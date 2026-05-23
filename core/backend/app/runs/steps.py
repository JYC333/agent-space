"""RunStep service — coarse execution replay spine (M3).

Provides helpers to create, update, and query RunStep rows.  All writes
require a resolved actor_id.  Metadata and errors are sanitized before
storage.  Step writes are best-effort: callers should catch exceptions so
a failed step write does not hide the original run failure.

Actor attribution rule:
- User-initiated runs: get_or_create_user_actor for the instructing user.
- Job-triggered runs: get_or_create_job_actor(db, "agent_run", space_id).
- System/internal paths: get_or_create_system_actor.

Do not pass Settings.default_user_id as actor identity.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Actor, Run, RunStep
from ..schemas import RUN_STEP_STATUSES, RUN_STEP_TYPES
from .redaction import redact_error, redact_metadata

log = logging.getLogger(__name__)


class RunStepIndexConflictError(RuntimeError):
    """Raised when step_index allocation repeatedly conflicts with DB uniqueness."""


def _is_step_index_conflict(exc: IntegrityError) -> bool:
    message = str(exc.orig or exc)
    return (
        "uq_run_steps_run_step_index" in message
        or "run_steps.run_id, run_steps.step_index" in message
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    from ulid import ULID

    return str(ULID())


def _next_step_index(db: Session, run_id: str) -> int:
    """Return the next deterministic step_index for a run (0-based, monotonic)."""
    current_max = (
        db.query(func.max(RunStep.step_index))
        .filter(RunStep.run_id == run_id)
        .scalar()
    )
    return 0 if current_max is None else current_max + 1


def _validate_step_type(step_type: str) -> None:
    if step_type not in RUN_STEP_TYPES:
        raise ValueError(
            f"invalid step_type: {step_type!r}; must be one of {sorted(RUN_STEP_TYPES)}"
        )


def _validate_status(status: str) -> None:
    if status not in RUN_STEP_STATUSES:
        raise ValueError(
            f"invalid status: {status!r}; must be one of {sorted(RUN_STEP_STATUSES)}"
        )


def resolve_run_actor(db: Session, run: Run) -> Actor:
    """Resolve or create the appropriate Actor for a run's execution.

    Resolution order:
    1. instructed_by_user_id → user actor
    2. trigger_origin == "job" → job actor (service_name="agent_run")
    3. Otherwise → system actor

    Never uses Settings.default_user_id.
    """
    from ..actors.service import (
        get_or_create_job_actor,
        get_or_create_system_actor,
        get_or_create_user_actor,
    )
    from ..models import User

    if run.instructed_by_user_id:
        user = db.query(User).filter(User.id == run.instructed_by_user_id).first()
        if user:
            return get_or_create_user_actor(db, user, run.space_id)

    if run.trigger_origin == "job":
        return get_or_create_job_actor(db, "agent_run", space_id=run.space_id)

    return get_or_create_system_actor(db, space_id=run.space_id, service_name="run_execution")


def create_step(
    db: Session,
    *,
    run: Run,
    actor_id: str,
    step_type: str,
    status: str,
    title: Optional[str] = None,
    runtime_adapter_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    proposal_id: Optional[str] = None,
    parent_step_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    input_summary: Optional[str] = None,
    output_summary: Optional[str] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> RunStep:
    """Create and flush a new RunStep row.

    Validates step_type and status.  Sanitizes error_message and
    metadata_json before writing.  Does NOT commit — caller controls
    transaction.
    """
    _validate_step_type(step_type)
    _validate_status(status)

    last_exc: IntegrityError | None = None
    for _ in range(3):
        now = _now()
        step = RunStep(
            id=_new_id(),
            space_id=run.space_id,
            run_id=run.id,
            parent_step_id=parent_step_id,
            actor_id=actor_id,
            step_index=_next_step_index(db, run.id),
            step_type=step_type,
            status=status,
            title=title,
            runtime_adapter_id=runtime_adapter_id,
            workspace_id=workspace_id or run.workspace_id,
            session_id=session_id or run.session_id,
            task_id=task_id,
            artifact_id=artifact_id,
            proposal_id=proposal_id,
            started_at=started_at,
            ended_at=ended_at,
            input_summary=(input_summary or "")[:4000] or None,
            output_summary=(output_summary or "")[:4000] or None,
            error_type=error_type,
            error_message=redact_error(error_message),
            metadata_json=redact_metadata(metadata_json or {}),
            created_at=now,
            updated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(step)
                db.flush()
            return step
        except IntegrityError as exc:
            if not _is_step_index_conflict(exc):
                raise
            last_exc = exc
            log.warning(
                "RunStep step_index conflict while creating step; retrying run=%s step_type=%s",
                run.id,
                step_type,
            )

    raise RunStepIndexConflictError(
        f"could not allocate unique RunStep.step_index for run {run.id}"
    ) from last_exc


def start_step(
    db: Session,
    step: RunStep,
    *,
    started_at: Optional[datetime] = None,
) -> RunStep:
    """Transition a step to running status."""
    step.status = "running"
    step.started_at = started_at or _now()
    step.updated_at = _now()
    db.add(step)
    db.flush()
    return step


def complete_step(
    db: Session,
    step: RunStep,
    *,
    ended_at: Optional[datetime] = None,
    output_summary: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> RunStep:
    """Transition a step to succeeded status."""
    step.status = "succeeded"
    step.ended_at = ended_at or _now()
    step.updated_at = _now()
    if output_summary is not None:
        step.output_summary = output_summary[:4000] or None
    if metadata_json is not None:
        step.metadata_json = redact_metadata(metadata_json)
    db.add(step)
    db.flush()
    return step


def fail_step(
    db: Session,
    step: RunStep,
    *,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    ended_at: Optional[datetime] = None,
    metadata_json: Optional[dict] = None,
) -> RunStep:
    """Transition a step to failed status with sanitized error."""
    step.status = "failed"
    step.ended_at = ended_at or _now()
    step.updated_at = _now()
    if error_type is not None:
        step.error_type = error_type
    if error_message is not None:
        step.error_message = redact_error(error_message)
    if metadata_json is not None:
        step.metadata_json = redact_metadata(metadata_json)
    db.add(step)
    db.flush()
    return step


def record_artifact_step(
    db: Session,
    *,
    run: Run,
    actor_id: str,
    artifact_id: str,
    title: Optional[str] = None,
    output_summary: Optional[str] = None,
) -> RunStep:
    """Create a completed artifact_created step linked to an artifact."""
    now = _now()
    return create_step(
        db,
        run=run,
        actor_id=actor_id,
        step_type="artifact_created",
        status="succeeded",
        title=title or "Artifact created",
        artifact_id=artifact_id,
        started_at=now,
        ended_at=now,
        output_summary=output_summary,
    )


def record_proposal_step(
    db: Session,
    *,
    run: Run,
    actor_id: str,
    proposal_id: str,
    title: Optional[str] = None,
    output_summary: Optional[str] = None,
) -> RunStep:
    """Create a completed proposal_created step linked to a proposal."""
    now = _now()
    return create_step(
        db,
        run=run,
        actor_id=actor_id,
        step_type="proposal_created",
        status="succeeded",
        title=title or "Proposal created",
        proposal_id=proposal_id,
        started_at=now,
        ended_at=now,
        output_summary=output_summary,
    )


def list_run_steps(
    db: Session,
    run_id: str,
    space_id: str,
) -> list[RunStep]:
    """Return all RunStep rows for a run, ordered by step_index ascending."""
    return (
        db.query(RunStep)
        .filter(RunStep.run_id == run_id, RunStep.space_id == space_id)
        .order_by(RunStep.step_index.asc(), RunStep.created_at.asc(), RunStep.id.asc())
        .all()
    )
