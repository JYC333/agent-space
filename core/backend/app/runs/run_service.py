"""
RunService — Run creation and lifecycle.

This service owns Run creation, inspection, and cancellation.
It does NOT execute runs, call adapters, create sandboxes, or dispatch jobs.

Responsibilities:
  - Run creation uses Agent.current_version_id (no new AgentVersion created)
  - Run starts with status=queued
  - ContextSnapshot is created and linked
  - mode=dry_run only records the mode (no preview artifact/proposal until execute)
  - Stop only changes status to cancelled

Delegation:
  - Delegation metadata and depth limits are enforced here (single choke point).
  - Optional adapter_type on RunCreate is validated against the target agent version policy.
"""

from __future__ import annotations

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Run, ContextSnapshot, ActivityRecord, Artifact, Agent, AgentVersion
from ..schemas import RunCreate
from ..visibility.auth import can_read_scoped_object


_VALID_MODES = {"live", "dry_run"}
_VALID_RUN_TYPES = {"agent", "system", "workflow", "validation", "reflection", "export"}
_VALID_TRIGGER_ORIGINS = {"manual", "automation", "job", "parent_run", "system"}
_TERMINAL_STATUSES = {"succeeded", "failed", "degraded", "cancelled"}
_STOPABLE_STATUSES = {"queued", "running", "waiting_for_review"}


def _new_id() -> str:
    return str(ULID())


