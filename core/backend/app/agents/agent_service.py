from __future__ import annotations
"""
AgentService — CRUD for Agent configurations and multi-agent run orchestration.

Separation of concerns:
  - AgentService   — manages Agent records + AgentVersion lifecycle + policy checks
  - RunService     — owns Run creation and lifecycle
  - Runner module  — adapter registry + post-run hooks

Agent identity fields (name, description, visibility, status) live on Agent.
Execution configuration lives on AgentVersion (append-only).
PATCH only changes identity fields; post-create execution configuration changes
must be accepted through an agent_config_update proposal.
Run execution reads runtime_policy from the current AgentVersion.

run() and submit() create Runs via RunService (status=queued).
Adapter execution, Artifact/Proposal/MemoryEntry materialization, and sandbox
work happen in RunExecutionService — not in AgentService.
"""

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Agent, Run, AgentVersion, ModelProvider
from ..schemas import (
    AgentCreate, AgentUpdate, RunRequest,
    AgentConfigProposalCreate,
    AgentVersionCreate,
    RunCreate,
    AgentOut, AgentModelSummary,
    DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY,
)
from ..config import settings

_task_router = None


def _new_id() -> str:
    return str(ULID())


def _get_task_router():
    global _task_router
    if _task_router is None:
        from ..router.task_router import TaskRouter
        _task_router = TaskRouter()
    return _task_router


