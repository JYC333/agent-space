from __future__ import annotations
"""
Handler registry for the job queue.

Register a handler:
    from app.jobs.handlers import register_handler

    @register_handler("my_job_type")
    def handle_my_job(job: Job) -> dict | None:
        ...
        return {"key": "value"}

Handlers are synchronous callables; the worker runs them in a thread-pool executor.
Return a dict (or None) that becomes job.result on success.
Raise any exception to signal failure (the worker calls fail_job and retries).
"""

import logging
from typing import Callable

log = logging.getLogger(__name__)

# job_type → sync handler callable
_REGISTRY: dict[str, Callable] = {}


def register_handler(job_type: str):
    """Decorator that registers a sync handler for a job type."""
    def decorator(fn: Callable) -> Callable:
        _REGISTRY[job_type] = fn
        return fn
    return decorator


def get_handler(job_type: str) -> Callable | None:
    return _REGISTRY.get(job_type)


def list_registered() -> list[str]:
    return list(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Built-in handler: agent_run
#
# Payload fields:
#   run_id            — pre-created AgentRun ID (status=pending)
#   adapter_type      — e.g. "echo", "claude_code"
#   prompt            — instruction text
#   context           — context snapshot dict
#   workspace_path    — optional local path
#   timeout           — seconds, default 300
#   risk_level        — "low" | "medium" | "high" | "critical", default "medium"
#   cli_adapter_config_id — optional CLIAdapterConfig ID
#   task_id           — optional Task ID; when set, task.status is updated after run
# ---------------------------------------------------------------------------

@register_handler("agent_run")
def handle_agent_run(job) -> dict | None:
    from ..agents.runner import execute_pending_run

    payload = job.payload or {}
    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("agent_run handler requires payload.run_id")

    execute_pending_run(
        run_id=run_id,
        adapter_type=payload.get("adapter_type", "echo"),
        prompt=payload.get("prompt", ""),
        context=payload.get("context", {}),
        workspace_path=payload.get("workspace_path"),
        timeout=payload.get("timeout", 300),
        risk_level=payload.get("risk_level", "medium"),
        cli_adapter_config_id=payload.get("cli_adapter_config_id"),
    )

    # Optionally update the parent Task's status
    task_id = payload.get("task_id")
    if task_id:
        _sync_task_status(task_id, run_id)

    return {"run_id": run_id}


def _sync_task_status(task_id: str, run_id: str) -> None:
    from datetime import datetime, UTC
    from ..db import SessionLocal
    from ..models import AgentRun, Task

    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        task = db.query(Task).filter(Task.id == task_id).first()
        if run and task:
            task.status = "completed" if run.status == "completed" else "failed"
            task.result = run.output
            task.error = run.error
            task.updated_at = datetime.now(UTC)
            db.commit()
    except Exception as exc:
        log.warning("Failed to sync task %s status: %s", task_id, exc)
        db.rollback()
    finally:
        db.close()
