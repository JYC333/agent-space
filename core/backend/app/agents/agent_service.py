from __future__ import annotations
"""
AgentService — CRUD for Agent configurations and multi-agent run orchestration.

Separation of concerns:
  - AgentService  — manages Agent records; owns delegation policy; calls PolicyEngine
  - AgentRunService (runner.py) — low-level adapter execution and run logging

Two run entry points:
  run()    — synchronous; used by tests and agent-to-agent delegation.
  submit() — creates pending record only; HTTP layer schedules async execution.
"""

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException

from ..models import Agent, AgentRun
from ..schemas import (
    AgentCreate, AgentUpdate, AgentRunRequest,
    DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY,
)
from ..config import settings
from ..policy import PolicyEngine, PolicyDecision
from ..policy.decisions import Decision
from ..router.task_router import TaskRouter

_task_router = TaskRouter()


def _new_id() -> str:
    return str(ULID())


_engine = PolicyEngine()


def _decision_snapshot(decision: PolicyDecision) -> dict:
    return {
        "decision": decision.decision.value,
        "reason": decision.reason,
        "risk_level": decision.risk_level.value,
        "policy_rule_id": decision.policy_rule_id,
    }


class AgentService:
    def __init__(self, db: DBSession):
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, data: AgentCreate, requesting_user_id: str | None = None) -> Agent:
        agent = Agent(
            id=_new_id(),
            space_id=data.space_id or settings.default_space_id,
            created_by_user_id=data.created_by_user_id or requesting_user_id or settings.default_user_id,
            name=data.name,
            description=data.description,
            visibility=data.visibility,
            role_instruction=data.role_instruction,
            model_config_json=data.model_config_json or DEFAULT_MODEL_CONFIG.copy(),
            memory_policy_json=data.memory_policy_json or DEFAULT_MEMORY_POLICY.copy(),
            capabilities_json=data.capabilities_json or [],
            tool_policy_json=data.tool_policy_json or [],
            runtime_policy_json=data.runtime_policy_json or DEFAULT_RUNTIME_POLICY.copy(),
            status="active",
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return (
            self.db.query(Agent)
            .filter(Agent.id == agent_id, Agent.deleted_at.is_(None))
            .first()
        )

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
        q = self.db.query(Agent).filter(
            Agent.space_id == space_id,
            Agent.deleted_at.is_(None),
        )
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
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(agent, field, value)
        agent.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete(self, agent_id: str) -> bool:
        agent = self.get(agent_id)
        if not agent:
            return False
        agent.deleted_at = datetime.now(UTC)
        agent.status = "archived"
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Policy checks (all via PolicyEngine — no scattered inline checks)
    # ------------------------------------------------------------------

    def _check_run(self, agent: Agent, adapter_type: str, space_id: str) -> PolicyDecision:
        """Run all policy checks for a user→agent run. Raises HTTP 4xx on deny."""
        # 1. Agent must be active
        d = _engine.check({
            "action": "agent.run",
            "space_id": space_id,
            "resource_space_id": agent.space_id,
            "agent_status": agent.status,
        })
        if d.denied:
            raise HTTPException(status_code=409, detail=d.reason)

        # 2. Adapter must be in allowed list (checked in runtime_policy_json for back-compat)
        allowed = (agent.runtime_policy_json or {}).get("allowed_adapter_types")
        d = _engine.check({
            "action": "tool.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        return d

    def _check_delegate(
        self,
        delegating_agent: Agent,
        parent_run: AgentRun,
        target_agent: Agent,
        adapter_type: str,
        space_id: str,
    ) -> PolicyDecision:
        """Run all policy checks for agent→agent delegation. Raises HTTP 4xx on deny."""
        rt = delegating_agent.runtime_policy_json or {}

        # 1. can_delegate + depth
        d = _engine.check({
            "action": "agent.delegate",
            "space_id": space_id,
            "resource_space_id": delegating_agent.space_id,
            "agent_status": delegating_agent.status,
            "can_delegate": rt.get("can_delegate", True),
            "delegation_depth": parent_run.delegation_depth,
            "max_delegation_depth": rt.get("max_delegation_depth", 3),
        })
        if d.denied:
            raise HTTPException(status_code=403, detail=d.reason)

        # 2. Target agent must be active
        d2 = _engine.check({
            "action": "agent.run",
            "space_id": space_id,
            "resource_space_id": target_agent.space_id,
            "agent_status": target_agent.status,
        })
        if d2.denied:
            raise HTTPException(status_code=409, detail=d2.reason)

        # 3. Adapter allowed on target
        allowed = (target_agent.runtime_policy_json or {}).get("allowed_adapter_types")
        d3 = _engine.check({
            "action": "tool.execute",
            "space_id": space_id,
            "tool_name": adapter_type,
            "agent_tool_permissions": allowed,
        })
        if d3.denied:
            raise HTTPException(status_code=403, detail=d3.reason)

        return d

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    def _resolve_adapter_type(self, req: AgentRunRequest) -> str:
        """Apply TaskRouter: downgrade CLI adapters to anthropic_api when not needed."""
        classification = _task_router.classify_from_request(
            task_type=req.task_type,
            risk_level=req.risk_level,
            requires_filesystem=req.requires_filesystem,
            requires_terminal=req.requires_terminal,
            requires_git=req.requires_git,
            requires_long_reasoning=req.requires_long_reasoning,
        )
        return _task_router.resolve_adapter(req.adapter_type, classification)

    # ------------------------------------------------------------------
    # Synchronous run (tests + delegation)
    # ------------------------------------------------------------------

    def run(
        self,
        agent_id: str,
        req: AgentRunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> AgentRun:
        """
        Synchronous user→agent run. Validates, builds context, executes adapter.
        Returns a completed (or failed) AgentRun.
        """
        from .runner import AgentRunService
        from ..memory.context_builder import ContextBuilder

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        decision = self._check_run(agent, adapter_type, space_id)

        context = ContextBuilder(self.db).build(
            space_id=space_id,
            user_id=instructed_by_user_id or settings.default_user_id,
            workspace_id=req.workspace_id,
            agent_memory_policy=agent.memory_policy_json,
            agent_id=agent_id,
        ).model_dump()

        timeout = (agent.runtime_policy_json or {}).get("max_run_time_seconds", 300)

        return AgentRunService(self.db).run(
            prompt=req.prompt,
            context=context,
            adapter_type=adapter_type,
            space_id=space_id,
            user_id=instructed_by_user_id or settings.default_user_id,
            agent_id=agent_id,
            instructed_by_user_id=instructed_by_user_id,
            instructed_by_agent_id=None,
            parent_run_id=None,
            delegation_depth=0,
            workspace_id=req.workspace_id,
            permission_snapshot_json=_decision_snapshot(decision),
            workspace_path=req.workspace_path,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Async submit (HTTP layer — returns pending run for BackgroundTask)
    # ------------------------------------------------------------------

    def submit(
        self,
        agent_id: str,
        req: AgentRunRequest,
        space_id: str,
        instructed_by_user_id: str | None = None,
    ) -> AgentRun:
        """
        Validate + create a pending AgentRun. Does NOT execute the adapter.
        The HTTP route schedules execute_pending_run() as a FastAPI BackgroundTask.
        Returns the pending AgentRun immediately (status='pending').
        """
        from .runner import AgentRunService
        from ..memory.context_builder import ContextBuilder

        adapter_type = self._resolve_adapter_type(req)
        agent = self.get_or_404(agent_id)
        decision = self._check_run(agent, adapter_type, space_id)

        context = ContextBuilder(self.db).build(
            space_id=space_id,
            user_id=instructed_by_user_id or settings.default_user_id,
            workspace_id=req.workspace_id,
            agent_memory_policy=agent.memory_policy_json,
            agent_id=agent_id,
        ).model_dump()

        timeout = (agent.runtime_policy_json or {}).get("max_run_time_seconds", 300)

        return AgentRunService(self.db).create_pending(
            prompt=req.prompt,
            context=context,
            adapter_type=adapter_type,
            space_id=space_id,
            user_id=instructed_by_user_id or settings.default_user_id,
            agent_id=agent_id,
            instructed_by_user_id=instructed_by_user_id,
            instructed_by_agent_id=None,
            parent_run_id=None,
            delegation_depth=0,
            workspace_id=req.workspace_id,
            permission_snapshot_json=_decision_snapshot(decision),
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Delegation (always synchronous — called from within a background run)
    # ------------------------------------------------------------------

    def delegate(
        self,
        target_agent_id: str,
        req: AgentRunRequest,
        space_id: str,
        parent_run_id: str,
        instructed_by_agent_id: str,
    ) -> AgentRun:
        """Agent → Agent delegation. Validates policy then dispatches a child run."""
        from .runner import AgentRunService
        from ..memory.context_builder import ContextBuilder

        parent_run = self.db.query(AgentRun).filter(AgentRun.id == parent_run_id).first()
        if not parent_run:
            raise HTTPException(status_code=404, detail=f"Parent run '{parent_run_id}' not found")

        delegating_agent = self.get_or_404(instructed_by_agent_id)
        target_agent = self.get_or_404(target_agent_id)

        decision = self._check_delegate(
            delegating_agent, parent_run, target_agent, req.adapter_type, space_id
        )

        next_depth = parent_run.delegation_depth + 1

        context = ContextBuilder(self.db).build(
            space_id=space_id,
            user_id=parent_run.user_id,
            workspace_id=req.workspace_id,
            agent_memory_policy=target_agent.memory_policy_json,
            agent_id=target_agent_id,
        ).model_dump()

        timeout = (target_agent.runtime_policy_json or {}).get("max_run_time_seconds", 300)

        return AgentRunService(self.db).run(
            prompt=req.prompt,
            context=context,
            adapter_type=req.adapter_type,
            space_id=space_id,
            user_id=parent_run.user_id,
            agent_id=target_agent_id,
            instructed_by_user_id=None,
            instructed_by_agent_id=instructed_by_agent_id,
            parent_run_id=parent_run_id,
            delegation_depth=next_depth,
            workspace_id=req.workspace_id,
            permission_snapshot_json=_decision_snapshot(decision),
            workspace_path=req.workspace_path,
            timeout=timeout,
        )
