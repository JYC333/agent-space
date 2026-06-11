from __future__ import annotations
"""
Built-in job handlers owned by the jobs module.

These are infrastructure handlers (``agent_run``, ``memory_consolidation``) that
this module owns. They are plain callables taking the ``Job`` ORM row and
returning a dict (or None) that becomes ``job.result_json`` on success; raising
signals failure (the worker calls ``fail_job`` and retries per ``max_attempts``).

Registration is explicit: ``register_job_handlers(registry)`` (called once per
startup via ``app.modules.registry.register_job_handlers``) binds these handlers
to a ``JobHandlerRegistry``. The registry itself (``app.jobs.registry``) owns the
dispatch mechanics and holds no business logic.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import JobHandlerRegistry

log = logging.getLogger(__name__)


# Built-in handler: agent_run (routes to RunExecutionService)
#
# This handler is **infrastructure only**. The Job row is queue plumbing,
# not a product Task. The handler routes intents to the shared
# ``RunExecutionService`` (adapters from policy / ``RuntimeAdapter``).
# Removed ``payload.runtime`` overrides are rejected **before** execution: the
# handler raises ``ValueError`` so the job fails with ``runtime_removed`` semantics
# and no Run row is mutated for that path.
#
#   1. payload.run_id  — execute an existing queued Run.
#   2. payload.task_id — load the product Task, create a queued Run via
#                        ``TaskService.create_queued_run_for_task`` (which
#                        also creates a canonical ``TaskRun`` link), then
#                        execute that Run.
#   3. payload.agent_id — create a fresh Run via ``RunService.create_run``,
#                         then execute it.
#
# After execution the handler writes ``{"run_id", "status"}`` (plus a small
# error snippet on failure) to ``job.result_json`` and lets the queue
# transition the Job. If execution raises, the handler re-raises so the
# queue marks the Job ``failed`` (with retry semantics governed by the
# Job's ``max_attempts``).
#
# Not reintroduced:
#   - POST /api/v1/tasks/{task_id}/run singular route
#   - job_type="product_task" as product task behaviour
#   - Task = Job modelling
#   - monolithic execute_pending_run helpers on the runner module
# ---------------------------------------------------------------------------


def _resolve_identity(job, payload: dict) -> tuple[str, str | None]:
    space_id = payload.get("space_id") or job.space_id
    user_id = payload.get("user_id") or job.user_id
    if not space_id:
        raise ValueError("job payload is missing space_id")
    if not user_id:
        raise ValueError("job payload is missing user_id")
    return space_id, user_id


def _reject_removed_job_runtime(payload: dict) -> None:
    from ..runs import is_obsolete_runtime_override_token

    rt = payload.get("runtime")
    if rt is None or rt == "":
        return
    if is_obsolete_runtime_override_token(rt):
        raise ValueError(
            "runtime_removed: removed runtime override in job payload; "
            "omit payload.runtime or use configured adapters."
        )


def _job_runtime(payload: dict) -> str | None:
    runtime = payload.get("runtime")
    if runtime == "":
        return None
    return runtime


def _execute_existing_run(job, payload: dict, run_id: str) -> dict:
    from fastapi import HTTPException

    from ..db import SessionLocal
    from ..models import Run
    from ..runs import RunExecutionService
    from ..jobs.worker import WORKER_ID

    space_id, _ = _resolve_identity(job, payload)
    job_id = getattr(job, "id", None)
    db = SessionLocal()
    try:
        # Guard: if the target Run was cancelled before this job worker picked it up,
        # exit cleanly without retrying.  RunExecutionService raises HTTPException 409
        # for any terminal-status run (including cancelled).  We catch that specific
        # case here so the job records the outcome and does not re-enqueue.
        # Full Job↔Run cancellation linkage is deferred; this guard ensures cancelled
        # runs do not produce spurious job failure entries.  See runtime docs for the
        # current-behaviour note on the queued-job / Run cancellation gap.
        try:
            result = RunExecutionService(db).execute_run(
                run_id,
                space_id=space_id,
                runtime=_job_runtime(payload),
                simulate_failure=bool(payload.get("simulate_failure")),
                worker_id=WORKER_ID,
                job_id=job_id,
            )
        except HTTPException as exc:
            if exc.status_code == 409 and "terminal status" in str(exc.detail):
                run = db.query(Run).filter(Run.id == run_id).first()
                run_status = run.status if run else "unknown"
                log.info(
                    "agent_run job %s: run %s already in terminal status '%s'; "
                    "exiting cleanly without retry",
                    getattr(job, "id", "?"), run_id, run_status,
                )
                return {
                    "run_id": run_id,
                    "status": run_status,
                    "skipped": True,
                    "skip_reason": "run_already_terminal",
                }
            raise

        # Duplicate-execution is non-retryable: another worker holds the lock.
        # Return a completed (not failed) result so the job is not re-enqueued.
        if result and result.error_code == "duplicate_execution":
            log.info(
                "agent_run job %s: run %s duplicate_execution — job completed, no retry",
                getattr(job, "id", "?"), run_id,
            )
            return {
                "run_id": run_id,
                "status": "queued",
                "skipped": True,
                "skip_reason": "duplicate_execution",
                "error_code": "duplicate_execution",
            }

        run = db.query(Run).filter(Run.id == run_id).first()
        out: dict = {"run_id": run_id, "status": run.status if run else "unknown"}
        if run and run.error_json and isinstance(run.error_json, dict):
            ec = run.error_json.get("error_code")
            if ec:
                out["error_code"] = ec
            et = run.error_json.get("error_text")
            if et:
                out["error_text"] = str(et)[:2000]
        if result and not result.success and result.error:
            out["error"] = result.error[:1000]
        if result and result.error_code:
            out["error_code"] = result.error_code
        return out
    finally:
        db.close()


def _create_and_execute_task_run(job, payload: dict, task_id: str) -> dict:
    from ..db import SessionLocal
    from ..runs import RunExecutionService
    from ..schemas import TaskRunCreateBody
    from ..tasks.service import TaskService
    from ..jobs.worker import WORKER_ID

    space_id, user_id = _resolve_identity(job, payload)
    job_id = getattr(job, "id", None)
    db = SessionLocal()
    try:
        body = TaskRunCreateBody(
            agent_id=payload.get("agent_id"),
            mode=payload.get("mode") or "live",
            run_type=payload.get("run_type") or "agent",
            trigger_origin=payload.get("trigger_origin") or "job",
            session_id=payload.get("session_id"),
            workspace_id=payload.get("workspace_id"),
            prompt=payload.get("prompt"),
            instruction=payload.get("instruction"),
            set_task_in_progress=bool(payload.get("set_task_in_progress", True)),
            parent_run_id=payload.get("parent_run_id"),
            adapter_type=payload.get("adapter_type"),
        )
        _link, run = TaskService(db).create_queued_run_for_task(
            task_id, space_id, user_id, body
        )
        run_id = run.id
        result = RunExecutionService(db).execute_run(
            run_id,
            space_id=space_id,
            runtime=_job_runtime(payload),
            simulate_failure=bool(payload.get("simulate_failure")),
            worker_id=WORKER_ID,
            job_id=job_id,
        )
        from ..models import Run

        run = db.query(Run).filter(Run.id == run_id).first()
        out: dict = {"run_id": run_id, "status": run.status if run else "unknown"}
        if run and run.error_json and isinstance(run.error_json, dict):
            ec = run.error_json.get("error_code")
            if ec:
                out["error_code"] = ec
            et = run.error_json.get("error_text")
            if et:
                out["error_text"] = str(et)[:2000]
        if result and not result.success and result.error:
            out["error"] = result.error[:1000]
        if result and result.error_code:
            out["error_code"] = result.error_code
        return out
    finally:
        db.close()


def _create_and_execute_agent_run(job, payload: dict, agent_id: str) -> dict:
    from ..db import SessionLocal
    from ..runs import RunExecutionService
    from ..runs import RunService
    from ..schemas import RunCreate
    from ..jobs.worker import WORKER_ID

    space_id, user_id = _resolve_identity(job, payload)
    job_id = getattr(job, "id", None)
    db = SessionLocal()
    try:
        run = RunService(db).create_run(
            agent_id=agent_id,
            data=RunCreate(
                mode=payload.get("mode") or "live",
                run_type=payload.get("run_type") or "agent",
                trigger_origin=payload.get("trigger_origin") or "job",
                session_id=payload.get("session_id"),
                workspace_id=payload.get("workspace_id"),
                prompt=payload.get("prompt"),
                instruction=payload.get("instruction"),
                parent_run_id=payload.get("parent_run_id"),
                adapter_type=payload.get("adapter_type"),
                runtime_adapter_id=payload.get("runtime_adapter_id"),
            ),
            space_id=space_id,
            user_id=user_id,
        )
        run_id = run.id
        result = RunExecutionService(db).execute_run(
            run_id,
            space_id=space_id,
            runtime=_job_runtime(payload),
            simulate_failure=bool(payload.get("simulate_failure")),
            worker_id=WORKER_ID,
            job_id=job_id,
        )
        from ..models import Run

        run = db.query(Run).filter(Run.id == run_id).first()
        out: dict = {"run_id": run_id, "status": run.status if run else "unknown"}
        if run and run.error_json and isinstance(run.error_json, dict):
            ec = run.error_json.get("error_code")
            if ec:
                out["error_code"] = ec
            et = run.error_json.get("error_text")
            if et:
                out["error_text"] = str(et)[:2000]
        if result and not result.success and result.error:
            out["error"] = result.error[:1000]
        if result and result.error_code:
            out["error_code"] = result.error_code
        return out
    finally:
        db.close()


def handle_agent_run(job) -> dict | None:
    """Drive a Run to completion through ``RunExecutionService``.

    Behaviour summary (see module docstring for full notes):

    - payload.run_id → execute that queued Run.
    - payload.task_id → create+link a Run for the product Task, then execute.
    - payload.agent_id → create a Run, then execute.

    Returns ``{"run_id", "status"}`` (plus optional ``error``) in
    ``job.result_json``. Re-raises on internal errors so the queue marks
    the Job as failed (with retry per ``max_attempts``).
    """
    payload = job.payload_json or {}
    _reject_removed_job_runtime(payload)
    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    agent_id = payload.get("agent_id")

    if run_id:
        return _execute_existing_run(job, payload, run_id)
    if task_id:
        return _create_and_execute_task_run(job, payload, task_id)
    if agent_id:
        return _create_and_execute_agent_run(job, payload, agent_id)

    raise ValueError(
        "agent_run handler requires payload.run_id, payload.task_id, or payload.agent_id"
    )


def handle_memory_consolidation(job) -> dict | None:
    """Process pending ``ActivityRecord`` rows into reviewable proposals."""
    from ..db import SessionLocal
    from ..memory import run_memory_consolidation_job_payload

    payload = job.payload_json or {}
    db = SessionLocal()
    try:
        return run_memory_consolidation_job_payload(db=db, payload=payload)
    finally:
        db.close()


def register_job_handlers(registry: "JobHandlerRegistry") -> None:
    """Register this module's job handlers. Called once per startup.

    Adding a new jobs-module handler means registering it here — the central
    worker dispatch loop never needs to change.
    """
    registry.register("agent_run", handle_agent_run)
    registry.register("memory_consolidation", handle_memory_consolidation)