class AgentService:
    def __init__(self, db: DBSession):
        self.db = db

    def _validate_model_provider(self, provider_id: str | None, space_id: str) -> None:
        if not provider_id:
            return
        from ..providers.service import ModelService
        try:
            ModelService().assert_selectable(self.db, provider_id, space_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _model_summary_for_agent(self, agent: Agent) -> AgentModelSummary | None:
        if not agent.current_version_id:
            return None
        version = self.db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        if not version or not version.model_provider_id:
            if version and version.model_name:
                return AgentModelSummary(model=version.model_name)
            return None
        provider = self.db.query(ModelProvider).filter(
            ModelProvider.id == version.model_provider_id
        ).first()
        return AgentModelSummary(
            provider_id=version.model_provider_id,
            provider_name=provider.name if provider else None,
            provider_type=provider.provider_type if provider else None,
            model=version.model_name,
        )

    def to_agent_out(self, agent: Agent) -> AgentOut:
        return AgentOut(
            id=agent.id,
            space_id=agent.space_id,
            created_by_user_id=agent.owner_user_id or settings.default_user_id,
            name=agent.name,
            description=agent.description,
            visibility=agent.visibility,
            role_instruction=agent.role_instruction,
            status=agent.status,
            current_version_id=agent.current_version_id,
            model=self._model_summary_for_agent(agent),
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _version_fields_from_current(self, agent: Agent) -> dict:
        base = {
            "model_provider_id": None,
            "model_name": None,
            "model_config_json": DEFAULT_MODEL_CONFIG.copy(),
            "memory_policy_json": DEFAULT_MEMORY_POLICY.copy(),
            "capabilities_json": [],
            "tool_permissions_json": {},
            "runtime_policy_json": DEFAULT_RUNTIME_POLICY.copy(),
        }
        if not agent.current_version_id:
            return base
        from .version_service import AgentVersionService
        current = AgentVersionService(self.db).get_or_404(agent.current_version_id)
        base.update({
            "model_provider_id": current.model_provider_id,
            "model_name": current.model_name,
            "model_config_json": current.model_config_json,
            "memory_policy_json": current.memory_policy_json,
            "capabilities_json": current.capabilities_json,
            "tool_permissions_json": current.tool_permissions_json,
            "runtime_policy_json": current.runtime_policy_json,
        })
        return base

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: AgentCreate, requesting_user_id: str | None = None) -> Agent:
        from .version_service import AgentVersionService
        space_id = data.space_id or settings.default_space_id
        owner_user_id = data.created_by_user_id or requesting_user_id or settings.default_user_id

        version_svc = AgentVersionService(self.db)

        self._validate_model_provider(data.default_model_provider_id, space_id)
        if data.default_model and not data.default_model_provider_id:
            raise HTTPException(
                status_code=400,
                detail="default_model_provider_id is required when default_model is set",
            )

        agent = Agent(
            id=_new_id(),
            space_id=space_id,
            owner_user_id=owner_user_id,
            name=data.name,
            description=data.description,
            visibility=data.visibility,
            role_instruction=data.role_instruction,
            status="active",
        )
        self.db.add(agent)
        self.db.flush()

        version_data = AgentVersionCreate(
            model_provider_id=data.default_model_provider_id,
            model_name=data.default_model,
            model_config_json=dict(data.model_config_json or DEFAULT_MODEL_CONFIG),
            memory_policy_json=dict(data.memory_policy_json or DEFAULT_MEMORY_POLICY),
            capabilities_json=list(data.capabilities_json or []),
            tool_permissions_json=dict(data.tool_permissions_json or {}),
            runtime_policy_json=dict(data.runtime_policy_json or DEFAULT_RUNTIME_POLICY),
        )
        version = version_svc.create(
            agent_id=agent.id,
            space_id=space_id,
            data=version_data,
            label="v1",
        )
        agent.current_version_id = version.id

        self.db.commit()
        self.db.refresh(agent)
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self.db.query(Agent).filter(Agent.id == agent_id).first()

    def get_or_404(self, agent_id: str) -> Agent:
        agent = self.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        return agent

    def list(
        self,
        space_id: str,
        created_by_user_id: str | None = None,
        visibility: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Agent]:
        q = self.db.query(Agent).filter(Agent.space_id == space_id)
        if created_by_user_id:
            q = q.filter(Agent.created_by_user_id == created_by_user_id)
        if visibility:
            q = q.filter(Agent.visibility == visibility)
        if status:
            q = q.filter(Agent.status == status)
        return q.order_by(Agent.created_at.desc()).offset(offset).limit(limit).all()

    def update(self, agent_id: str, data: AgentUpdate) -> Agent | None:
        agent = self.get(agent_id)
        if not agent:
            return None

        exec_field_names = {
            "default_model_provider_id",
            "default_model",
            "model_provider_id",
            "model_name",
            "runtime_adapter_id",
            "system_prompt",
            "model_config_json",
            "runtime_config_json",
            "context_policy_json",
            "memory_policy_json",
            "capabilities_json",
            "tool_permissions_json",
            "tool_policy_json",
            "runtime_policy_json",
        }

        update_dict = data.model_dump(exclude_none=True)
        if any(fn in update_dict for fn in exec_field_names):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Agent execution configuration changes require an "
                    "agent_config_update proposal. Use POST /api/v1/agents/{agent_id}/config-proposals."
                ),
            )

        for field, value in update_dict.items():
            setattr(agent, field, value)

        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def create_config_update_proposal(
        self,
        agent_id: str,
        data: AgentConfigProposalCreate,
        *,
        user_id: str,
    ):
        from ..memory.proposals import ProposalService

        agent = self.get_or_404(agent_id)
        base = self.db.query(AgentVersion).filter(
            AgentVersion.id == data.base_version_id,
            AgentVersion.agent_id == agent.id,
            AgentVersion.space_id == agent.space_id,
        ).first()
        if base is None:
            raise HTTPException(status_code=404, detail="base AgentVersion not found for this agent")

        raw = data.model_dump(exclude_unset=True)
        raw.pop("base_version_id", None)
        changes = {k: v for k, v in raw.items()}
        if not changes:
            raise HTTPException(status_code=422, detail="No agent configuration changes provided")

        provider_id = changes.get("model_provider_id", base.model_provider_id)
        model_name = changes.get("model_name", base.model_name)
        if model_name and not provider_id:
            raise HTTPException(status_code=400, detail="model_provider_id is required when model_name is set")
        if provider_id:
            self._validate_model_provider(provider_id, agent.space_id)

        runtime_adapter_id = changes.get("runtime_adapter_id")
        if runtime_adapter_id:
            from ..models import RuntimeAdapter

            adapter = self.db.query(RuntimeAdapter).filter(
                RuntimeAdapter.id == runtime_adapter_id,
                RuntimeAdapter.space_id == agent.space_id,
            ).first()
            if adapter is None:
                raise HTTPException(status_code=400, detail="runtime_adapter_id does not belong to this space")

        payload = {
            "agent_id": agent.id,
            "base_version_id": data.base_version_id,
            "changes": changes,
        }
        changed_fields = sorted(changes)
        return ProposalService(self.db).create_user_proposal(
            space_id=agent.space_id,
            user_id=user_id,
            proposal_type="agent_config_update",
            title=f"Update agent config: {agent.name}",
            payload_json=payload,
            rationale="Agent configuration update requested via public API.",
            risk_level="high",
            urgency="normal",
            policy_action="agent.config_update",
            policy_resource_type="agent",
            policy_resource_id=agent.id,
            policy_context={
                "agent_id": agent.id,
                "agent_status": agent.status,
                "base_version_id": data.base_version_id,
                "changed_fields": changed_fields,
            },
            policy_metadata_json={
                "agent_id": agent.id,
                "base_version_id": data.base_version_id,
                "changed_fields": changed_fields,
                "model_provider_id": provider_id,
                "runtime_adapter_id": changes.get("runtime_adapter_id"),
            },
        )

    def delete(self, agent_id: str) -> bool:
        agent = self.get(agent_id)
        if not agent:
            return False
        agent.status = "archived"
        self.db.commit()
        return True

    def get_current_version(self, agent_id: str) -> AgentVersion | None:
        from .version_service import AgentVersionService
        agent = self.get_or_404(agent_id)
        if not agent.current_version_id:
            return None
        return AgentVersionService(self.db).get_or_404(agent.current_version_id)

    def create_version(
        self, agent_id: str, data: AgentVersionCreate, label: str | None = None
    ) -> AgentVersion:
        from .version_service import AgentVersionService
        agent = self.get_or_404(agent_id)
        version_svc = AgentVersionService(self.db)
        version = version_svc.create(
            agent_id=agent.id,
            space_id=agent.space_id,
            data=data,
            label=label,
        )
        agent.current_version_id = version.id
        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return version

    # ------------------------------------------------------------------
    # Policy checks
    # ------------------------------------------------------------------

    def _get_policy_fields(self, agent: Agent) -> tuple[dict, dict]:
        memory_policy = DEFAULT_MEMORY_POLICY.copy()
        runtime_policy = DEFAULT_RUNTIME_POLICY.copy()

        if agent.current_version_id:
            version = self.db.query(AgentVersion).filter(
                AgentVersion.id == agent.current_version_id
            ).first()
            if version:
                memory_policy = version.memory_policy_json or memory_policy
                runtime_policy = version.runtime_policy_json or runtime_policy

        return memory_policy, runtime_policy

    def _check_run(self, agent: Agent, adapter_type: str, space_id: str) -> tuple:
        """Non-mutating preflight checks before creating a queued run.

        Uses PolicyEngine directly (no PolicyDecisionRecord persisted here).
        Real enforcement with PolicyGateway.enforce runs in RunExecutionService.
        """
        from ..policy.engine import PolicyEngine

        engine = PolicyEngine()

        d = engine.check({
            "action": "runtime.execute",
            "space_id": space_id,
            "resource_space_id": agent.space_id,
            "agent_status": agent.status,
        })
        if d.denied:
            raise HTTPException(status_code=409, detail=d.message)

        _, runtime_policy = self._get_policy_fields(agent)
        allowed = runtime_policy.get("allowed_adapter_types")
        d = engine.check({
            "action": "runtime.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.message)

        memory_policy, _ = self._get_policy_fields(agent)
        return d, memory_policy, runtime_policy

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    def _resolve_adapter_type(self, req: RunRequest) -> str:
        router = _get_task_router()
        return router.resolve_adapter(
            req.adapter_type,
            router.classify_from_request(
                task_type=req.task_type,
                risk_level=req.risk_level,
                requires_filesystem=req.requires_filesystem,
                requires_terminal=req.requires_terminal,
                requires_git=req.requires_git,
                requires_long_reasoning=req.requires_long_reasoning,
            ),
        )

    # ------------------------------------------------------------------
    # Run creation via RunService (canonical path)
    # No adapter execution here (handled by RunExecutionService)
    # ------------------------------------------------------------------

    def run(
        self,
        agent_id: str,
        req: RunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> Run:
        """
        Create a Run for a user→agent request.
        Returns a queued Run via RunService. No adapter execution here.
        """
        from app.runs.run_service import RunService

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        self._check_run(agent, adapter_type, space_id)

        user_id = instructed_by_user_id or settings.default_user_id

        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode="live",
                run_type="agent",
                trigger_origin="manual",
                workspace_id=req.workspace_id,
                adapter_type=adapter_type,
                prompt=req.prompt,
            ),
            space_id=space_id,
            user_id=user_id,
        )

        # instructed_by_user_id must be set explicitly; RunCreate.user_id is the canonical source.
        run.instructed_by_user_id = user_id
        self.db.commit()
        return run

    # ------------------------------------------------------------------
    # Async submit — creates a queued Run for BackgroundTask dispatch
    # ------------------------------------------------------------------

    def submit(
        self,
        agent_id: str,
        req: RunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> Run:
        """
        Create a Run for an async HTTP request.
        Returns a queued Run via RunService. No adapter execution here.
        """
        from app.runs.run_service import RunService

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        self._check_run(agent, adapter_type, space_id)

        user_id = instructed_by_user_id or settings.default_user_id

        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode="live",
                run_type="agent",
                trigger_origin="manual",
                workspace_id=req.workspace_id,
                adapter_type=adapter_type,
                prompt=req.prompt,
            ),
            space_id=space_id,
            user_id=user_id,
        )

        run.instructed_by_user_id = user_id
        self.db.commit()
        return run
