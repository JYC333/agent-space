"""Workflow tests for the RunEvaluation -> TaskEvaluation bridge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

from app.models import (
    Artifact,
    MemoryEntry,
    Policy,
    Proposal,
    Run,
    RunEvaluation,
    RunReflection,
    Task,
    TaskArtifact,
    TaskEvaluation,
    TaskRun,
)
from app.runs.evaluation import RunEvaluationService
from app.tasks.evaluation_errors import TaskEvaluationInvalidRequestError, TaskEvaluationNotFoundError
from app.tasks.evaluation_service import TaskEvaluationService
from app.schemas import TaskEvaluationCreate
from tests.support import factories


def _id() -> str:
    return str(ULID())


def _setup(db, *, space_id: str | None = None, user_id: str | None = None) -> tuple[str, str]:
    space = space_id or _id()
    user = user_id or _id()
    factories.create_test_space(db, space_id=space)
    factories.create_test_user(db, space_id=space, user_id=user)
    return space, user


def _task(db, *, space_id: str, user_id: str, status: str = "inbox") -> Task:
    row = Task(
        id=_id(),
        space_id=space_id,
        title=f"task-{_id()}",
        task_type="general",
        status=status,
        priority="normal",
        risk_level="low",
        created_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


def _run(db, *, space_id: str, user_id: str, status: str = "succeeded") -> Run:
    row = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    row.status = status
    db.flush()
    return row


def _link(db, *, task: Task, run: Run, role: str = "primary") -> TaskRun:
    row = TaskRun(
        id=_id(),
        space_id=task.space_id,
        task_id=task.id,
        run_id=run.id,
        role=role,
    )
    db.add(row)
    db.flush()
    return row


def _run_evaluation(
    db,
    *,
    run: Run,
    outcome_status: str = "passed",
    trajectory_status: str = "acceptable",
    failure_layer: str | None = None,
    failure_reason_code: str | None = None,
    evidence_json: dict | None = None,
    evaluated_at: datetime | None = None,
) -> RunEvaluation:
    row = RunEvaluation(
        id=_id(),
        space_id=run.space_id,
        run_id=run.id,
        evaluator_type="deterministic_harness",
        evaluator_version="harness_eval.v1",
        outcome_status=outcome_status,
        failure_layer=failure_layer,
        failure_reason_code=failure_reason_code,
        trajectory_status=trajectory_status,
        evidence_json=evidence_json or {},
        rule_trace_json=[],
        evaluated_at=evaluated_at or datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def _bridge(db, run_eval: RunEvaluation, *, space_id: str) -> TaskEvaluation:
    return TaskEvaluationService(db).create_from_run_evaluation(run_eval.id, space_id=space_id)


class TestTaskEvaluationBridgeService:
    def test_basic_creation(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        run_eval = _run_evaluation(db, run=run)

        task_eval = _bridge(db, run_eval, space_id=space)

        assert task_eval.task_id == task.id
        assert task_eval.run_id == run.id
        assert task_eval.run_evaluation_id == run_eval.id
        assert task_eval.evaluator_type == "run_evaluation_bridge"

    @pytest.mark.parametrize(
        ("outcome", "score", "recommendation", "confidence"),
        [
            ("passed", 1.0, "accept", 1.0),
            ("partial", 0.5, "review", 0.7),
            ("failed", 0.0, "retry", 1.0),
            ("unknown", None, "needs_evidence", 0.3),
        ],
    )
    def test_outcome_mapping(self, db, outcome, score, recommendation, confidence):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        run_eval = _run_evaluation(
            db,
            run=run,
            outcome_status=outcome,
            trajectory_status="incomplete" if outcome == "partial" else "acceptable",
        )

        task_eval = _bridge(db, run_eval, space_id=space)

        assert task_eval.score == score
        assert task_eval.recommendation == recommendation
        assert task_eval.confidence == confidence

    def test_append_only(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        run_eval = _run_evaluation(db, run=run)

        first = _bridge(db, run_eval, space_id=space)
        second = _bridge(db, run_eval, space_id=space)

        assert first.id != second.id
        rows = (
            db.query(TaskEvaluation)
            .filter(TaskEvaluation.task_id == task.id, TaskEvaluation.run_evaluation_id == run_eval.id)
            .all()
        )
        assert {row.id for row in rows} == {first.id, second.id}

    def test_task_run_linkage_works_and_run_task_id_is_ignored(self, db):
        space, user = _setup(db)
        canonical_task = _task(db, space_id=space, user_id=user)
        hint_task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        run.task_id = hint_task.id
        _link(db, task=canonical_task, run=run)
        run_eval = _run_evaluation(db, run=run)
        db.flush()

        task_eval = _bridge(db, run_eval, space_id=space)

        assert task_eval.task_id == canonical_task.id
        assert task_eval.task_id != hint_task.id

    def test_run_task_id_without_task_run_raises(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        run.task_id = task.id
        run_eval = _run_evaluation(db, run=run)
        db.flush()

        with pytest.raises(TaskEvaluationNotFoundError, match="No TaskRun linkage found"):
            _bridge(db, run_eval, space_id=space)

        assert db.query(TaskEvaluation).filter(TaskEvaluation.run_evaluation_id == run_eval.id).count() == 0

    def test_primary_task_run_wins_otherwise_created_at_id_order_is_deterministic(self, db):
        space, user = _setup(db)
        run = _run(db, space_id=space, user_id=user)
        first_task = _task(db, space_id=space, user_id=user)
        primary_task = _task(db, space_id=space, user_id=user)
        _link(db, task=first_task, run=run, role="related")
        _link(db, task=primary_task, run=run, role="primary")
        run_eval = _run_evaluation(db, run=run)

        task_eval = _bridge(db, run_eval, space_id=space)
        assert task_eval.task_id == primary_task.id

        run2 = _run(db, space_id=space, user_id=user)
        older_task = _task(db, space_id=space, user_id=user)
        newer_task = _task(db, space_id=space, user_id=user)
        _link(db, task=older_task, run=run2, role="related")
        _link(db, task=newer_task, run=run2, role="related")
        run_eval2 = _run_evaluation(db, run=run2)

        task_eval2 = _bridge(db, run_eval2, space_id=space)
        assert task_eval2.task_id == older_task.id

    def test_cross_space_run_evaluation_cannot_be_bridged(self, db):
        space_a, user_a = _setup(db)
        space_b, user_b = _setup(db)
        task = _task(db, space_id=space_b, user_id=user_b)
        run = _run(db, space_id=space_b, user_id=user_b)
        _link(db, task=task, run=run)
        run_eval = _run_evaluation(db, run=run)

        with pytest.raises(TaskEvaluationNotFoundError, match="not found in this space"):
            _bridge(db, run_eval, space_id=space_a)

        assert db.query(TaskEvaluation).filter(TaskEvaluation.space_id == space_a).count() == 0

    def test_evidence_projection(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        artifact = factories.create_test_artifact(db, space_id=space, run_id=run.id)
        evidence = {
            "context": {"warnings": ["stable_prefix_warning"]},
            "materialization": {
                "codes": ["artifact_write_failed"],
                "errors": [{"code": "disk_full"}],
            },
            "validation": {"status": "failed", "signals": ["validation_step_failed"]},
        }
        run_eval = _run_evaluation(
            db,
            run=run,
            outcome_status="failed",
            trajectory_status="unsafe",
            failure_layer="runtime",
            failure_reason_code="adapter_runtime_error",
            evidence_json=evidence,
        )

        task_eval = _bridge(db, run_eval, space_id=space)

        assert task_eval.checklist_json == {
            "run_evaluation_id": run_eval.id,
            "run_id": run.id,
            "outcome_status": "failed",
            "trajectory_status": "unsafe",
            "failure_layer": "runtime",
            "failure_reason_code": "adapter_runtime_error",
            "evaluator_version": "harness_eval.v1",
        }
        assert {"kind": "context_warning", "code": "stable_prefix_warning"} in task_eval.known_issues_json
        assert {"kind": "materialization_code", "code": "artifact_write_failed"} in task_eval.known_issues_json
        assert {"kind": "materialization_error", "error": {"code": "disk_full"}} in task_eval.known_issues_json
        assert {"kind": "validation_status", "status": "failed"} in task_eval.known_issues_json
        assert {"kind": "validation_signal", "code": "validation_step_failed"} in task_eval.known_issues_json
        assert {"kind": "trajectory", "status": "unsafe"} in task_eval.known_issues_json
        assert task_eval.evidence_artifact_ids == [artifact.id]
        assert task_eval.summary == "Run evaluation failed at runtime: adapter_runtime_error."

    def test_no_side_effects(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user, status="in_progress")
        run = _run(db, space_id=space, user_id=user, status="succeeded")
        _link(db, task=task, run=run)
        run_eval = _run_evaluation(db, run=run)
        task_status = task.status
        run_snapshot = {
            "status": run.status,
            "error_json": run.error_json,
            "output_json": run.output_json,
            "task_id": run.task_id,
        }
        run_eval_snapshot = {
            "outcome_status": run_eval.outcome_status,
            "trajectory_status": run_eval.trajectory_status,
            "failure_layer": run_eval.failure_layer,
            "failure_reason_code": run_eval.failure_reason_code,
            "evidence_json": run_eval.evidence_json,
        }
        counts_before = {
            "memory": db.query(MemoryEntry).filter(MemoryEntry.space_id == space).count(),
            "policy": db.query(Policy).filter(Policy.space_id == space).count(),
            "proposal": db.query(Proposal).filter(Proposal.space_id == space).count(),
            "reflection": db.query(RunReflection).filter(RunReflection.space_id == space).count(),
        }

        _bridge(db, run_eval, space_id=space)
        db.refresh(task)
        db.refresh(run)
        db.refresh(run_eval)

        assert task.status == task_status
        assert {
            "status": run.status,
            "error_json": run.error_json,
            "output_json": run.output_json,
            "task_id": run.task_id,
        } == run_snapshot
        assert {
            "outcome_status": run_eval.outcome_status,
            "trajectory_status": run_eval.trajectory_status,
            "failure_layer": run_eval.failure_layer,
            "failure_reason_code": run_eval.failure_reason_code,
            "evidence_json": run_eval.evidence_json,
        } == run_eval_snapshot
        assert counts_before == {
            "memory": db.query(MemoryEntry).filter(MemoryEntry.space_id == space).count(),
            "policy": db.query(Policy).filter(Policy.space_id == space).count(),
            "proposal": db.query(Proposal).filter(Proposal.space_id == space).count(),
            "reflection": db.query(RunReflection).filter(RunReflection.space_id == space).count(),
        }


class TestTaskEvaluationBridgeAPI:
    def test_post_creates_from_latest_run_evaluation(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        task = _task(db, space_id=space, user_id=user.id)
        run = _run(db, space_id=space, user_id=user.id)
        _link(db, task=task, run=run)
        _run_evaluation(
            db,
            run=run,
            outcome_status="failed",
            failure_layer="runtime",
            failure_reason_code="adapter_runtime_error",
            evaluated_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        latest = _run_evaluation(
            db,
            run=run,
            outcome_status="passed",
            trajectory_status="acceptable",
            evaluated_at=datetime.now(UTC),
        )
        db.commit()

        response = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/evaluation/task",
            params={"space_id": space},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["task_id"] == task.id
        assert body["run_id"] == run.id
        assert body["run_evaluation_id"] == latest.id
        assert body["recommendation"] == "accept"

    def test_post_404_when_no_run_evaluation_exists(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        task = _task(db, space_id=space, user_id=user.id)
        run = _run(db, space_id=space, user_id=user.id)
        _link(db, task=task, run=run)
        db.commit()

        response = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/evaluation/task",
            params={"space_id": space},
        )

        assert response.status_code == 404
        assert "evaluate first" in response.json()["message"]

    def test_post_404_when_no_task_run_linkage_exists(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _run(db, space_id=space, user_id=user.id)
        _run_evaluation(db, run=run)
        db.commit()

        response = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/evaluation/task",
            params={"space_id": space},
        )

        assert response.status_code == 404
        assert "No TaskRun linkage found" in response.json()["message"]

    def test_post_rejects_cross_space_access(self, db, cross_space_pair):
        space_a = cross_space_pair["space_a_id"]
        space_b = cross_space_pair["space_b_id"]
        user_b = cross_space_pair["user_b"]
        task = _task(db, space_id=space_b, user_id=user_b.id)
        run = _run(db, space_id=space_b, user_id=user_b.id)
        _link(db, task=task, run=run)
        _run_evaluation(db, run=run)
        db.commit()

        response = cross_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/evaluation/task",
            params={"space_id": space_a},
        )

        assert response.status_code == 404
        assert db.query(TaskEvaluation).filter(TaskEvaluation.space_id == space_a).count() == 0


class TestListTaskEvaluationsAPI:
    def test_list_returns_empty_page_for_task_with_no_evaluations(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        task = _task(db, space_id=space, user_id=user.id)
        db.commit()

        response = same_space_pair["client_a"].get(
            f"/api/v1/tasks/{task.id}/evaluations",
            params={"space_id": space},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_list_returns_404_for_missing_task(self, db, same_space_pair):
        space = same_space_pair["space_id"]

        response = same_space_pair["client_a"].get(
            "/api/v1/tasks/nonexistent-task-id/evaluations",
            params={"space_id": space},
        )

        assert response.status_code == 404

    def test_list_returns_404_for_cross_space_task(self, db, cross_space_pair):
        space_a = cross_space_pair["space_a_id"]
        space_b = cross_space_pair["space_b_id"]
        user_b = cross_space_pair["user_b"]
        task = _task(db, space_id=space_b, user_id=user_b.id)
        db.commit()

        response = cross_space_pair["client_a"].get(
            f"/api/v1/tasks/{task.id}/evaluations",
            params={"space_id": space_a},
        )

        assert response.status_code == 404


def test_bridge_can_consume_run_evaluation_service_output(db):
    space, user = _setup(db)
    task = _task(db, space_id=space, user_id=user)
    run = _run(db, space_id=space, user_id=user)
    _link(db, task=task, run=run)
    artifact = factories.create_test_artifact(db, space_id=space, run_id=run.id)
    run_eval = RunEvaluationService(db).evaluate(run.id, space_id=space)

    task_eval = TaskEvaluationService(db).create_from_run_evaluation(
        run_eval.id,
        space_id=space,
    )

    assert task_eval.run_evaluation_id == run_eval.id
    assert task_eval.evidence_artifact_ids == [artifact.id]


# ---------------------------------------------------------------------------
# Service-layer import assertion
# ---------------------------------------------------------------------------

def test_evaluation_service_does_not_import_fastapi():
    import importlib
    mod = importlib.import_module("app.tasks.evaluation_service")
    assert not hasattr(mod, "HTTPException"), "evaluation_service must not import HTTPException"
    # Also verify fastapi is not a direct dependency of the module
    source_file = mod.__file__
    assert source_file is not None
    with open(source_file) as f:
        source = f.read()
    assert "fastapi" not in source, "evaluation_service must not reference fastapi"
    assert "HTTPException" not in source, "evaluation_service must not reference HTTPException"


# ---------------------------------------------------------------------------
# Evidence artifact linkage rules
# ---------------------------------------------------------------------------

class TestBridgeEvidenceArtifactLinkage:
    def test_bridge_includes_run_artifacts_without_task_artifact_row(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        # Create artifact linked to the run but with no TaskArtifact row
        artifact = factories.create_test_artifact(db, space_id=space, run_id=run.id)
        assert db.query(TaskArtifact).filter(TaskArtifact.artifact_id == artifact.id).count() == 0

        run_eval = _run_evaluation(db, run=run)
        task_eval = _bridge(db, run_eval, space_id=space)

        assert artifact.id in task_eval.evidence_artifact_ids

    def test_bridge_does_not_create_task_artifact_rows(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        run = _run(db, space_id=space, user_id=user)
        _link(db, task=task, run=run)
        factories.create_test_artifact(db, space_id=space, run_id=run.id)
        run_eval = _run_evaluation(db, run=run)
        count_before = db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).count()

        _bridge(db, run_eval, space_id=space)

        assert db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).count() == count_before


class TestManualEvaluationEvidenceArtifactLinkage:
    def _payload(self, **kwargs) -> TaskEvaluationCreate:
        return TaskEvaluationCreate(evaluator_type="human", **kwargs)

    def test_manual_rejects_artifact_not_in_space(self, db):
        space_a, user_a = _setup(db)
        space_b, user_b = _setup(db)
        task = _task(db, space_id=space_a, user_id=user_a)
        other_artifact = factories.create_test_artifact(db, space_id=space_b)

        payload = self._payload(evidence_artifact_ids=[other_artifact.id])
        with pytest.raises(TaskEvaluationInvalidRequestError, match="artifacts in the current space"):
            TaskEvaluationService(db).create_manual_task_evaluation(task.id, space_a, user_a, payload)

    def test_manual_rejects_artifact_not_linked_via_task_artifact(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        artifact = factories.create_test_artifact(db, space_id=space)
        # Artifact exists in the space but no TaskArtifact row links it to this task

        payload = self._payload(evidence_artifact_ids=[artifact.id])
        with pytest.raises(TaskEvaluationInvalidRequestError, match="linked to the task through TaskArtifact"):
            TaskEvaluationService(db).create_manual_task_evaluation(task.id, space, user, payload)

    def test_manual_accepts_artifact_with_task_artifact_linkage(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)
        artifact = factories.create_test_artifact(db, space_id=space)
        link = TaskArtifact(
            id=_id(),
            space_id=space,
            task_id=task.id,
            artifact_id=artifact.id,
        )
        db.add(link)
        db.flush()

        payload = self._payload(evidence_artifact_ids=[artifact.id])
        task_eval = TaskEvaluationService(db).create_manual_task_evaluation(task.id, space, user, payload)

        assert task_eval.evidence_artifact_ids == [artifact.id]

    def test_manual_rejects_reserved_evaluator_type(self, db):
        space, user = _setup(db)
        task = _task(db, space_id=space, user_id=user)

        payload = TaskEvaluationCreate(evaluator_type="run_evaluation_bridge")
        with pytest.raises(TaskEvaluationInvalidRequestError, match="reserved"):
            TaskEvaluationService(db).create_manual_task_evaluation(task.id, space, user, payload)
