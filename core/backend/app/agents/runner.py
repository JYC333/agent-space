from __future__ import annotations
"""
AgentRunService — low-level adapter execution and run logging.

Separation of concerns:
  - AgentService (agent_service.py) — owns agent config, delegation policy, context assembly
  - AgentRunService                 — owns the AgentRun record lifecycle + adapter dispatch

Two execution modes:
  run()           — synchronous; creates record + executes immediately. Used by tests
                    and by delegation (already in a background context).
  create_pending()— creates the AgentRun record with status="pending" and returns immediately.
                    The caller schedules execute_pending_run() as a BackgroundTask.

execute_pending_run() is a module-level function (not a method) so it can open its own
DB session in a FastAPI BackgroundTask after the request session has closed.
"""

import logging
from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

from ..models import AgentRun, ContextSnapshot
from ..config import settings
from .base import AgentAdapter, AgentRunResult
from .cli_adapter import EchoAgentAdapter
from .claude_adapter import ClaudeCLIAdapter
from .codex_adapter import CodexCLIAdapter
from .api_adapter import AnthropicAPIAdapter


def _new_id() -> str:
    return str(ULID())


_ADAPTER_REGISTRY: dict[str, type[AgentAdapter]] = {
    "echo": EchoAgentAdapter,
    "anthropic_api": AnthropicAPIAdapter,
    "claude_code": ClaudeCLIAdapter,
    "claude_cli": ClaudeCLIAdapter,  # legacy alias
    "codex_cli": CodexCLIAdapter,
}

# Adapters that require an isolated sandbox (worktree or Docker).
# These run LLM-generated code and must never execute on the host directly.
_SANDBOXED_ADAPTERS: frozenset[str] = frozenset({"claude_code", "claude_cli", "codex_cli"})


# ---------------------------------------------------------------------------
# Post-run hook registry
#
# Hooks are callables registered at import time (or by plugins/tests).
# Each hook receives the completed AgentRun and the result from the adapter.
# Hooks are fire-and-forget: exceptions are logged, never re-raised.
#
# Register a hook:
#   from app.agents.runner import register_post_run_hook
#   @register_post_run_hook
#   def my_hook(run: AgentRun, result: AgentRunResult | None) -> None:
#       ...
# ---------------------------------------------------------------------------

from typing import Callable
PostRunHook = Callable[["AgentRun", "AgentRunResult | None"], None]

_POST_RUN_HOOKS: list[PostRunHook] = []


def register_post_run_hook(fn: PostRunHook) -> PostRunHook:
    """Decorator / function to register a post-run hook."""
    _POST_RUN_HOOKS.append(fn)
    return fn


def _fire_post_run_hooks(run: "AgentRun", result: "AgentRunResult | None") -> None:
    for hook in _POST_RUN_HOOKS:
        try:
            hook(run, result)
        except Exception as exc:
            log.warning("post-run hook %s raised: %s", hook.__name__, exc)


# ---------------------------------------------------------------------------
# Module-level background executor (opens its own DB session)
# ---------------------------------------------------------------------------

