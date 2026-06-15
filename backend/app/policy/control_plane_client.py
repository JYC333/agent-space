"""Internal client for TS-owned policy enforcement."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Optional

import httpx

from ..config import settings
from .approval import get_space_role
from .decisions import Decision, PolicyDecision, RiskLevel
from .exceptions import PolicyAuditPersistError, PolicyGateBlocked
from .gateway import PolicyCheckRequest, PolicyGateway
from .proposal_apply import supported_proposal_apply_types


class ControlPlanePolicyError(Exception):
    """Raised when an internal policy call to control-plane fails unexpectedly."""


def policy_owned_by_control_plane() -> bool:
    return (settings.control_plane_policy_authority or "").strip().lower() == "ts"


def _internal_base_url() -> str:
    base_url = (settings.control_plane_internal_url or "").strip().rstrip("/")
    if not base_url:
        raise ControlPlanePolicyError(
            "CONTROL_PLANE_INTERNAL_URL is required when policy is owned by control-plane."
        )
    return base_url


def _internal_token() -> str:
    token = (settings.control_plane_internal_token or "").strip()
    if not token:
        raise ControlPlanePolicyError(
            "CONTROL_PLANE_INTERNAL_TOKEN is required when policy is owned by control-plane."
        )
    return token


def _post_internal(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_internal_base_url()}{path}"
    headers = {
        "content-type": "application/json",
        "x-agent-space-internal-token": _internal_token(),
    }
    try:
        with httpx.Client(timeout=settings.control_plane_internal_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ControlPlanePolicyError(
            f"Control-plane policy call failed: {exc.__class__.__name__}"
        ) from exc

    if response.status_code >= 400:
        detail: Any
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise ControlPlanePolicyError(str(detail or f"HTTP {response.status_code}"))

    try:
        value = response.json()
    except ValueError as exc:
        raise ControlPlanePolicyError("Control-plane policy returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ControlPlanePolicyError("Control-plane policy returned an invalid response")
    return value


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _decision_from_wire(value: Any) -> PolicyDecision:
    if not isinstance(value, dict):
        raise ControlPlanePolicyError("Control-plane policy response is missing a decision")
    try:
        decision = Decision(value["decision"])
        risk_level = RiskLevel(value.get("risk_level") or RiskLevel.LOW.value)
    except (KeyError, ValueError) as exc:
        raise ControlPlanePolicyError(
            "Control-plane policy response contains an invalid decision"
        ) from exc
    return PolicyDecision(
        decision=decision,
        message=str(value.get("message") or ""),
        risk_level=risk_level,
        reason_code=value.get("reason_code"),
        required_approver_role=value.get("required_approver_role"),
        policy_rule_id=value.get("policy_rule_id"),
        policy_source=str(value.get("policy_source") or "builtin"),
        policy_id=value.get("policy_id"),
        actor_type=value.get("actor_type"),
        actor_id=value.get("actor_id"),
        actor_ref=value.get("actor_ref"),
        space_id=value.get("space_id"),
        action=value.get("action"),
        resource_type=value.get("resource_type"),
        resource_id=value.get("resource_id"),
        audit_code=value.get("audit_code"),
        approval_capability=value.get("approval_capability"),
        proposal_type=value.get("proposal_type"),
        metadata_json=value.get("metadata_json"),
        created_at=_parse_created_at(value.get("created_at")),
    )


def _raise_blocked_from_check(req: PolicyCheckRequest, decision: PolicyDecision) -> None:
    resource_type = req.resource_type or decision.resource_type
    proposal_id = req.proposal_id
    if proposal_id is None and resource_type == "proposal":
        proposal_id = req.resource_id or decision.resource_id
    raise PolicyGateBlocked(
        decision=decision,
        action=req.action,
        actor_type=req.actor_type or decision.actor_type,
        actor_id=req.actor_id or decision.actor_id,
        actor_ref=req.actor_ref or decision.actor_ref,
        space_id=req.space_id or decision.space_id,
        resource_type=resource_type,
        resource_id=req.resource_id or decision.resource_id,
        run_id=req.run_id,
        proposal_id=proposal_id,
        metadata_json=req.metadata_json or decision.metadata_json,
        http_status_code=403,
        audit_already_persisted=True,
    )


def _proposal_payload(proposal: Any) -> dict[str, Any]:
    payload = getattr(proposal, "payload_json", None)
    return payload if isinstance(payload, dict) else {}


def _raise_blocked_from_proposal(
    *,
    user_id: str,
    space_id: str,
    proposal: Any,
    decision: PolicyDecision,
    metadata_json: Optional[dict[str, Any]],
) -> None:
    raise PolicyGateBlocked(
        decision=decision,
        action="proposal.apply",
        actor_type="user",
        actor_id=user_id,
        actor_ref=None,
        space_id=space_id,
        resource_type="proposal",
        resource_id=str(getattr(proposal, "id")),
        run_id=None,
        proposal_id=str(getattr(proposal, "id")),
        metadata_json=metadata_json or decision.metadata_json,
        http_status_code=403,
        audit_already_persisted=True,
    )


class ControlPlanePolicyGateway:
    """PolicyPort implementation backed by the TS control-plane policy module."""

    def __init__(self, db: Any):
        self.db = db

    def enforce(self, req: PolicyCheckRequest) -> PolicyDecision:
        payload = asdict(req)
        value = _post_internal("/internal/policy/enforce", payload)
        status = value.get("status")
        decision = _decision_from_wire(value.get("decision")) if value.get("decision") else None
        if status == "allow" and decision is not None:
            return decision
        if status == "blocked" and decision is not None:
            _raise_blocked_from_check(req, decision)
        if status == "error" and value.get("error_code") == "policy_audit_persist_failed":
            raise PolicyAuditPersistError(action=req.action, actor_id=req.actor_id)
        raise ControlPlanePolicyError(
            str(value.get("message") or "Control-plane policy returned an invalid result")
        )

    def enforce_proposal_apply(
        self,
        user_id: str,
        space_id: str,
        proposal: Any,
        metadata_json: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        payload = {
            "user_id": user_id,
            "space_id": space_id,
            "proposal_id": str(getattr(proposal, "id")),
            "proposal_type": str(getattr(proposal, "proposal_type")),
            "risk_level": getattr(proposal, "risk_level", None),
            "membership_role": get_space_role(self.db, user_id, space_id),
            "supported_proposal_types": sorted(supported_proposal_apply_types()),
            "payload": _proposal_payload(proposal),
            "metadata_json": metadata_json,
        }
        value = _post_internal("/internal/policy/enforce-proposal-apply", payload)
        status = value.get("status")
        decision = _decision_from_wire(value.get("decision")) if value.get("decision") else None
        if status == "allow" and decision is not None:
            return decision
        if status == "blocked" and decision is not None:
            _raise_blocked_from_proposal(
                user_id=user_id,
                space_id=space_id,
                proposal=proposal,
                decision=decision,
                metadata_json=metadata_json,
            )
        if status == "error" and value.get("error_code") == "policy_audit_persist_failed":
            raise PolicyAuditPersistError(action="proposal.apply", actor_id=user_id)
        raise ControlPlanePolicyError(
            str(value.get("message") or "Control-plane policy returned an invalid result")
        )


def get_policy_port(db: Any):
    """Return the active PolicyPort implementation for the current authority."""
    if policy_owned_by_control_plane():
        return ControlPlanePolicyGateway(db)
    return PolicyGateway(db)


__all__ = [
    "ControlPlanePolicyError",
    "ControlPlanePolicyGateway",
    "get_policy_port",
    "policy_owned_by_control_plane",
]
