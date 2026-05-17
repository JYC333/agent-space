from __future__ import annotations

"""Canonical active Policy row loading and domain-scoped decisions."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .domains import (
    ALL_REGISTERED_DOMAINS,
    MEMORY_WRITE_DIRECT,
    SECURITY_SENSITIVE_DOMAINS,
)


class ActivePolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ALLOW_WITH_LOG = "allow_with_log"
    NO_POLICY = "no_policy"


@dataclass(frozen=True)
class ActivePolicyMatch:
    decision: ActivePolicyDecision
    policy_id: str | None = None
    policy_key: str | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_effect(value: Any) -> ActivePolicyDecision | None:
    raw = str(value or "").strip().lower()
    if raw == ActivePolicyDecision.DENY.value:
        return ActivePolicyDecision.DENY
    if raw == ActivePolicyDecision.REQUIRE_APPROVAL.value:
        return ActivePolicyDecision.REQUIRE_APPROVAL
    if raw == ActivePolicyDecision.ALLOW_WITH_LOG.value:
        return ActivePolicyDecision.ALLOW_WITH_LOG
    if raw == ActivePolicyDecision.ALLOW.value:
        return ActivePolicyDecision.ALLOW
    return None


def load_active_policy_rows(
    db: Any,
    *,
    space_id: str,
    policy_domain_column: str | None = None,
) -> list[Any]:
    """
    Canonical query for active Policy rows in deterministic priority order.

    Only ``enabled`` rows with ``status == active`` are returned.
    """
    if db is None or not space_id:
        return []

    from ..models import Policy

    q = (
        db.query(Policy)
        .filter(
            Policy.space_id == space_id,
            Policy.enabled.is_(True),
            Policy.status == "active",
        )
        .order_by(Policy.priority.desc(), Policy.created_at.desc(), Policy.id.desc())
    )
    if policy_domain_column is not None:
        q = q.filter(Policy.domain == policy_domain_column)
    return q.all()


def _row_matches_domain(row: Any, domain: str) -> bool:
    if row.policy_key == domain:
        return True
    rule_json = _as_dict(row.rule_json)
    policy_json = _as_dict(row.policy_json)
    applies_to = _as_dict(row.applies_to_json)
    domain_key = (
        rule_json.get("policy_domain")
        or policy_json.get("policy_domain")
        or applies_to.get("policy_domain")
    )
    if domain_key == domain:
        return True
    if domain.startswith("memory.") and row.domain == "memory":
        suffix = domain.split(".", 1)[1]
        if row.policy_key in (domain, suffix):
            return True
    if domain.startswith("run.") and row.domain == "run":
        suffix = domain.split(".", 1)[1]
        if row.policy_key in (domain, suffix):
            return True
    return False


def row_matches_write_direct(row: Any, *, action: str, resource_type: str) -> bool:
    """Match persisted rows for ``memory.write_direct`` (PolicyEngine)."""
    if row.policy_key in (MEMORY_WRITE_DIRECT, "memory.write_direct.guard"):
        rule_json = _as_dict(row.rule_json)
        policy_json = _as_dict(row.policy_json)
        applies_to = _as_dict(row.applies_to_json)
        row_action = (
            rule_json.get("action")
            or policy_json.get("action")
            or applies_to.get("action")
            or MEMORY_WRITE_DIRECT
        )
        row_resource_type = (
            rule_json.get("resource_type")
            or policy_json.get("resource_type")
            or applies_to.get("resource_type")
            or "memory"
        )
        return row_action == action and row_resource_type == resource_type

    rule_json = _as_dict(row.rule_json)
    policy_json = _as_dict(row.policy_json)
    applies_to = _as_dict(row.applies_to_json)
    policy_type = (
        rule_json.get("policy_type")
        or policy_json.get("policy_type")
        or applies_to.get("policy_type")
        or row.policy_key
    )
    row_action = (
        rule_json.get("action")
        or policy_json.get("action")
        or applies_to.get("action")
    )
    row_resource_type = (
        rule_json.get("resource_type")
        or policy_json.get("resource_type")
        or applies_to.get("resource_type")
    )
    if policy_type not in ("memory_write", "memory_write_direct"):
        return False
    return row_action == action and row_resource_type == resource_type


def load_active_policies_for_domain(db: Any, *, space_id: str, domain: str) -> list[Any]:
    if domain not in ALL_REGISTERED_DOMAINS:
        return []
    rows = load_active_policy_rows(db, space_id=space_id)
    return [row for row in rows if _row_matches_domain(row, domain)]


def load_active_policies_for_write_direct(
    db: Any,
    *,
    space_id: str,
    action: str,
    resource_type: str,
) -> list[Any]:
    if action != MEMORY_WRITE_DIRECT or resource_type != "memory":
        return []
    rows = load_active_policy_rows(db, space_id=space_id, policy_domain_column="memory")
    return [row for row in rows if row_matches_write_direct(row, action=action, resource_type=resource_type)]


def get_active_policy_match(
    db: Any,
    *,
    space_id: str,
    domain: str,
    action_context: dict[str, Any] | None = None,
) -> ActivePolicyMatch:
    """Return the winning active policy match for ``domain``."""
    _ = action_context
    if domain not in ALL_REGISTERED_DOMAINS:
        return ActivePolicyMatch(decision=ActivePolicyDecision.NO_POLICY)

    for row in load_active_policies_for_domain(db, space_id=space_id, domain=domain):
        rule_json = _as_dict(row.rule_json)
        policy_json = _as_dict(row.policy_json)
        effect = _normalize_effect(
            row.enforcement_mode or rule_json.get("effect") or policy_json.get("effect")
        )
        if effect is None:
            if domain in SECURITY_SENSITIVE_DOMAINS:
                return ActivePolicyMatch(
                    decision=ActivePolicyDecision.DENY,
                    policy_id=row.id,
                    policy_key=row.policy_key,
                )
            continue
        return ActivePolicyMatch(
            decision=effect,
            policy_id=row.id,
            policy_key=row.policy_key,
        )

    return ActivePolicyMatch(decision=ActivePolicyDecision.NO_POLICY)


def get_active_policy_decision(
    db: Any,
    *,
    space_id: str,
    domain: str,
    action_context: dict[str, Any] | None = None,
) -> ActivePolicyDecision:
    return get_active_policy_match(
        db, space_id=space_id, domain=domain, action_context=action_context
    ).decision


def policy_allows(decision: ActivePolicyDecision) -> bool:
    return decision in (ActivePolicyDecision.ALLOW, ActivePolicyDecision.ALLOW_WITH_LOG)


def policy_denies(decision: ActivePolicyDecision) -> bool:
    return decision in (ActivePolicyDecision.DENY, ActivePolicyDecision.REQUIRE_APPROVAL)