def _resolve_adapter(
    adapter_type: str,
    run_id: str,
    workspace_path: str | None,
    risk_level: str = "medium",
) -> "tuple[AgentAdapter, str, str | None, str]":
    """
    Return (adapter, sandbox_level, sandbox_path, executor_type) for this run.

    Routing:
      - Non-sandboxed adapters (echo, …): run directly on the host.
      - Sandboxed adapters (claude_cli, codex_cli):
          low           → dry_run (context assembly only, no execution)
          medium        → worktree + local executor  ← default, no new container
          high/critical → one_shot_docker; falls back to worktree+local if Docker unavailable

    An agent can escalate risk_level but cannot downgrade a sandboxed adapter to echo.
    """
    from ..workspace.sandbox_manager import SandboxManager, SandboxLevel
    from .cli_adapter import LocalExecutor

    if adapter_type not in _SANDBOXED_ADAPTERS:
        cls = _ADAPTER_REGISTRY.get(adapter_type)
        if not cls:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        return cls(), "none", None, "local"

    mgr = SandboxManager()
    sandbox_level = mgr.resolve_level(risk_level)

    if sandbox_level == SandboxLevel.ONE_SHOT_DOCKER:
        if mgr.is_docker_available():
            adapter = mgr.get_docker_adapter(adapter_type, run_id, workspace_path)
            return adapter, sandbox_level.value, str(mgr.sandbox_path(run_id)), "docker"
        log.warning(
            "Docker unavailable for high-risk run %s — falling back to worktree+local "
            "(requires CLI in PATH; will fail if CLI is also missing)",
            run_id,
        )
        sandbox_level = SandboxLevel.WORKTREE

    if sandbox_level == SandboxLevel.DRY_RUN:
        cls = _ADAPTER_REGISTRY.get(adapter_type)
        return cls(), "dry_run", None, "local"

    # WORKTREE: git worktree (or plain dir) + local subprocess.
    # The CLI runs inside whatever process owns the backend — no new container spawned.
    # On bare-metal/WSL: runs on the host. In Docker Compose: runs inside the backend container.
    # The backend image installs claude/codex for exactly this reason.
    ctx = mgr.create_worktree(run_id, workspace_path)
    if adapter_type in ("claude_code", "claude_cli"):
        adapter = ClaudeCLIAdapter(executor=LocalExecutor(), sandbox_dir=str(ctx.sandbox_dir))
    else:
        adapter = CodexCLIAdapter(executor=LocalExecutor(), sandbox_dir=str(ctx.sandbox_dir))
    return adapter, ctx.level.value, str(ctx.sandbox_dir), "local"


def _save_context_snapshot(
    db: "Session",
    run: AgentRun,
    context: dict,
    compiled_content: str | None = None,
    target_format: str | None = None,
    scan_findings: list | None = None,
    secrets_found: bool = False,
    injection_risk: bool = False,
) -> ContextSnapshot:
    """
    Freeze the context package at run-start as an immutable ContextSnapshot.
    Called once, immediately before the adapter executes. Memory writes during
    the run must not mutate this record.
    """
    memory_ids: list[str] = []
    for section_key in ("user_memory", "workspace_memory", "capability_memory", "agent_memory", "system_policy", "relevant_episodes"):
        for item in context.get(section_key, []):
            mid = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
            if mid:
                memory_ids.append(mid)

    total_chars = len(compiled_content) if compiled_content else sum(
        len(str(v)) for v in context.values() if v
    )

    snap = ContextSnapshot(
        id=_new_id(),
        run_id=run.id,
        space_id=run.space_id,
        context_package=context,
        memory_ids=memory_ids,
        compiled_content=compiled_content,
        target_format=target_format,
        total_chars=total_chars,
        secrets_found=secrets_found,
        injection_risk=injection_risk,
        scan_findings=scan_findings or [],
    )
    db.add(snap)
    db.commit()
    return snap