class RunService:
    def __init__(self, db: DBSession):
        self.db = db

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_agent_version(
        self, agent, agent_version_id: str, space_id: str
    ) -> None:
        """
        Verify agent_version_id belongs to the given agent and space.
        Raises HTTPException 400 if validation fails.
        """
        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent_version_id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=400,
                detail=f"AgentVersion '{agent_version_id}' not found",
            )
        if version.agent_id != agent.id:
            raise HTTPException(
                status_code=400,
                detail=f"AgentVersion '{agent_version_id}' does not belong to Agent '{agent.id}'",
            )
        if version.space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail=f"AgentVersion '{agent_version_id}' does not belong to this space",
            )

    def _validate_workspace_space(self, workspace_id: str, space_id: str) -> None:
        from ..models import Workspace
        ws = self.db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            raise HTTPException(status_code=400, detail=f"Workspace '{workspace_id}' not found")
        if ws.owner_space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail=f"Workspace '{workspace_id}' does not belong to this space",
            )

    def _validate_session_space(self, session_id: str, space_id: str) -> None:
        from ..models import Session
        session = self.db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=400, detail=f"Session '{session_id}' not found")
        if session.space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail=f"Session '{session_id}' does not belong to this space",
            )

    def _runtime_policy_for_agent(self, agent: Agent) -> dict:
        if not agent.current_version_id:
            return {}
        v = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == agent.current_version_id)
            .first()
        )
        return dict(v.runtime_policy_json or {}) if v else {}

    def _policy_engine(self):
        from ..policy import PolicyEngine

        return PolicyEngine()

    def _validate_run_target_agent(self, agent: Agent, space_id: str) -> None:
        d = self._policy_engine().check(
            {
                "action": "agent.run",
                "space_id": space_id,
                "resource_space_id": agent.space_id,
                "agent_status": agent.status,
            }
        )
        if d.denied:
            raise HTTPException(status_code=409, detail=d.reason)

    def _validate_adapter_for_target(self, agent: Agent, adapter_type: str, space_id: str) -> None:
        policy = self._runtime_policy_for_agent(agent)
        allowed = policy.get("allowed_adapter_types")
        if allowed is None or not isinstance(allowed, list) or len(allowed) == 0:
            return
        d = self._policy_engine().check(
            {
                "action": "tool.execute",
                "space_id": space_id,
                "tool_name": adapter_type,
                "agent_tool_permissions": allowed,
            }
        )
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

    def _resolve_delegation(
        self,
        *,
        data: RunCreate,
        space_id: str,
    ) -> tuple[str | None, int, str | None]:
        """Return ``(parent_run_id, delegation_depth, instructed_by_agent_id)`` for the new Run."""
        if not data.parent_run_id:
            return None, 0, None

        parent = (
            self.db.query(Run)
            .filter(Run.id == data.parent_run_id)
            .first()
        )
        if not parent:
            raise HTTPException(
                status_code=404,
                detail=f"Parent run '{data.parent_run_id}' not found",
            )
        if parent.space_id != space_id:
            raise HTTPException(
                status_code=400,
                detail="Cross-space parent_run_id is not allowed",
            )

        delegator_id = data.instructed_by_agent_id or parent.agent_id
        delegator = (
            self.db.query(Agent)
            .filter(Agent.id == delegator_id, Agent.space_id == space_id)
            .first()
        )
        if not delegator:
            raise HTTPException(
                status_code=404,
                detail=f"Delegating agent '{delegator_id}' not found in this space",
            )

        policy = self._runtime_policy_for_agent(delegator)
        d = self._policy_engine().check(
            {
                "action": "agent.delegate",
                "space_id": space_id,
                "resource_space_id": delegator.space_id,
                "agent_status": delegator.status,
                "can_delegate": policy.get("can_delegate", True),
                "delegation_depth": parent.delegation_depth,
                "max_delegation_depth": policy.get("max_delegation_depth", 3),
            }
        )
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        next_depth = parent.delegation_depth + 1
        return parent.id, next_depth, delegator_id

    # ------------------------------------------------------------------
    # Run creation
    # ------------------------------------------------------------------

    def create_run(
        self,
        agent_id: str,
        data: RunCreate,
        space_id: str,
        user_id: str,
    ) -> Run:
        """
        Create a Run for the given Agent using its current AgentVersion.

        Requirements:
        - Agent must exist in the current space and have current_version_id
        - AgentVersion must belong to the same agent and space
        - Run starts with status=queued
        - ContextSnapshot is created and linked
        - No AgentVersion is created
        - No real execution is triggered

        Raises HTTPException:
        - 404 if Agent not found in this space
        - 400 if Agent.current_version_id is null
        - 400 if AgentVersion doesn't belong to this agent/space
        - 422 if mode/run_type/trigger_origin is invalid
        - 400 if workspace_id/session_id is in a different space
        """
        from ..models import Agent

        # 1. Validate Agent exists and belongs to this space
        agent = self.db.query(Agent).filter(
            Agent.id == agent_id,
            Agent.space_id == space_id,
        ).first()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in this space")

        # 2. Validate Agent has current_version_id
        if not agent.current_version_id:
            raise HTTPException(
                status_code=400,
                detail=f"Agent '{agent_id}' has no current version. Create an AgentVersion first.",
            )

        # 3. Validate AgentVersion belongs to this agent and space
        self._validate_agent_version(agent, agent.current_version_id, space_id)

        # 4. Validate mode, run_type, trigger_origin
        if data.mode not in _VALID_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid mode '{data.mode}'. Must be one of: {', '.join(sorted(_VALID_MODES))}",
            )
        if data.run_type not in _VALID_RUN_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid run_type '{data.run_type}'. Must be one of: {', '.join(sorted(_VALID_RUN_TYPES))}",
            )
        if data.trigger_origin not in _VALID_TRIGGER_ORIGINS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid trigger_origin '{data.trigger_origin}'. Must be one of: {', '.join(sorted(_VALID_TRIGGER_ORIGINS))}",
            )

        # 5. Validate workspace_id if provided
        if data.workspace_id:
            self._validate_workspace_space(data.workspace_id, space_id)

        # 6. Validate session_id if provided
        if data.session_id:
            self._validate_session_space(data.session_id, space_id)

        self._validate_run_target_agent(agent, space_id)
        if data.adapter_type:
            self._validate_adapter_for_target(agent, data.adapter_type, space_id)

        parent_run_id, delegation_depth, instructed_by_agent_id = self._resolve_delegation(
            data=data,
            space_id=space_id,
        )

        # Agent→agent delegation (``trigger_origin=parent_run`` + ``instructed_by_agent_id``)
        # leaves ``instructed_by_user_id`` unset; user-initiated runs keep the caller id.
        effective_user_id = user_id
        if (
            parent_run_id
            and data.trigger_origin == "parent_run"
            and data.instructed_by_agent_id is not None
        ):
            effective_user_id = None

        # 7. Create minimal ContextSnapshot
        snapshot = ContextSnapshot(
            id=_new_id(),
            space_id=space_id,
            source_refs_json=[],
            compiled_summary=None,
            token_estimate=None,
        )
        self.db.add(snapshot)

        # 8. Validate and resolve execution plane; snapshot its observability/exposure/trust metadata.
        # Priority: runtime_adapter_id → execution_plane_id → adapter_type lookup.
        execution_plane_id = getattr(data, "execution_plane_id", None)
        runtime_adapter_id = getattr(data, "runtime_adapter_id", None)
        model_provider_id = getattr(data, "model_provider_id", None)

        # Validate FK references belong to this space (prevent cross-space injection).
        if runtime_adapter_id:
            from ..models import RuntimeAdapter as _RA
            if not self.db.query(_RA).filter(
                _RA.id == runtime_adapter_id, _RA.space_id == space_id
            ).first():
                raise HTTPException(
                    status_code=400,
                    detail=f"RuntimeAdapter '{runtime_adapter_id}' not found in this space",
                )
        if model_provider_id:
            from ..models import ModelProvider as _MP
            if not self.db.query(_MP).filter(
                _MP.id == model_provider_id, _MP.space_id == space_id
            ).first():
                raise HTTPException(
                    status_code=400,
                    detail=f"ModelProvider '{model_provider_id}' not found in this space",
                )

        observability_level = None
        data_exposure_level = None
        trust_level = None
        externality_level = None

        resolved_plane = None
        if runtime_adapter_id or execution_plane_id or data.adapter_type:
            from ..execution_planes.service import ExecutionPlaneService
            ep_svc = ExecutionPlaneService(self.db)
            if runtime_adapter_id:
                resolved_plane = ep_svc.resolve_execution_plane_for_runtime(
                    runtime_adapter_id, space_id
                )
            if not resolved_plane and execution_plane_id:
                resolved_plane = ep_svc.get_execution_plane(execution_plane_id, space_id)
            if not resolved_plane and data.adapter_type:
                resolved_plane = ep_svc.get_default_execution_plane(space_id, data.adapter_type)

            if resolved_plane:
                execution_plane_id = resolved_plane.id
                observability_level = resolved_plane.observability_level
                data_exposure_level = resolved_plane.data_exposure_level
                trust_level = resolved_plane.trust_level
                externality_level = ep_svc.externality_level_for_plane(resolved_plane)

        # 9. Create Run with status=queued, mode from request, agent_version from current
        run = Run(
            id=_new_id(),
            space_id=space_id,
            agent_id=agent.id,
            agent_version_id=agent.current_version_id,
            context_snapshot_id=snapshot.id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            parent_run_id=parent_run_id,
            instructed_by_user_id=effective_user_id,
            instructed_by_agent_id=instructed_by_agent_id,
            delegation_depth=delegation_depth,
            run_type=data.run_type,
            trigger_origin=data.trigger_origin,
            status="queued",
            mode=data.mode,
            prompt=data.prompt,
            instruction=data.instruction,
            scheduled_at=data.scheduled_at,
            adapter_type=data.adapter_type,
            required_sandbox_level="none",
            source="managed",
            execution_plane_id=execution_plane_id,
            runtime_adapter_id=runtime_adapter_id,
            model_provider_id=model_provider_id,
            observability_level=observability_level,
            data_exposure_level=data_exposure_level,
            trust_level=trust_level,
            externality_level=externality_level,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # ------------------------------------------------------------------
    # Run inspection
    # ------------------------------------------------------------------

    def get_run(self, run_id: str, space_id: str, *, user_id: str | None = None) -> Run:
        """Get a Run by id, scoped to space_id."""
        run = (
            self.db.query(Run)
            .filter(Run.id == run_id, Run.space_id == space_id)
            .first()
        )
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in this space")
        if user_id is not None and not can_read_scoped_object(
            visibility=run.visibility,
            owner_user_id=run.instructed_by_user_id,
            current_user_id=user_id,
            is_space_member=True,
        ):
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found in this space")
        return run

    def list_runs(
        self,
        space_id: str,
        status: str | None = None,
        mode: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        user_id: str | None = None,
    ) -> list[Run]:
        """List runs scoped to space, with optional filters."""
        q = self.db.query(Run).filter(Run.space_id == space_id)
        if status:
            q = q.filter(Run.status == status)
        if mode:
            q = q.filter(Run.mode == mode)
        if agent_id:
            q = q.filter(Run.agent_id == agent_id)
        if workspace_id:
            q = q.filter(Run.workspace_id == workspace_id)
        rows = q.order_by(Run.created_at.desc()).all()
        if user_id is not None:
            rows = [
                r for r in rows
                if can_read_scoped_object(
                    visibility=r.visibility,
                    owner_user_id=r.instructed_by_user_id,
                    current_user_id=user_id,
                    is_space_member=True,
                )
            ]
        return rows[offset : offset + limit]

    def list_run_activities(
        self,
        run_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[ActivityRecord]]:
        """List activity records for a Run (read-only; space-scoped)."""
        self.get_run(run_id, space_id)
        q = (
            self.db.query(ActivityRecord)
            .filter(
                ActivityRecord.space_id == space_id,
                ActivityRecord.source_run_id == run_id,
            )
        )
        total = q.count()
        items = (
            q.order_by(ActivityRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, items

    def list_run_artifacts(
        self,
        run_id: str,
        space_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        artifact_type: str | None = None,
    ) -> tuple[int, list[Artifact]]:
        """List artifacts for a Run (read-only; space-scoped)."""
        self.get_run(run_id, space_id)
        q = self.db.query(Artifact).filter(
            Artifact.space_id == space_id,
            Artifact.run_id == run_id,
        )
        if artifact_type:
            q = q.filter(Artifact.artifact_type == artifact_type)
        total = q.count()
        items = q.order_by(Artifact.created_at.desc()).offset(offset).limit(limit).all()
        return total, items

    # ------------------------------------------------------------------
    # Run cancellation
    # ------------------------------------------------------------------

    def stop_run(self, run_id: str, space_id: str) -> tuple[Run, bool]:
        """
        Cancel a Run by setting its status to 'cancelled'.

        Only affects runs in queued, running, or waiting_for_review states.
        Runs in terminal states (succeeded, failed, degraded, cancelled) are
        returned as-is with changed=False.

        Returns (run, changed) tuple.
        """
        run = self.get_run(run_id, space_id)

        if run.status not in _STOPABLE_STATUSES:
            # Already terminal — return as-is
            return run, False

        run.status = "cancelled"
        run.ended_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(run)
        return run, True