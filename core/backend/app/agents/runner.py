from __future__ import annotations
"""
Runner — adapter registry and post-run hook infrastructure.

This module no longer owns Run lifecycle or execution.
Run lifecycle is owned by RunService (app.runs.run_service).
Execution is owned by RunExecutionService and registered runtime adapters.

This module provides:
  - Adapter registry (_ADAPTER_REGISTRY)
  - Post-run hook registry (register_post_run_hook, PostRunHook type)
  - Adapter resolution helpers (sandbox level, etc.) for execution services
"""

import logging
from datetime import datetime, UTC

log = logging.getLogger(__name__)

from ..models import Run
from .base import AgentAdapter, RuntimeExecutionResult
from .cli_adapter import EchoAgentAdapter
from .claude_adapter import ClaudeCLIAdapter
from .codex_adapter import CodexCLIAdapter
from .api_adapter import AnthropicAPIAdapter


_ADAPTER_REGISTRY: dict[str, type[AgentAdapter]] = {
    "echo": EchoAgentAdapter,
    "anthropic_api": AnthropicAPIAdapter,
    "claude_code": ClaudeCLIAdapter,
    "claude_cli": ClaudeCLIAdapter,
    "codex_cli": CodexCLIAdapter,
}

# Adapters that require an isolated sandbox (worktree or Docker).
# These run LLM-generated code and must never execute on the host directly.
_SANDBOXED_ADAPTERS: frozenset[str] = frozenset({"claude_code", "claude_cli", "codex_cli"})


# ---------------------------------------------------------------------------
# Post-run hook registry
#
# Hooks are callables registered at import time (or by plugins/tests).
# Each hook receives the completed Run and the result from the adapter.
# Hooks are fire-and-forget: exceptions are logged, never re-raised.
#
# Register a hook:
#   from app.agents.runner import register_post_run_hook
#   @register_post_run_hook
#   def my_hook(run: Run, result: RuntimeExecutionResult | None) -> None:
#       ...
# ---------------------------------------------------------------------------

from typing import Callable
PostRunHook = Callable[[Run, RuntimeExecutionResult | None], None]

_POST_RUN_HOOKS: list[PostRunHook] = []


def register_post_run_hook(fn: PostRunHook) -> PostRunHook:
    """Decorator / function to register a post-run hook."""
    _POST_RUN_HOOKS.append(fn)
    return fn


def _fire_post_run_hooks(run: Run, result: RuntimeExecutionResult | None) -> None:
    for hook in _POST_RUN_HOOKS:
        try:
            hook(run, result)
        except Exception as exc:
            log.warning("post-run hook %s raised: %s", hook.__name__, exc)


# ---------------------------------------------------------------------------
# Adapter resolution helpers (used by RunExecutionService)
# ---------------------------------------------------------------------------

def resolve_adapter(
    adapter_type: str,
    run_id: str,
    workspace_path: str | None,
    risk_level: str = "medium",
) -> tuple[AgentAdapter, str, str | None, str]:
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
    ctx = mgr.create_worktree(run_id, workspace_path)
    if adapter_type in ("claude_code", "claude_cli"):
        adapter = ClaudeCLIAdapter(executor=LocalExecutor(), sandbox_dir=str(ctx.sandbox_dir))
    else:
        adapter = CodexCLIAdapter(executor=LocalExecutor(), sandbox_dir=str(ctx.sandbox_dir))
    return adapter, ctx.level.value, str(ctx.sandbox_dir), "local"