def execute_pending_run(
    run_id: str,
    adapter_type: str,
    prompt: str,
    context: dict,
    workspace_path: str | None,
    timeout: int,
    risk_level: str = "medium",
    cli_adapter_config_id: str | None = None,
) -> None:
    """
    Execute the adapter for an already-created AgentRun (status=pending).
    Opens its own DB session — safe to call from FastAPI BackgroundTasks
    after the request session has been closed.

    Sandbox routing is risk-based:
      low      → dry_run (no execution, context assembly only)
      medium   → git worktree + local executor  ← default
      high/critical → one_shot_docker (falls back to worktree if Docker unavailable)

    Agent records can override risk_level via runtime_policy_json.risk_level.
    """
    from ..db import SessionLocal
    from ..models import Agent, CLIAdapterConfig
    from ..workspace.sandbox_manager import get_docker_semaphore
    db = SessionLocal()
    docker_sem = None
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if not run:
            return

        # Resolve adapter_type from CLIAdapterConfig if provided
        if cli_adapter_config_id:
            config = db.query(CLIAdapterConfig).filter(CLIAdapterConfig.id == cli_adapter_config_id).first()
            if config and config.enabled:
                adapter_type = config.adapter_id
                run.cli_adapter_config_id = cli_adapter_config_id
                db.commit()

        # Agent record can escalate risk level
        if run.agent_id:
            agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
            if agent:
                policy_risk = (agent.runtime_policy_json or {}).get("risk_level")
                if policy_risk:
                    risk_level = policy_risk

        # Acquire a Docker concurrency slot before marking as running (Docker runs only).
        # Non-Docker runs skip this; blocks here (run stays "pending") when at capacity.
        if risk_level in ("high", "critical"):
            docker_sem = get_docker_semaphore()
            docker_sem.acquire()

        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.commit()

        # Freeze context snapshot before any execution — immutable from this point.
        try:
            _save_context_snapshot(db, run, context)
        except Exception as exc:
            log.warning("Failed to save context snapshot for run %s: %s", run_id, exc)

        try:
            adapter, sandbox_level, sandbox_path, executor_type = _resolve_adapter(
                adapter_type, run_id, workspace_path, risk_level
            )
            run.sandbox_level = sandbox_level
            run.sandbox_path = sandbox_path
            run.executor_type = executor_type
            db.commit()
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)
            db.commit()
            return

        if not adapter.is_available():
            run.status = "failed"
            run.error = f"Adapter '{adapter_type}' is not available on this system."
            run.completed_at = datetime.now(UTC)
            db.commit()
            return

        # Credential grant — gives the adapter access to its CLI login state
        from ..credentials.broker import CredentialBroker
        broker = CredentialBroker()
        spec = adapter.get_credential_spec()
        grant = None
        if spec:
            executor_mode = "docker" if sandbox_level in ("one_shot_docker",) else "worktree"
            grant = broker.grant_for_run(
                run_id=run_id,
                runtime=spec.runtime,
                risk_level=risk_level,
                executor_mode=executor_mode,
            )
            if grant:
                adapter.credential_grant = grant
                broker.record_usage(db, run_id, run.space_id, grant)
            else:
                broker.record_usage(db, run_id, run.space_id, None,
                                    action="credential.skipped",
                                    reason="no profile configured — using container default")

        result = None
        try:
            result = adapter.run(
                prompt=prompt,
                context=context,
                workspace_path=workspace_path,
                timeout=timeout,
            )
            run.status = "completed" if result.success else "failed"
            run.output = result.output
            run.error = result.error
            run.exit_code = result.exit_code
            run.started_at = result.started_at or run.started_at
            run.completed_at = result.completed_at or datetime.now(UTC)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)
        finally:
            # Clean up per-run temp HOME regardless of outcome
            if grant and grant.temp_home:
                broker.cleanup_temp_home(run_id)

        if run.started_at and run.completed_at:
            run.runtime_seconds = (run.completed_at - run.started_at).total_seconds()

        db.commit()
        _fire_post_run_hooks(run, result)
    finally:
        if docker_sem is not None:
            docker_sem.release()
        db.close()


# ---------------------------------------------------------------------------
# AgentRunService
# ---------------------------------------------------------------------------

