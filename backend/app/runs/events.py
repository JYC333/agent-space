"""RunEvent service — structured append-only harness evidence spine.

RunEvent records each significant phase of a Run as a structured event:
context compilation, runtime selection, sandbox creation, adapter invocation
and completion, artifact ingestion, patch collection, validation, proposal
creation, and evaluation creation.

Design rules:
- Append-only: rows are never updated or deleted.
- event_index is MAX()+1 scoped to (space_id, run_id). Documented distributed-
  writer risk — same as RunStep.step_index.
- Writes are best-effort: use safe_append_run_event at instrumentation points
  so that a failed event write never poisons Run terminal-state commits,
  artifact persistence, proposal creation, or evaluation creation.
- Never stores raw credentials, stdout/stderr, full rendered context, full patch
  bodies, personal memory text, or complete file contents.
"""

from __future__ import annotations
import uuid

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import RunEvent
from .redaction import redact_error, redact_metadata

log = logging.getLogger(__name__)

RUN_EVENT_TYPES = frozenset({
    "context_compiled",
    "runtime_selected",
    "credential_granted",
    "sandbox_created",
    "policy_checked",
    "adapter_invoked",
    "adapter_completed",
    "artifact_ingested",
    "patch_collected",
    "validation_started",
    "validation_completed",
    "proposal_created",
    "evaluation_created",
    "run_finalized",
})

RUN_EVENT_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "warning",
    "cancelled",
})


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class RunEventService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def next_event_index(self, run_id: str, space_id: str) -> int:
        """Return the next event_index for this run (0-based, monotonic)."""
        current_max = (
            self.db.query(func.max(RunEvent.event_index))
            .filter(RunEvent.run_id == run_id, RunEvent.space_id == space_id)
            .scalar()
        )
        return 0 if current_max is None else current_max + 1

    def append_event(
        self,
        *,
        run_id: str,
        space_id: str,
        event_type: str,
        status: str,
        step_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        summary: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        workspace_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        data_exposure_level: Optional[str] = None,
        trust_level: Optional[str] = None,
        metadata_json: Optional[dict] = None,
    ) -> RunEvent:
        """Append a new RunEvent row. Raises ValueError for unknown event_type/status."""
        if event_type not in RUN_EVENT_TYPES:
            raise ValueError(
                f"invalid event_type: {event_type!r}; must be one of {sorted(RUN_EVENT_TYPES)}"
            )
        if status not in RUN_EVENT_STATUSES:
            raise ValueError(
                f"invalid status: {status!r}; must be one of {sorted(RUN_EVENT_STATUSES)}"
            )

        event_index = self.next_event_index(run_id, space_id)

        event = RunEvent(
            id=_new_id(),
            space_id=space_id,
            run_id=run_id,
            step_id=step_id,
            actor_id=actor_id,
            event_index=event_index,
            event_type=event_type,
            status=status,
            summary=summary,
            error_code=error_code,
            error_message=redact_error(error_message),
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            proposal_id=proposal_id,
            data_exposure_level=data_exposure_level,
            trust_level=trust_level,
            metadata_json=redact_metadata(metadata_json) if metadata_json else None,
            created_at=_now(),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_for_run(
        self,
        run_id: str,
        space_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[int, list[RunEvent]]:
        """Return (total, items) for events matching filters, ordered by event_index.

        Filters are applied at the DB level before count and pagination so that
        total always reflects the filtered set.
        """
        q = self.db.query(RunEvent).filter(
            RunEvent.run_id == run_id,
            RunEvent.space_id == space_id,
        )
        if event_type is not None:
            q = q.filter(RunEvent.event_type == event_type)
        if status is not None:
            q = q.filter(RunEvent.status == status)
        total = q.count()
        items = (
            q.order_by(RunEvent.event_index)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, items

    def get_latest_for_run(
        self,
        run_id: str,
        space_id: str,
    ) -> Optional[RunEvent]:
        """Return the most recently appended event for a run, or None."""
        return (
            self.db.query(RunEvent)
            .filter(RunEvent.run_id == run_id, RunEvent.space_id == space_id)
            .order_by(RunEvent.event_index.desc())
            .first()
        )

    def list_by_type(
        self,
        run_id: str,
        space_id: str,
        event_type: str,
    ) -> list[RunEvent]:
        """Return all events of a given type for a run, ordered by event_index."""
        return (
            self.db.query(RunEvent)
            .filter(
                RunEvent.run_id == run_id,
                RunEvent.space_id == space_id,
                RunEvent.event_type == event_type,
            )
            .order_by(RunEvent.event_index)
            .all()
        )


def safe_append_run_event(
    db: Session,
    *,
    run_id: str,
    space_id: str,
    event_type: str,
    status: str,
    log_context: str = "",
    step_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    summary: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    workspace_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    proposal_id: Optional[str] = None,
    data_exposure_level: Optional[str] = None,
    trust_level: Optional[str] = None,
    metadata_json: Optional[dict[str, Any]] = None,
) -> Optional[RunEvent]:
    """Best-effort RunEvent write inside a savepoint.

    Catches all exceptions and logs a warning so that a failed event write
    never poisons Run terminal-state commits, artifact persistence, proposal
    creation, or evaluation creation.
    """
    from ..db_uow import UnitOfWork

    ctx = f" [{log_context}]" if log_context else ""
    try:
        with UnitOfWork(db).savepoint():
            svc = RunEventService(db)
            return svc.append_event(
                run_id=run_id,
                space_id=space_id,
                event_type=event_type,
                status=status,
                step_id=step_id,
                actor_id=actor_id,
                summary=summary,
                error_code=error_code,
                error_message=error_message,
                workspace_id=workspace_id,
                artifact_id=artifact_id,
                proposal_id=proposal_id,
                data_exposure_level=data_exposure_level,
                trust_level=trust_level,
                metadata_json=metadata_json,
            )
    except IntegrityError as exc:
        log.warning("run_event write conflict%s run=%s type=%s: %s", ctx, run_id, event_type, exc)
    except Exception as exc:
        log.warning("run_event write failed%s run=%s type=%s: %s", ctx, run_id, event_type, exc)
    return None
