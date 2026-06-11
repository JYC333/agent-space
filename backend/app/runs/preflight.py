"""Runtime preflight service — validates all execution preconditions without starting a run.

POST /api/v1/runs/preflight returns a structured result listing errors and warnings
so callers (UI, automation scheduler) can verify a run would succeed before creating one.

Preflight does NOT:
  - start a run or mutate DB state
  - create sandboxes
  - write workspace files
  - enforce sensitive actions or persist PolicyDecisionRecord
  - call any external API or subprocess (except lightweight CLI availability checks)

Policy simulation contract: PreflightService may call PolicyEngine directly only to
predict whether a prospective runtime.execute request would be allowed. It is a
non-mutating dry-run, not an enforcement point. Real runtime execution must go
through PolicyGateway and record decisions there when required.

Resolution contract: preflight resolves adapter_type and required_sandbox_level using the
exact same priority order as RunExecutionService + resolve_runtime_adapter + compute_runtime_policy_decision.
Request-level overrides that execution would not honour (risk_level, runtime_adapter_id) are
intentionally absent from PreflightRequest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..runtimes.command_renderer import CommandRenderError, resolve_executable_for_detection

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / output schemas
# ---------------------------------------------------------------------------


class PreflightRequest(BaseModel):
    """What the caller wants to check.

    space_id is NOT included here — it always comes from the authenticated identity
    and is passed separately to PreflightService.check(). Clients must not submit
    space_id in the body.

    risk_level and runtime_adapter_id are NOT included here. Preflight cannot
    simulate a prospective Run.runtime_adapter_id because that field is not
    accepted by this request schema. It can simulate prospective Run.adapter_type
    through adapter_type, and otherwise uses AgentVersion/runtime policy fields
    in the same order as execution.

    extra="forbid" ensures obsolete fields (space_id, risk_level, runtime_adapter_id)
    are rejected with 422 rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    workspace_id: str | None = None
    trigger_origin: str = "manual"
    adapter_type: str | None = None


class PreflightResult(BaseModel):
    """Structured preflight outcome."""

    model_config = ConfigDict(arbitrary_types_allowed=False)

    executable: bool
    adapter_type: str | None = None
    required_sandbox_level: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Preflight service
# ---------------------------------------------------------------------------


@dataclass
class _PreflightState:
    space_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adapter_type: str | None = None
    required_sandbox_level: str | None = None
    runtime_adapter_id: str | None = None
    runtime_adapter_config_json: dict[str, Any] = field(default_factory=dict)
    executable_path_override: str | None = None


