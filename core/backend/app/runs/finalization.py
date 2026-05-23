"""PostRunFinalizationService — canonical post-run write boundary.

Lifecycle:
  queued → running → terminal → finalized

"finalized" means agent-space has performed deterministic post-run evaluation
and, when applicable, task-level evaluation bridging.

Design rules:
- Idempotent per (run_id, finalizer_version): repeated calls return the existing
  completed or failed RunFinalization without creating duplicate RunEvaluation,
  TaskEvaluation, or run_finalized RunEvent rows.
- Does NOT mutate Run terminal status, Artifact, Proposal, MemoryEntry, Policy,
  WorkspaceProfile, ValidationRecipe, Capability, or RunReflection.
- Does NOT create learning proposals.
- Does NOT auto-apply anything.
- RunEvaluationService remains the deterministic evaluator (internal primitive).
- TaskEvaluationService remains the task bridge (invoked when TaskRun linkage exists).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
from ulid import ULID

from ..models import Run, RunFinalization
from .evaluation import RunEvaluationService
from .events import safe_append_run_event
from ..tasks.evaluation_service import TaskEvaluationService
from ..tasks.evaluation_errors import TaskEvaluationNotFoundError

log = logging.getLogger(__name__)

_FINALIZER_VERSION = "post_run_finalization.v1"

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "degraded", "cancelled"})


def _new_id() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(UTC)


class NonTerminalRunError(ValueError):
    """Raised when finalization is attempted on a non-terminal Run."""


class RunNotFoundError(ValueError):
    """Raised when the Run cannot be found in the given space."""


class PostRunFinalizationService:
    """Orchestrates post-run evaluation and finalization for a terminal Run.

    Single public entry point: finalize(run_id, space_id=...) → RunFinalization.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def finalize(self, run_id: str, *, space_id: str) -> RunFinalization:
        """Finalize a terminal Run.

        Creates exactly one RunEvaluation, optionally one TaskEvaluation bridge row
        when TaskRun linkage exists, one RunFinalization record, and one run_finalized
        RunEvent. Idempotent: returns existing completed or failed finalization without
        side effects. Failed finalizations are final for this finalizer_version; retry
        requires a new finalizer_version.

        Raises RunNotFoundError for missing runs.
        Raises NonTerminalRunError for queued/running/waiting_for_review runs.
        """
        run = (
            self.db.query(Run)
            .filter(Run.id == run_id, Run.space_id == space_id)
            .first()
        )
        if run is None:
            raise RunNotFoundError(f"Run '{run_id}' not found in space '{space_id}'")

        if run.status not in TERMINAL_STATUSES:
            raise NonTerminalRunError(
                f"Run '{run_id}' is not terminal (status={run.status!r}); "
                "finalization requires a terminal status: succeeded, failed, degraded, or cancelled."
            )

        existing = self._get_existing(run_id, space_id)
        if existing is not None:
            return existing

        return self._do_finalize(run, space_id=space_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_existing(self, run_id: str, space_id: str) -> Optional[RunFinalization]:
        return (
            self.db.query(RunFinalization)
            .filter(
                RunFinalization.run_id == run_id,
                RunFinalization.space_id == space_id,
                RunFinalization.finalizer_version == _FINALIZER_VERSION,
            )
            .first()
        )

    def _do_finalize(self, run: Run, *, space_id: str) -> RunFinalization:
        skipped_reasons: list[str] = []
        error_json: Optional[dict] = None
        run_eval_id: Optional[str] = None
        task_eval_id: Optional[str] = None

        try:
            run_eval = RunEvaluationService(self.db).evaluate(run.id, space_id=space_id)
            self.db.flush()
            run_eval_id = run_eval.id
        except Exception as exc:
            log.error("finalization: RunEvaluation failed run=%s: %s", run.id, exc)
            return self._record_failed(
                run,
                space_id=space_id,
                error_json={"stage": "run_evaluation", "error": str(exc)},
            )

        try:
            task_eval = self._bridge_task_evaluation(run_eval_id, space_id=space_id)
            if task_eval is not None:
                task_eval_id = task_eval.id
            else:
                skipped_reasons.append("no_task_run_link")
        except TaskEvaluationNotFoundError as exc:
            skipped_reasons.append("no_task_run_link")
            log.debug("finalization: task bridge skipped run=%s: %s", run.id, exc)
        except Exception as exc:
            log.error("finalization: TaskEvaluation bridge failed run=%s: %s", run.id, exc)
            return self._record_failed(
                run,
                space_id=space_id,
                run_evaluation_id=run_eval_id,
                error_json={"stage": "task_evaluation_bridge", "error": str(exc)},
            )

        finalization = self._record_completed(
            run,
            space_id=space_id,
            run_evaluation_id=run_eval_id,
            task_evaluation_id=task_eval_id,
            run_eval=run_eval,
            skipped_reasons=skipped_reasons,
        )
        self.db.flush()

        safe_append_run_event(
            self.db,
            run_id=run.id,
            space_id=space_id,
            event_type="run_finalized",
            status="succeeded",
            log_context="PostRunFinalizationService",
            metadata_json={
                "run_finalization_id": finalization.id,
                "run_evaluation_id": run_eval_id,
                "task_evaluation_id": task_eval_id,
                "skipped_reasons": skipped_reasons,
                "finalizer_version": _FINALIZER_VERSION,
            },
        )

        return finalization

    def _bridge_task_evaluation(self, run_evaluation_id: str, *, space_id: str):
        """Bridge RunEvaluation → TaskEvaluation. Returns row or None (no link)."""
        existing_evals = TaskEvaluationService(self.db).list_for_run_evaluation(
            run_evaluation_id, space_id
        )
        if existing_evals:
            return existing_evals[0]
        return TaskEvaluationService(self.db).create_from_run_evaluation(
            run_evaluation_id, space_id=space_id
        )

    def _record_completed(
        self,
        run: Run,
        *,
        space_id: str,
        run_evaluation_id: Optional[str],
        task_evaluation_id: Optional[str],
        run_eval: Any,
        skipped_reasons: list[str],
    ) -> RunFinalization:
        now = _now()
        row = RunFinalization(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            finalizer_version=_FINALIZER_VERSION,
            status="completed",
            run_evaluation_id=run_evaluation_id,
            task_evaluation_id=task_evaluation_id,
            outcome_status=run_eval.outcome_status,
            failure_layer=run_eval.failure_layer,
            failure_reason_code=run_eval.failure_reason_code,
            trajectory_status=run_eval.trajectory_status,
            skipped_reasons_json=skipped_reasons if skipped_reasons else None,
            finalized_at=now,
            created_at=now,
        )
        self.db.add(row)
        return row

    def _record_failed(
        self,
        run: Run,
        *,
        space_id: str,
        error_json: dict,
        run_evaluation_id: Optional[str] = None,
    ) -> RunFinalization:
        now = _now()
        row = RunFinalization(
            id=_new_id(),
            space_id=space_id,
            run_id=run.id,
            finalizer_version=_FINALIZER_VERSION,
            status="failed",
            run_evaluation_id=run_evaluation_id,
            error_json=error_json,
            finalized_at=now,
            created_at=now,
        )
        self.db.add(row)
        self.db.flush()

        safe_append_run_event(
            self.db,
            run_id=run.id,
            space_id=space_id,
            event_type="run_finalized",
            status="failed",
            log_context="PostRunFinalizationService",
            metadata_json={
                "run_finalization_id": row.id,
                "run_evaluation_id": run_evaluation_id,
                "task_evaluation_id": None,
                "skipped_reasons": [],
                "finalizer_version": _FINALIZER_VERSION,
                "error": error_json,
            },
        )

        return row

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_latest(self, run_id: str, *, space_id: str) -> Optional[RunFinalization]:
        """Return the most recent finalization for a run, or None."""
        return (
            self.db.query(RunFinalization)
            .filter(RunFinalization.run_id == run_id, RunFinalization.space_id == space_id)
            .order_by(RunFinalization.finalized_at.desc(), RunFinalization.id.desc())
            .first()
        )

    def list_for_run(self, run_id: str, *, space_id: str) -> list[RunFinalization]:
        """Return all finalizations for a run, newest first."""
        return (
            self.db.query(RunFinalization)
            .filter(RunFinalization.run_id == run_id, RunFinalization.space_id == space_id)
            .order_by(RunFinalization.finalized_at.desc(), RunFinalization.id.desc())
            .all()
        )
