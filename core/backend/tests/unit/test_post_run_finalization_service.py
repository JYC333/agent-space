"""Unit tests for PostRunFinalizationService."""
from __future__ import annotations

import pytest
from ulid import ULID

from app.models import (
    MemoryEntry,
    Policy,
    RunEvaluation,
    RunEvent,
    RunFinalization,
    Task,
    TaskEvaluation,
    TaskRun,
)
from app.runs.finalization import (
    NonTerminalRunError,
    PostRunFinalizationService,
    RunNotFoundError,
    _FINALIZER_VERSION,
)
from tests.support import factories


def _id() -> str:
    return str(ULID())


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


class TestFinalizeSucceededRun:
    def test_creates_run_evaluation(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        count = db.query(RunEvaluation).filter(RunEvaluation.run_id == run.id).count()
        assert count == 1

    def test_creates_run_finalization(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.run_id == run.id
        assert fin.finalizer_version == _FINALIZER_VERSION
        assert fin.run_evaluation_id is not None

    def test_creates_run_finalized_event(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        events = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event_type == "run_finalized")
            .all()
        )
        assert len(events) == 1
        assert events[0].status == "succeeded"

    def test_run_status_not_mutated(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.refresh(run)

        assert run.status == "succeeded"


class TestFinalizeFailedRun:
    def test_failed_run_preserves_failure_classification(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="failed")
        # adapter_runtime_error is in _EXACT_ERROR_CODE_MAP → (runtime, adapter_runtime_error)
        run.error_json = {"error_code": "adapter_runtime_error"}
        db.flush()

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.outcome_status == "failed"
        assert fin.failure_layer == "runtime"
        assert fin.failure_reason_code == "adapter_runtime_error"
        assert fin.run_evaluation_id is not None

    def test_run_status_unchanged_after_failed_finalization(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="failed")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.refresh(run)

        assert run.status == "failed"


class TestNonTerminalRejection:
    @pytest.mark.parametrize("status", ["queued", "running", "waiting_for_review"])
    def test_rejects_non_terminal_status(self, db, status):
        space, user = _setup(db)
        run = factories.create_test_run(db, space_id=space, user_id=user)
        run.status = status
        db.flush()

        with pytest.raises(NonTerminalRunError):
            PostRunFinalizationService(db).finalize(run.id, space_id=space)

    def test_rejects_missing_run(self, db):
        space, user = _setup(db)

        with pytest.raises(RunNotFoundError):
            PostRunFinalizationService(db).finalize("nonexistent-run-id", space_id=space)


class TestIdempotency:
    def test_repeated_finalize_returns_same_record(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        first = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        second = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert first.id == second.id

    def test_no_duplicate_run_evaluation_on_repeat(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        count = db.query(RunEvaluation).filter(RunEvaluation.run_id == run.id).count()
        assert count == 1

    def test_no_duplicate_run_finalized_event_on_repeat(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        events = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event_type == "run_finalized")
            .all()
        )
        assert len(events) == 1

    def test_no_duplicate_task_evaluation_on_repeat(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        _task_link(db, space_id=space, user_id=user, run=run)

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        run_eval = db.query(RunEvaluation).filter(RunEvaluation.run_id == run.id).first()
        count = (
            db.query(TaskEvaluation)
            .filter(TaskEvaluation.run_evaluation_id == run_eval.id)
            .count()
        )
        assert count == 1


class TestFailedFinalizationIdempotency:
    """A finalization whose status='failed' is a final append-only record for that
    finalizer_version. Repeated calls must return the existing failed row without
    creating duplicate RunEvaluation, TaskEvaluation, or run_finalized RunEvent rows.
    """

    def _monkeypatch_eval_failure(self, monkeypatch) -> None:
        def _fail(*args, **kwargs):
            raise RuntimeError("forced evaluation failure for idempotency test")

        monkeypatch.setattr(
            "app.runs.finalization.RunEvaluationService.evaluate",
            _fail,
        )

    def test_failed_finalization_returns_same_record(self, db, monkeypatch):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        self._monkeypatch_eval_failure(monkeypatch)

        first = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        second = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert first.status == "failed"
        assert first.id == second.id

    def test_failed_finalization_no_duplicate_run_evaluation(self, db, monkeypatch):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        self._monkeypatch_eval_failure(monkeypatch)

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        count = db.query(RunEvaluation).filter(RunEvaluation.run_id == run.id).count()
        assert count == 0

    def test_failed_finalization_no_duplicate_task_evaluation(self, db, monkeypatch):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        _task_link(db, space_id=space, user_id=user, run=run)
        self._monkeypatch_eval_failure(monkeypatch)

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        count = db.query(TaskEvaluation).filter(TaskEvaluation.run_id == run.id).count()
        assert count == 0

    def test_failed_finalization_no_duplicate_run_finalized_event(self, db, monkeypatch):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        self._monkeypatch_eval_failure(monkeypatch)

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()
        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        events = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event_type == "run_finalized")
            .all()
        )
        assert len(events) == 1
        assert events[0].status == "failed"


class TestNoTaskRunLink:
    def test_finalizes_without_task_run_and_records_skipped_reason(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")

        fin = PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert fin.status == "completed"
        assert fin.task_evaluation_id is None
        assert fin.skipped_reasons_json is not None
        assert "no_task_run_link" in fin.skipped_reasons_json


class TestNoSideEffects:
    def test_finalization_never_writes_memory_or_policy(self, db):
        space, user = _setup(db)
        run = _terminal_run(db, space_id=space, user_id=user, status="succeeded")
        mem_before = db.query(MemoryEntry).filter(MemoryEntry.space_id == space).count()
        pol_before = db.query(Policy).filter(Policy.space_id == space).count()

        PostRunFinalizationService(db).finalize(run.id, space_id=space)
        db.flush()

        assert db.query(MemoryEntry).filter(MemoryEntry.space_id == space).count() == mem_before
        assert db.query(Policy).filter(Policy.space_id == space).count() == pol_before
