"""Workflow tests for PostRunFinalizationService."""
from __future__ import annotations
import uuid

import pytest

from app.models import (
    RunEvaluation,
    RunFinalization,
    Task,
    TaskEvaluation,
    TaskRun,
)
from app.runs.finalization import PostRunFinalizationService, _FINALIZER_VERSION
from tests.support import factories


def _id() -> str:
    return str(uuid.uuid4())


def _setup(db, *, space_id: str | None = None, user_id: str | None = None) -> tuple[str, str]:
    space = space_id or _id()
    user = user_id or _id()
    factories.create_test_space(db, space_id=space)
    factories.create_test_user(db, space_id=space, user_id=user)
    return space, user


def _terminal_run(db, *, space_id: str, user_id: str, status: str = "succeeded"):
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    run.status = status
    db.flush()
    return run


def _task_link(db, *, space_id: str, user_id: str, run):
    task = Task(
        id=_id(),
        space_id=space_id,
        title="test task",
        task_type="general",
        status="inbox",
        priority="normal",
        risk_level="low",
        created_by_user_id=user_id,
    )
    db.add(task)
    db.flush()
    link = TaskRun(id=_id(), space_id=space_id, task_id=task.id, run_id=run.id, role="primary")
    db.add(link)
    db.flush()
    return task, link


class TestTaskLinkedRunFinalization:
    def test_task_linked_run_gets_bridge_task_evaluation(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        task, _ = _task_link(db, space_id=space, user_id=user, run=run)

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.task_evaluation_id is not None

        task_eval = db.query(TaskEvaluation).filter(
            TaskEvaluation.id == fin.task_evaluation_id
        ).first()
        assert task_eval is not None
        assert task_eval.task_id == task.id
        assert task_eval.run_id == run.id

    def test_task_evaluation_run_evaluation_id_points_to_run_evaluation(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        _task_link(db, space_id=space, user_id=user, run=run)

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        run_eval = db.query(RunEvaluation).filter(RunEvaluation.id == fin.run_evaluation_id).first()
        task_eval = db.query(TaskEvaluation).filter(TaskEvaluation.id == fin.task_evaluation_id).first()

        assert task_eval.run_evaluation_id == run_eval.id


class TestFailedRunFinalization:
    def test_finalization_mirrors_run_evaluation_outcome(self, db):
        """Failure classification in RunEvaluation is reflected in RunFinalization."""
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="failed")
        # Use an error code in the exact map so classification is deterministic
        run.error_json = {"error_code": "sandbox_required"}
        db.flush()

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.outcome_status == "failed"
        assert fin.failure_layer == "sandbox"
        assert fin.failure_reason_code == "sandbox_required"

        run_eval = db.query(RunEvaluation).filter(RunEvaluation.id == fin.run_evaluation_id).first()
        assert run_eval is not None
        assert run_eval.outcome_status == fin.outcome_status
        assert run_eval.failure_layer == fin.failure_layer
        assert run_eval.failure_reason_code == fin.failure_reason_code
        assert run_eval.trajectory_status == fin.trajectory_status

    def test_degraded_run_mirrors_partial_outcome(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="degraded")

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.outcome_status == "partial"


class TestFinalizeAllTerminalStatuses:
    @pytest.mark.parametrize("status", ["succeeded", "failed", "degraded", "cancelled"])
    def test_all_terminal_statuses_can_be_finalized(self, db, status):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status=status)

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        stored = db.query(RunFinalization).filter(RunFinalization.id == fin.id).first()
        assert stored is not None
        assert stored.status in ("completed", "failed")
