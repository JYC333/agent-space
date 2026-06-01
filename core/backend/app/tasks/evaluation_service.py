"""TaskEvaluationService — append-only task-level evaluations."""

from __future__ import annotations
import uuid

from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    Run,
    RunEvaluation,
    Task,
    TaskArtifact,
    TaskEvaluation,
    TaskRun,
)
from app.schemas import TaskEvaluationCreate

from .evaluation_errors import TaskEvaluationInvalidRequestError, TaskEvaluationNotFoundError
from .visibility import can_read_task

_EVALUATOR_TYPE_BRIDGE = "run_evaluation_bridge"

_OUTCOME_TO_SCORE: dict[str, Optional[float]] = {
    "passed": 1.0,
    "partial": 0.5,
    "failed": 0.0,
    "unknown": None,
}

_OUTCOME_TO_RECOMMENDATION: dict[str, str] = {
    "passed": "accept",
    "partial": "review",
    "failed": "retry",
    "unknown": "needs_evidence",
}

_OUTCOME_TO_CONFIDENCE: dict[str, float] = {
    "passed": 1.0,
    "failed": 1.0,
    "partial": 0.7,
    "unknown": 0.3,
}


def _new_id() -> str:
    return str(uuid.uuid4())


def _build_summary(re: RunEvaluation) -> str:
    outcome = re.outcome_status
    trajectory = re.trajectory_status
    if outcome == "passed" and trajectory == "acceptable":
        return "Run evaluation passed with acceptable trajectory."
    if outcome == "failed":
        if re.failure_layer and re.failure_reason_code:
            return f"Run evaluation failed at {re.failure_layer}: {re.failure_reason_code}."
        if re.failure_layer:
            return f"Run evaluation failed at {re.failure_layer}."
        if re.failure_reason_code:
            return f"Run evaluation failed: {re.failure_reason_code}."
        return "Run evaluation failed."
    if outcome == "partial":
        return f"Run evaluation is partial; trajectory {trajectory}."
    if outcome == "unknown":
        return f"Run evaluation is unknown; trajectory {trajectory}."
    return f"Run evaluation {outcome}; trajectory {trajectory}."


def _build_checklist(re: RunEvaluation) -> dict:
    return {
        "run_evaluation_id": re.id,
        "run_id": re.run_id,
        "outcome_status": re.outcome_status,
        "trajectory_status": re.trajectory_status,
        "failure_layer": re.failure_layer,
        "failure_reason_code": re.failure_reason_code,
        "evaluator_version": re.evaluator_version,
    }


def _build_known_issues(re: RunEvaluation) -> list:
    issues: list[dict] = []
    if re.failure_layer or re.failure_reason_code:
        issues.append(
            {
                "kind": "failure",
                "failure_layer": re.failure_layer,
                "failure_reason_code": re.failure_reason_code,
            }
        )

    evidence = re.evidence_json or {}
    context = evidence.get("context") if isinstance(evidence, dict) else None
    if isinstance(context, dict):
        warnings = context.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if warning:
                    issues.append({"kind": "context_warning", "code": str(warning)})

    materialization = evidence.get("materialization") if isinstance(evidence, dict) else None
    if isinstance(materialization, dict):
        codes = materialization.get("codes")
        if isinstance(codes, list):
            for code in codes:
                if code:
                    issues.append({"kind": "materialization_code", "code": str(code)})
        errors = materialization.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if error:
                    issues.append({"kind": "materialization_error", "error": error})
        patch_warnings = materialization.get("code_patch_warnings")
        if isinstance(patch_warnings, list):
            for warning in patch_warnings:
                if warning:
                    issues.append({"kind": "materialization_warning", "code": str(warning)})

    validation = evidence.get("validation") if isinstance(evidence, dict) else None
    if isinstance(validation, dict):
        status = validation.get("status")
        if status:
            issues.append({"kind": "validation_status", "status": str(status)})
        signals = validation.get("signals")
        if isinstance(signals, list):
            for signal in signals:
                if signal:
                    issues.append({"kind": "validation_signal", "code": str(signal)})

    if re.trajectory_status == "unsafe":
        issues.append({"kind": "trajectory", "status": "unsafe"})
    return issues