class PreflightService:
    """Validate runtime execution preconditions without mutating or auditing decisions.

    Direct PolicyEngine evaluation in this service is simulation only. Enforcement
    of an actual runtime execution remains the responsibility of PolicyGateway.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def check(self, req: PreflightRequest, space_id: str) -> PreflightResult:
        """Run all preflight checks.

        space_id must come from the authenticated identity, never from the request body.
        """
        state = _PreflightState(space_id=space_id)
        self._check_agent(req, state)
        if not state.errors:
            self._check_adapter(req, state)
        if not state.errors:
            self._check_risk_level(req, state)
        if not state.errors:
            self._check_workspace(req, state)
        if not state.errors:
            self._check_cli_availability(req, state)
        if not state.errors:
            self._check_credential_profile(req, state)
        if not state.errors:
            self._check_code_patch_possible(req, state)

        return PreflightResult(
            executable=len(state.errors) == 0,
            adapter_type=state.adapter_type,
            required_sandbox_level=state.required_sandbox_level,
            warnings=state.warnings,
            errors=state.errors,
        )

    # ------------------------------------------------------------------
    # Individual checks — resolution order mirrors the visible execution inputs
    # ------------------------------------------------------------------

    def _check_agent(self, req: PreflightRequest, state: _PreflightState) -> None:
        from ..models import Agent, AgentVersion
        from ..policy import PolicyEngine

        agent = (
            self.db.query(Agent)
            .filter(Agent.id == req.agent_id, Agent.space_id == state.space_id)
            .first()
        )
        if agent is None:
            state.errors.append(f"Agent '{req.agent_id}' not found in space '{state.space_id}'")
            return

        # Dry-run simulation only: do not use PolicyGateway or write an audit
        # decision here. RunExecutionService enforces runtime.execute through
        # PolicyGateway before actual execution.
        d = PolicyEngine().check({
            "action": "runtime.execute",
            "space_id": state.space_id,
            "resource_space_id": agent.space_id,
            "agent_status": agent.status,
        })
        if d.denied:
            state.errors.append(f"Agent is not runnable: {d.message}")
            return

        if not agent.current_version_id:
            state.errors.append(f"Agent '{req.agent_id}' has no current AgentVersion")
            return

        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent.current_version_id)
            .first()
        )
        if version is None:
            state.errors.append(f"AgentVersion '{agent.current_version_id}' not found")

    def _check_adapter(self, req: PreflightRequest, state: _PreflightState) -> None:
        """Resolve the adapter using the same visible fields as execution.

        Full execution can use Run.runtime_adapter_id first; PreflightRequest
        intentionally has no runtime_adapter_id, so this check starts at
        AgentVersion.runtime_adapter_id and then treats req.adapter_type as the
        prospective Run.adapter_type.
        """
        from ..models import Agent, AgentVersion
        from ..router import AdapterResolutionError, RouterService

        agent = (
            self.db.query(Agent)
            .filter(Agent.id == req.agent_id, Agent.space_id == state.space_id)
            .first()
        )
        if agent is None or not agent.current_version_id:
            return

        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent.current_version_id)
            .first()
        )
        if version is None:
            return

        try:
            resolved = RouterService(self.db).resolve_preflight_adapter(
                space_id=state.space_id,
                version=version,
                requested_adapter_type=req.adapter_type,
            )
        except AdapterResolutionError as exc:
            state.errors.append(f"{exc.error_code}: {exc.message}")
            return

        row = resolved.runtime_adapter_row
        if row is not None:
            state.runtime_adapter_id = row.id
            state.runtime_adapter_config_json = dict(row.config_json or {})
            raw_override = state.runtime_adapter_config_json.get("executable_path")
            state.executable_path_override = str(raw_override) if raw_override else None

        state.adapter_type = resolved.adapter_type

    def _check_risk_level(self, req: PreflightRequest, state: _PreflightState) -> None:
        """Mirror compute_runtime_policy_decision exactly.

        risk_level is read exclusively from AgentVersion.runtime_policy_json — the same
        source RunExecutionService uses. There is no request-level risk_level override.
        """
        from ..models import Agent, AgentVersion
        from .runtime_policy import (
            _norm_risk,
            required_sandbox_level_for_risk,
        )

        agent = (
            self.db.query(Agent)
            .filter(Agent.id == req.agent_id, Agent.space_id == state.space_id)
            .first()
        )
        if agent is None or not agent.current_version_id:
            return
        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent.current_version_id)
            .first()
        )
        if version is None:
            return

        policy = dict(version.runtime_policy_json or {})
        # Read risk_level from policy only — mirrors compute_runtime_policy_decision
        risk = _norm_risk(policy.get("risk_level"))
        level = required_sandbox_level_for_risk(risk)
        state.required_sandbox_level = level

        if level == "one_shot_docker":
            state.errors.append(
                "critical_runtime_requires_unimplemented_one_shot_docker: "
                "risk_level=critical requires one_shot_docker sandbox which is not implemented. "
                "Use risk_level=high (worktree) for mutating CLI runs."
            )
            return

        adapter_type = state.adapter_type or ""
        try:
            from ..runtimes import get_runtime_adapter_spec
            spec = get_runtime_adapter_spec(adapter_type)
            requires_file_access = spec.sandbox.requires_file_access
            minimum_level = spec.sandbox.minimum_sandbox_level
        except KeyError:
            requires_file_access = False
            minimum_level = "none"
        if requires_file_access and level != minimum_level:
            state.errors.append(
                f"file_access_adapter_requires_worktree_policy: "
                f"adapter_type='{adapter_type}' requires {minimum_level} sandbox but "
                f"risk_level='{risk}' resolves to required_sandbox_level='{level}'. "
                "Set risk_level=high in runtime_policy_json."
            )

    def _check_workspace(self, req: PreflightRequest, state: _PreflightState) -> None:
        from ..models import Workspace
        from ..workspace.disk_path import workspace_absolute_root
        from ..workspace.root_validation import (
            WorkspaceRootValidationError,
            validate_workspace_root_for_execution,
        )

        if state.required_sandbox_level != "worktree":
            return

        if not req.workspace_id:
            state.errors.append(
                "workspace_id is required for worktree-level runs but was not provided"
            )
            return

        ws = (
            self.db.query(Workspace)
            .filter(Workspace.id == req.workspace_id)
            .first()
        )
        if ws is None:
            state.errors.append(f"Workspace '{req.workspace_id}' not found")
            return

        if ws.space_id != state.space_id:
            state.errors.append(
                f"Workspace '{req.workspace_id}' does not belong to space '{state.space_id}'"
            )
            return

        resolved_root = workspace_absolute_root(ws)
        try:
            validate_workspace_root_for_execution(
                workspace_space_id=ws.space_id,
                run_space_id=state.space_id,
                workspace_root=resolved_root,
                allow_external_root=getattr(ws, "allow_external_root", False),
                sandbox_level=state.required_sandbox_level,
            )
        except WorkspaceRootValidationError as exc:
            state.errors.append(f"{exc.error_code}: {exc.message}")

    def _check_cli_availability(self, req: PreflightRequest, state: _PreflightState) -> None:
        adapter_type = state.adapter_type or ""
        try:
            from ..runtimes import get_runtime_adapter_spec
            spec = get_runtime_adapter_spec(adapter_type)
        except KeyError:
            return
        if spec.runtime_kind != "local_cli":
            return
        try:
            resolve_executable_for_detection(spec, state.executable_path_override)
        except CommandRenderError as exc:
            state.warnings.append(
                f"{exc.error_code}: {exc.message}. "
                "The run will fail unless the executable is available before execution."
            )

    def _check_credential_profile(self, req: PreflightRequest, state: _PreflightState) -> None:
        adapter_type = state.adapter_type or ""
        try:
            from ..runtimes import get_runtime_adapter_spec
            spec = get_runtime_adapter_spec(adapter_type)
        except KeyError:
            return
        if spec.credentials.credential_mode != "cli_profile":
            return

        runtime = spec.credentials.credential_runtime_name or adapter_type
        try:
            from ..models import Agent, AgentVersion, RuntimeAdapter
            from ..credentials.broker import CredentialBroker
            broker = CredentialBroker()
            profile_id = None
            agent = (
                self.db.query(Agent)
                .filter(Agent.id == req.agent_id, Agent.space_id == state.space_id)
                .first()
            )
            if agent and agent.current_version_id:
                version = (
                    self.db.query(AgentVersion)
                    .filter(AgentVersion.id == agent.current_version_id)
                    .first()
                )
                if version and version.runtime_adapter_id:
                    row = (
                        self.db.query(RuntimeAdapter)
                        .filter(
                            RuntimeAdapter.id == version.runtime_adapter_id,
                            RuntimeAdapter.space_id == state.space_id,
                        )
                        .first()
                    )
                    profile_id = getattr(row, "credential_profile_id", None) if row else None
            ready = broker.profile_ready(runtime, profile_id)
            if not ready:
                state.errors.append(
                    f"runtime_credential_profile_required: "
                    f"Runtime adapter '{adapter_type}' "
                    "requires an explicit credential profile. "
                    "No credential profile is configured."
                )
        except Exception as exc:
            state.warnings.append(
                f"Could not verify credential profiles: {exc!s}. "
                "Automation runs may fail at execution time."
            )

    def _check_code_patch_possible(self, req: PreflightRequest, state: _PreflightState) -> None:
        adapter_type = state.adapter_type or ""
        try:
            from ..runtimes import get_runtime_adapter_spec
            requires_file_access = get_runtime_adapter_spec(adapter_type).sandbox.requires_file_access
        except KeyError:
            requires_file_access = False

        if not requires_file_access:
            return

        if state.required_sandbox_level != "worktree":
            return

        if not req.workspace_id:
            state.warnings.append(
                "code_patch proposals cannot be collected: workspace_id is not set. "
                "File changes will not be surfaced for review."
            )
