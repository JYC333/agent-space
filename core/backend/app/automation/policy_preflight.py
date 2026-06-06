"""Automation policy preflight simulation.

This module predicts whether an automation-origin run would be blocked by the
same policy gates that RunExecutionService enforces before adapter invocation.
It is not enforcement: it never calls PolicyGateway, never persists
PolicyDecisionRecord, and never mutates business rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..models import Agent, AgentVersion, RuntimeAdapter
from ..policy.decisions import PolicyDecision
from ..policy.engine import PolicyEngine
from ..policy.gateway import PolicyCheckRequest
from ..policy.hard_invariants import HardInvariantGuard
from ..runs.adapter_resolution import ResolvedRuntimeAdapter
from ..runs.policy_inputs import (
    CredentialPolicyMetadataError,
    build_runtime_execute_policy_request,
    build_runtime_use_credential_policy_request,
    resolve_runtime_credential_policy_metadata,
)
from ..runs.runtime_policy import _norm_risk, required_sandbox_level_for_risk
from ..runs.runtime_policy import RuntimePolicyDecision
from ..runtimes.requirements import (
    UnknownRuntimeRequirementsError,
    get_runtime_requirements,
)


class AutomationPolicyPreflightCheck(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=False)

    action: str
    decision: str | None = None
    allowed: bool = False
    reason_code: str | None = None
    policy_rule_id: str | None = None
    audit_code: str | None = None
    message: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AutomationPolicyPreflightResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=False)

    executable: bool
    checks: list[AutomationPolicyPreflightCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _ResolvedAdapterMetadata:
    adapter_type: str | None
    runtime_adapter_row: RuntimeAdapter | None
    error: str | None = None


class AutomationPolicyPreflightService:
    """Read-only policy preflight simulation for automation-origin runs."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._engine = PolicyEngine()
        self._guard = HardInvariantGuard()

    def check(
        self,
        *,
        space_id: str,
        agent_id: str,
        workspace_id: str | None = None,
        trigger_origin: str = "automation",
        pre_authorized: bool = False,
    ) -> AutomationPolicyPreflightResult:
        errors: list[str] = []
        warnings: list[str] = []
        checks: list[AutomationPolicyPreflightCheck] = []

        agent = (
            self.db.query(Agent)
            .filter(Agent.id == agent_id, Agent.space_id == space_id)
            .first()
        )
        if agent is None:
            return AutomationPolicyPreflightResult(
                executable=False,
                errors=[f"Agent '{agent_id}' not found in space '{space_id}'"],
            )
        if not agent.current_version_id:
            return AutomationPolicyPreflightResult(
                executable=False,
                errors=[f"Agent '{agent_id}' has no current AgentVersion"],
            )

        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent.current_version_id)
            .first()
        )
        if version is None:
            return AutomationPolicyPreflightResult(
                executable=False,
                errors=[f"AgentVersion '{agent.current_version_id}' not found"],
            )

        policy = dict(version.runtime_policy_json or {})
        risk_level = _norm_risk(policy.get("risk_level"))
        required_sandbox_level = required_sandbox_level_for_risk(risk_level)
        runtime_policy_decision = RuntimePolicyDecision(
            required_sandbox_level=required_sandbox_level,
            risk_level=risk_level,
            policy_snapshot={
                "risk_level": risk_level,
                "required_sandbox_level": required_sandbox_level,
                "allowed_adapter_types": policy.get("allowed_adapter_types"),
                "allowed_model_providers": policy.get("allowed_model_providers"),
            },
        )
        resolved_adapter = self._resolve_adapter(version=version, policy=policy)
        if resolved_adapter.error:
            errors.append(resolved_adapter.error)

        adapter_type = resolved_adapter.adapter_type
        try:
            runtime_requirements = get_runtime_requirements(adapter_type)
        except UnknownRuntimeRequirementsError as exc:
            errors.append(str(exc))
            runtime_requirements = get_runtime_requirements(None)

        run_like = SimpleNamespace(
            id=f"automation-preflight:{agent_id}",
            space_id=space_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            workspace_id=workspace_id,
            instructed_by_user_id=None,
            trigger_origin=trigger_origin,
            model_provider_id=None,
            data_exposure_level=None,
            trust_level=None,
            observability_level=None,
        )
        resolved_runtime_adapter = ResolvedRuntimeAdapter(
            adapter_type=adapter_type,
            runtime_adapter_row=resolved_adapter.runtime_adapter_row,
            merged_config={},
        )
        runtime_execute_req = build_runtime_execute_policy_request(
            run_like,
            version,
            resolved_runtime_adapter,
            runtime_policy_decision,
            agent.status,
        )
        checks.append(self._simulate_request(runtime_execute_req))

        try:
            credential_subject = resolve_runtime_credential_policy_metadata(
                self.db,
                run_like,
                version,
                resolved_runtime_adapter,
                runtime_requirements,
            )
        except CredentialPolicyMetadataError as exc:
            errors.append(f"{exc.error_code}: {exc.message}")
            credential_subject = None
        if credential_subject is not None:
            checks.append(
                self._simulate_request(
                    build_runtime_use_credential_policy_request(
                        run_like,
                        credential_subject,
                        runtime_policy_decision,
                        adapter_type,
                        automation_pre_authorized=pre_authorized,
                    )
                )
            )

        checks.append(
            self._simulate(
                "context.inject_memory",
                {
                    "action": "context.inject_memory",
                    "space_id": space_id,
                    "resource_space_id": space_id,
                    "trigger_origin": trigger_origin,
                },
                metadata_json={"workspace_id": workspace_id},
            )
        )
        checks.append(
            self._simulate(
                "context.render_for_runtime",
                {
                    "action": "context.render_for_runtime",
                    "space_id": space_id,
                    "resource_space_id": space_id,
                    "has_personal_grant_context": False,
                },
                metadata_json={"workspace_id": workspace_id, "adapter_type": adapter_type},
            )
        )

        for check in checks:
            if not check.allowed:
                errors.append(
                    f"{check.action}: {check.decision} "
                    f"({check.reason_code or check.policy_rule_id}) {check.message or ''}".strip()
                )

        return AutomationPolicyPreflightResult(
            executable=len(errors) == 0,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    def _simulate(
        self,
        action: str,
        ctx: dict[str, Any],
        *,
        metadata_json: dict[str, Any] | None = None,
    ) -> AutomationPolicyPreflightCheck:
        guard_ctx = dict(ctx)
        if metadata_json:
            guard_ctx["metadata_json"] = metadata_json
        invariant = self._guard.check(guard_ctx)
        decision = invariant if invariant is not None else self._engine.check(ctx)
        return self._check_from_decision(
            action,
            decision,
            metadata_json=metadata_json or {},
        )

    def _simulate_request(self, req: PolicyCheckRequest) -> AutomationPolicyPreflightCheck:
        ctx: dict[str, Any] = {"action": req.action}
        if req.space_id:
            ctx["space_id"] = req.space_id
        if req.resource_space_id:
            ctx["resource_space_id"] = req.resource_space_id
        if req.actor_id:
            ctx["actor_id"] = req.actor_id
        if req.actor_ref:
            ctx["actor_ref"] = req.actor_ref
        if req.resource_type:
            ctx["resource_type"] = req.resource_type
        if req.resource_id:
            ctx["resource_id"] = req.resource_id
        if req.context:
            ctx.update(req.context)
        return self._simulate(req.action, ctx, metadata_json=req.metadata_json)

    def _check_from_decision(
        self,
        action: str,
        decision: PolicyDecision,
        *,
        metadata_json: dict[str, Any],
    ) -> AutomationPolicyPreflightCheck:
        return AutomationPolicyPreflightCheck(
            action=action,
            decision=decision.decision.value,
            allowed=decision.allowed,
            reason_code=decision.reason_code,
            policy_rule_id=decision.policy_rule_id,
            audit_code=decision.audit_code,
            message=decision.message,
            metadata_json=metadata_json,
        )

    def _resolve_adapter(
        self,
        *,
        version: AgentVersion,
        policy: dict[str, Any],
    ) -> _ResolvedAdapterMetadata:
        row: RuntimeAdapter | None = None
        adapter_type: str | None = None
        if version.runtime_adapter_id:
            row = (
                self.db.query(RuntimeAdapter)
                .filter(
                    RuntimeAdapter.id == version.runtime_adapter_id,
                    RuntimeAdapter.space_id == version.space_id,
                )
                .first()
            )
            if row is None:
                return _ResolvedAdapterMetadata(
                    adapter_type=None,
                    runtime_adapter_row=None,
                    error=(
                        "adapter_not_configured: AgentVersion.runtime_adapter_id "
                        "points to a missing RuntimeAdapter row"
                    ),
                )
            if not row.enabled:
                return _ResolvedAdapterMetadata(
                    adapter_type=row.adapter_type,
                    runtime_adapter_row=row,
                    error=f"adapter_disabled: RuntimeAdapter '{row.id}' is disabled",
                )
            adapter_type = row.adapter_type
        else:
            runtime_config = dict(version.runtime_config_json or {})
            adapter_type = (
                (runtime_config.get("adapter_type") or "").strip()
                or (str(policy.get("default_adapter_type") or "").strip())
            )
        return _ResolvedAdapterMetadata(
            adapter_type=adapter_type,
            runtime_adapter_row=row,
        )