class TaskEvaluationService:
    """Create and read append-only TaskEvaluation rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_task(self, task_id: str, space_id: str, user_id: Optional[str] = None) -> Task:
        task = (
            self.db.query(Task)
            .filter(Task.id == task_id, Task.space_id == space_id, Task.deleted_at.is_(None))
            .first()
        )
        if not task:
            raise TaskEvaluationNotFoundError("Task not found")
        if user_id is not None and not can_read_task(task, user_id):
            raise TaskEvaluationNotFoundError("Task not found")
        return task

    def _get_task_run_link(self, task_id: str, run_id: str, space_id: str) -> TaskRun:
        link = (
            self.db.query(TaskRun)
            .filter(
                TaskRun.task_id == task_id,
                TaskRun.run_id == run_id,
                TaskRun.space_id == space_id,
            )
            .first()
        )
        if not link:
            raise TaskEvaluationNotFoundError(
                f"Run '{run_id}' is not linked to task '{task_id}' in this space via TaskRun"
            )
        return link

    def _select_task_run_for_run(self, run_id: str, space_id: str) -> TaskRun:
        # A run can be associated with more than one task. The primary link wins;
        # otherwise created_at/id gives deterministic selection across databases.
        links = (
            self.db.query(TaskRun)
            .filter(TaskRun.run_id == run_id, TaskRun.space_id == space_id)
            .order_by(
                (TaskRun.role == "primary").desc(),
                TaskRun.created_at.asc(),
                TaskRun.id.asc(),
            )
            .all()
        )
        if not links:
            raise TaskEvaluationNotFoundError(f"No TaskRun linkage found for run '{run_id}' in this space")
        return links[0]

    def _validate_evidence_artifacts(
        self,
        task_id: str,
        space_id: str,
        artifact_ids: Optional[list],
    ) -> None:
        if not artifact_ids:
            return

        ids = [str(artifact_id) for artifact_id in artifact_ids]
        unique_ids = set(ids)

        artifact_count = (
            self.db.query(Artifact.id)
            .filter(Artifact.id.in_(unique_ids), Artifact.space_id == space_id)
            .count()
        )
        if artifact_count != len(unique_ids):
            raise TaskEvaluationInvalidRequestError(
                "evidence_artifact_ids must reference artifacts in the current space"
            )

        linked_count = (
            self.db.query(TaskArtifact.id)
            .filter(
                TaskArtifact.task_id == task_id,
                TaskArtifact.space_id == space_id,
                TaskArtifact.artifact_id.in_(unique_ids),
            )
            .count()
        )
        if linked_count != len(unique_ids):
            raise TaskEvaluationInvalidRequestError(
                "evidence_artifact_ids must be linked to the task through TaskArtifact"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_task_evaluations(
        self,
        task_id: str,
        space_id: str,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[TaskEvaluation]]:
        self._get_task(task_id, space_id, user_id)
        q = (
            self.db.query(TaskEvaluation)
            .filter(TaskEvaluation.task_id == task_id, TaskEvaluation.space_id == space_id)
            .order_by(TaskEvaluation.created_at.desc())
        )
        total = q.count()
        rows = q.offset(offset).limit(limit).all()
        return total, rows

    def get_latest_for_task(self, task_id: str, space_id: str) -> Optional[TaskEvaluation]:
        return (
            self.db.query(TaskEvaluation)
            .filter(TaskEvaluation.task_id == task_id, TaskEvaluation.space_id == space_id)
            .order_by(TaskEvaluation.created_at.desc(), TaskEvaluation.id.desc())
            .first()
        )

    def list_for_task(self, task_id: str, space_id: str) -> list[TaskEvaluation]:
        return (
            self.db.query(TaskEvaluation)
            .filter(TaskEvaluation.task_id == task_id, TaskEvaluation.space_id == space_id)
            .order_by(TaskEvaluation.created_at.desc(), TaskEvaluation.id.desc())
            .all()
        )

    def list_for_run_evaluation(
        self,
        run_evaluation_id: str,
        space_id: str,
    ) -> list[TaskEvaluation]:
        return (
            self.db.query(TaskEvaluation)
            .filter(
                TaskEvaluation.run_evaluation_id == run_evaluation_id,
                TaskEvaluation.space_id == space_id,
            )
            .order_by(TaskEvaluation.created_at.desc(), TaskEvaluation.id.desc())
            .all()
        )

    def create_from_run_evaluation(
        self,
        run_evaluation_id: str,
        *,
        space_id: str,
    ) -> TaskEvaluation:
        # Bridge-created evaluations derive evidence from the evaluated Run's artifacts because
        # RunEvaluation is the authoritative source record; TaskArtifact linkage is not required.
        run_eval = (
            self.db.query(RunEvaluation)
            .filter(RunEvaluation.id == run_evaluation_id, RunEvaluation.space_id == space_id)
            .first()
        )
        if run_eval is None:
            raise TaskEvaluationNotFoundError(f"RunEvaluation '{run_evaluation_id}' not found in this space")

        run = (
            self.db.query(Run)
            .filter(Run.id == run_eval.run_id, Run.space_id == space_id)
            .first()
        )
        if run is None:
            raise TaskEvaluationNotFoundError(f"Run '{run_eval.run_id}' not found in this space")

        task_run = self._select_task_run_for_run(run.id, space_id)
        task = (
            self.db.query(Task)
            .filter(
                Task.id == task_run.task_id,
                Task.space_id == space_id,
                Task.deleted_at.is_(None),
            )
            .first()
        )
        if task is None:
            raise TaskEvaluationNotFoundError(f"Task '{task_run.task_id}' not found in this space")

        artifact_ids = [
            row.id
            for row in (
                self.db.query(Artifact.id)
                .filter(Artifact.run_id == run.id, Artifact.space_id == space_id)
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                .all()
            )
        ]

        outcome = run_eval.outcome_status
        row = TaskEvaluation(
            id=_new_id(),
            space_id=space_id,
            task_id=task.id,
            run_id=run.id,
            run_evaluation_id=run_eval.id,
            evaluator_type=_EVALUATOR_TYPE_BRIDGE,
            score=_OUTCOME_TO_SCORE.get(outcome),
            confidence=_OUTCOME_TO_CONFIDENCE.get(outcome, 0.3),
            summary=_build_summary(run_eval),
            checklist_json=_build_checklist(run_eval),
            known_issues_json=_build_known_issues(run_eval),
            evidence_artifact_ids=artifact_ids,
            recommendation=_OUTCOME_TO_RECOMMENDATION.get(outcome, "needs_evidence"),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def create_manual_task_evaluation(
        self,
        task_id: str,
        space_id: str,
        user_id: str,
        payload: TaskEvaluationCreate,
    ) -> TaskEvaluation:
        # Manual evaluations must reference task-linked artifacts through TaskArtifact because
        # they are not anchored by a RunEvaluation that defines the artifact scope.
        self._get_task(task_id, space_id, user_id)
        if payload.evaluator_type == _EVALUATOR_TYPE_BRIDGE:
            raise TaskEvaluationInvalidRequestError(
                'evaluator_type="run_evaluation_bridge" is reserved for system-created bridge evaluations'
            )
        if payload.run_id is not None:
            self._get_task_run_link(task_id, payload.run_id, space_id)
        self._validate_evidence_artifacts(task_id, space_id, payload.evidence_artifact_ids)
        row = TaskEvaluation(
            id=_new_id(),
            space_id=space_id,
            task_id=task_id,
            run_id=payload.run_id,
            evaluator_type=payload.evaluator_type,
            evaluator_user_id=user_id,
            score=payload.score,
            confidence=payload.confidence,
            summary=payload.summary,
            checklist_json=payload.checklist_json,
            known_issues_json=payload.known_issues_json,
            evidence_artifact_ids=payload.evidence_artifact_ids,
            recommendation=payload.recommendation,
        )
        self.db.add(row)
        self.db.flush()
        return row