class AgentRunService:
    def __init__(self, db: Session):
        self.db = db

    def create_pending(
        self,
        prompt: str,
        context: dict,
        adapter_type: str = "echo",
        space_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        instructed_by_user_id: str | None = None,
        instructed_by_agent_id: str | None = None,
        parent_run_id: str | None = None,
        delegation_depth: int = 0,
        task_id: str | None = None,
        capability_id: str | None = None,
        workspace_id: str | None = None,
        permission_snapshot_json: dict | None = None,
        timeout: int = 300,
    ) -> AgentRun:
        """
        Create an AgentRun record with status='pending'. Does NOT execute the adapter.
        The caller must schedule execute_pending_run() as a background task.
        """
        space_id = space_id or settings.default_space_id
        user_id = user_id or settings.default_user_id

        run = AgentRun(
            id=_new_id(),
            task_id=task_id,
            space_id=space_id,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=agent_id,
            instructed_by_user_id=instructed_by_user_id,
            instructed_by_agent_id=instructed_by_agent_id,
            parent_run_id=parent_run_id,
            delegation_depth=delegation_depth,
            adapter_type=adapter_type,
            capability_id=capability_id,
            prompt=prompt,
            context_snapshot=context,
            permission_snapshot_json=permission_snapshot_json,
            status="pending",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def run(
        self,
        prompt: str,
        context: dict,
        adapter_type: str = "echo",
        space_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        instructed_by_user_id: str | None = None,
        instructed_by_agent_id: str | None = None,
        parent_run_id: str | None = None,
        delegation_depth: int = 0,
        task_id: str | None = None,
        capability_id: str | None = None,
        workspace_id: str | None = None,
        permission_snapshot_json: dict | None = None,
        workspace_path: str | None = None,
        risk_level: str = "medium",
        timeout: int = 300,
    ) -> AgentRun:
        """
        Synchronous execution: create record + run adapter in one call.
        Used by tests and agent-to-agent delegation (already in background context).
        """
        run = self.create_pending(
            prompt=prompt,
            context=context,
            adapter_type=adapter_type,
            space_id=space_id,
            user_id=user_id,
            agent_id=agent_id,
            instructed_by_user_id=instructed_by_user_id,
            instructed_by_agent_id=instructed_by_agent_id,
            parent_run_id=parent_run_id,
            delegation_depth=delegation_depth,
            task_id=task_id,
            capability_id=capability_id,
            workspace_id=workspace_id,
            permission_snapshot_json=permission_snapshot_json,
            timeout=timeout,
        )

        # Agent record can escalate risk level
        if agent_id:
            from ..models import Agent as AgentModel
            agent_obj = self.db.query(AgentModel).filter(AgentModel.id == agent_id).first()
            if agent_obj:
                policy_risk = (agent_obj.runtime_policy_json or {}).get("risk_level")
                if policy_risk:
                    risk_level = policy_risk

        run.status = "running"
        run.started_at = datetime.now(UTC)
        self.db.commit()

        # Freeze context snapshot before any execution.
        try:
            _save_context_snapshot(self.db, run, context)
        except Exception as exc:
            log.warning("Failed to save context snapshot for run %s: %s", run.id, exc)

        try:
            adapter, sandbox_level, sandbox_path, executor_type = _resolve_adapter(
                adapter_type, run.id, workspace_path, risk_level
            )
            run.sandbox_level = sandbox_level
            run.sandbox_path = sandbox_path
            run.executor_type = executor_type
            self.db.commit()
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(run)
            return run

        if not adapter.is_available():
            run.status = "failed"
            run.error = f"Adapter '{adapter_type}' is not available on this system."
            run.completed_at = datetime.now(UTC)
            self.db.commit()
            self.db.refresh(run)
            return run

        result = None
        try:
            result = adapter.run(
                prompt=prompt,
                context=context,
                workspace_path=workspace_path,
                timeout=timeout,
            )
            run.status = "completed" if result.success else "failed"
            run.output = result.output
            run.error = result.error
            run.exit_code = result.exit_code
            run.started_at = result.started_at or run.started_at
            run.completed_at = result.completed_at or datetime.now(UTC)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)

        if run.started_at and run.completed_at:
            run.runtime_seconds = (run.completed_at - run.started_at).total_seconds()

        self.db.commit()
        self.db.refresh(run)
        _fire_post_run_hooks(run, result)
        return run

    def list_runs(
        self,
        space_id: str,
        user_id: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        q = self.db.query(AgentRun).filter(
            AgentRun.space_id == space_id,
            AgentRun.user_id == user_id,
        )
        if task_id:
            q = q.filter(AgentRun.task_id == task_id)
        if agent_id:
            q = q.filter(AgentRun.agent_id == agent_id)
        return q.order_by(AgentRun.created_at.desc()).limit(limit).all()

    def get_run(self, run_id: str) -> AgentRun | None:
        return self.db.query(AgentRun).filter(AgentRun.id == run_id).first()

    def get_delegation_chain(self, run_id: str) -> list[AgentRun]:
        """Walk parent_run_id links to return the full delegation ancestry, root first."""
        chain: list[AgentRun] = []
        current = self.get_run(run_id)
        while current:
            chain.append(current)
            if current.parent_run_id:
                current = self.get_run(current.parent_run_id)
            else:
                break
        chain.reverse()
        return chain
