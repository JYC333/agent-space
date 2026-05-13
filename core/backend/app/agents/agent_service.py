from __future__ import annotations
"""
AgentService — CRUD for Agent configurations and multi-agent run orchestration.

Separation of concerns:
  - AgentService   — manages Agent records + AgentVersion lifecycle + policy checks
  - RunService     — owns Run creation and lifecycle
  - Runner module  — adapter registry + post-run hooks

Agent identity fields (name, description, visibility, status) live on Agent.
Execution configuration lives on AgentVersion (append-only).
PATCH with execution config fields creates a new AgentVersion and advances
current_version_id. Prior versions are never modified.
Run execution reads runtime_policy from the current AgentVersion.

run(), submit(), and delegate() create Runs via RunService (status=queued).
Adapter execution, Artifact/Proposal/MemoryEntry materialization, and sandbox
work happen in RunExecutionService — not in AgentService.
"""

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Agent, Run, AgentVersion
from ..schemas import (
    AgentCreate, AgentUpdate, RunRequest,
    AgentVersionCreate,
    RunCreate,
    DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY,
)
from ..config import settings

_task_router = None
_engine = None


def _new_id() -> str:
    return str(ULID())


def _get_task_router():
    global _task_router
    if _task_router is None:
        from ..router.task_router import TaskRouter
        _task_router = TaskRouter()
    return _task_router


def _get_engine():
    global _engine
    if _engine is None:
        from ..policy import PolicyEngine
        _engine = PolicyEngine()
    return _engine


class AgentService:
    def __init__(self, db: DBSession):
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: AgentCreate, requesting_user_id: str | None = None) -> Agent:
        from .version_service import AgentVersionService
        space_id = data.space_id or settings.default_space_id
        owner_user_id = data.created_by_user_id or requesting_user_id or settings.default_user_id

        version_svc = AgentVersionService(self.db)

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
        from .version_service import AgentVersionService
        agent = self.get(agent_id)
        if not agent:
            return None

        identity_fields = {}
        exec_field_names = {
            "model_config_json", "memory_policy_json", "capabilities_json",
            "tool_policy_json", "runtime_policy_json",
        }

        update_dict = data.model_dump(exclude_none=True)
        for field, value in update_dict.items():
            if field not in exec_field_names:
                identity_fields[field] = value

        for field, value in identity_fields.items():
            setattr(agent, field, value)

        has_exec_config = any(fn in update_dict for fn in exec_field_names)

        if has_exec_config:
            version_svc = AgentVersionService(self.db)
            version_dict = {}

            if agent.current_version_id:
                current = version_svc.get_or_404(agent.current_version_id)
                current_vals = {
                    "model_config_json": current.model_config_json,
                    "memory_policy_json": current.memory_policy_json,
                    "capabilities_json": current.capabilities_json,
                    "tool_permissions_json": current.tool_permissions_json,
                    "runtime_policy_json": current.runtime_policy_json,
                }
                for k, v in current_vals.items():
                    version_dict[k] = v
                for field in ["model_config_json", "memory_policy_json", "capabilities_json",
                              "tool_policy_json", "runtime_policy_json"]:
                    if field in update_dict and update_dict[field] is not None:
                        if field == "tool_policy_json":
                            version_dict["tool_permissions_json"] = update_dict[field]
                        else:
                            version_dict[field] = update_dict[field]
            else:
                for field in ["model_config_json", "memory_policy_json", "capabilities_json",
                              "tool_policy_json", "runtime_policy_json"]:
                    if field in update_dict and update_dict[field] is not None:
                        if field == "tool_policy_json":
                            version_dict["tool_permissions_json"] = update_dict[field]
                        else:
                            version_dict[field] = update_dict[field]
                    else:
                        if field == "model_config_json":
                            version_dict[field] = DEFAULT_MODEL_CONFIG.copy()
                        elif field == "memory_policy_json":
                            version_dict[field] = DEFAULT_MEMORY_POLICY.copy()
                        elif field == "runtime_policy_json":
                            version_dict[field] = DEFAULT_RUNTIME_POLICY.copy()
                        elif field == "capabilities_json":
                            version_dict[field] = []

            version_data = AgentVersionCreate(**version_dict)
            new_version = version_svc.create(agent_id=agent.id, space_id=agent.space_id, data=version_data)
            agent.current_version_id = new_version.id

        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

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
        """Run all policy checks for a user→agent run. Raises HTTP 4xx on deny."""
        engine = _get_engine()

        d = engine.check({
            "action": "agent.run",
            "space_id": space_id,
            "resource_space_id": agent.space_id,
            "agent_status": agent.status,
        })
        if d.denied:
            raise HTTPException(status_code=409, detail=d.reason)

        _, runtime_policy = self._get_policy_fields(agent)
        allowed = runtime_policy.get("allowed_adapter_types")
        d = engine.check({
            "action": "tool.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        memory_policy, _ = self._get_policy_fields(agent)
        return d, memory_policy, runtime_policy

    def _check_delegate(
        self,
        delegating_agent: Agent,
        parent_run: Run,
        target_agent: Agent,
        adapter_type: str,
        space_id: str,
    ) -> tuple:
        """Run all policy checks for agent→agent delegation. Raises HTTP 4xx on deny."""
        engine = _get_engine()

        _, delegator_runtime = self._get_policy_fields(delegating_agent)

        d = engine.check({
            "action": "agent.delegate",
            "space_id": space_id,
            "resource_space_id": delegating_agent.space_id,
            "agent_status": delegating_agent.status,
            "can_delegate": delegator_runtime.get("can_delegate", True),
            "delegation_depth": parent_run.delegation_depth,
            "max_delegation_depth": delegator_runtime.get("max_delegation_depth", 3),
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        d2 = engine.check({
            "action": "agent.run",
            "space_id": space_id,
            "resource_space_id": target_agent.space_id,
            "agent_status": target_agent.status,
        })
        if d2.denied:
            raise HTTPException(status_code=409, detail=d2.reason)

        delegator_memory, _ = self._get_policy_fields(delegating_agent)
        _, target_runtime = self._get_policy_fields(target_agent)
        allowed = target_runtime.get("allowed_adapter_types")
        d3 = engine.check({
            "action": "tool.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d3.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        return d, delegator_memory, target_runtime

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

        # Legacy fields already set on Run via RunCreate; keep explicit user id for callers.
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

    # ------------------------------------------------------------------
    # Delegation — creates a queued Run for the delegating agent
    # ------------------------------------------------------------------

    def delegate(
        self,
        target_agent_id: str,
        req: RunRequest,
        space_id: str,
        parent_run_id: str,
        instructed_by_agent_id: str,
    ) -> Run:
        """
        Create a Run for agent→agent delegation.
        Returns a queued Run via RunService. No adapter execution here.
        """
        from app.runs.run_service import RunService

        parent_run = self.db.query(Run).filter(Run.id == parent_run_id).first()
        if not parent_run:
            raise HTTPException(status_code=404, detail=f"Parent run '{parent_run_id}' not found")

        delegating_agent = self.get_or_404(instructed_by_agent_id)
        target_agent = self.get_or_404(target_agent_id)

        adapter_type = self._resolve_adapter_type(req)
        self._check_delegate(delegating_agent, parent_run, target_agent, adapter_type, space_id)

        run_svc = RunService(self.db)
        run = run_svc.create_run(
            agent_id=target_agent_id,
            data=RunCreate(
                mode="live",
                run_type="agent",
                trigger_origin="parent_run",
                workspace_id=req.workspace_id,
                parent_run_id=parent_run_id,
                instructed_by_agent_id=instructed_by_agent_id,
                adapter_type=adapter_type,
                prompt=req.prompt,
            ),
            space_id=space_id,
            user_id=parent_run.user_id or settings.default_user_id,
        )
        return run