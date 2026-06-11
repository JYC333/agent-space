"""Canonical workflow tests for RunEvaluationService (harness-level, deterministic).

Tests verify:
- Append-only persistence semantics (no UNIQUE(run_id) behavior)
- Real RunStep shape: adapter_started terminal status counts as adapter completion
- Exact error-code mapping before heuristics
- ContextSnapshot evidence handling (real token_budget_json shape)
- RunEvent structured evidence for patch/artifact classification (canonical path)
- Trajectory vs outcome independence
- Hard invariants: evaluation never writes Memory, Policy, Proposal, etc.
"""
from __future__ import annotations

import pytest

from app.models import MemoryEntry, Policy, Proposal, RunEvaluation
from app.runs.evaluation import (
    TRAJECTORY_STATUSES,
    RunEvaluationService,
    _classify_trajectory,
    _collect_error_codes,
    requires_context_snapshot,
)
from tests.support import factories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPACE = "space-eval-01"
USER = "user-eval-01"


def _setup(db):
    factories.create_test_space(db, space_id=SPACE)
    factories.create_test_user(db, space_id=SPACE, user_id=USER)


def _actor(db, run):
    from app.runs.steps import resolve_run_actor
    return resolve_run_actor(db, run)


# ---------------------------------------------------------------------------
# Schema / persistence: append-only semantics
# ---------------------------------------------------------------------------

class TestPersistenceAppendOnly:
    def test_re_evaluate_creates_second_row(self, db):
        """Re-evaluating a run appends a new row — existing row is never deleted."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        svc = RunEvaluationService(db)
        first = svc.evaluate(run.id, space_id=SPACE)
        db.flush()
        first_id = first.id

        run.status = "succeeded"
        run.error_json = None
        db.flush()

        second = svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        assert second.id != first_id
        assert second.outcome_status == "passed"

        # Both rows must exist
        count = db.query(RunEvaluation).filter(RunEvaluation.run_id == run.id).count()
        assert count == 2

    def test_get_latest_returns_newest_row(self, db):
        """get_latest() returns the most recently created evaluation."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        svc = RunEvaluationService(db)
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        run.status = "succeeded"
        run.error_json = None
        db.flush()
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        latest = svc.get_latest(run.id, space_id=SPACE)
        assert latest is not None
        assert latest.outcome_status == "passed"

    def test_list_for_run_returns_all_rows_newest_first(self, db):
        """list_for_run() returns all evaluations newest first."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        svc = RunEvaluationService(db)
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        run.status = "succeeded"
        run.error_json = None
        db.flush()
        svc.evaluate(run.id, space_id=SPACE)
        db.flush()

        rows = svc.list_for_run(run.id, space_id=SPACE)
        assert len(rows) == 2
        assert rows[0].outcome_status == "passed"
        assert rows[1].outcome_status == "failed"

    def test_get_latest_returns_none_before_evaluate(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        db.flush()

        result = RunEvaluationService(db).get_latest(run.id, space_id=SPACE)
        assert result is None

    def test_evaluate_raises_on_missing_run(self, db):
        _setup(db)
        with pytest.raises(ValueError, match="not found"):
            RunEvaluationService(db).evaluate("nonexistent-run-id", space_id=SPACE)

    def test_evidence_json_has_structured_shape(self, db):
        """evidence_json must have the canonical structured shape."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        ev = result.evidence_json
        assert isinstance(ev, dict)
        assert "run" in ev
        assert "steps" in ev
        assert "context" in ev
        assert "artifacts" in ev
        assert "proposals" in ev
        assert "validation" in ev
        assert "materialization" in ev
        assert ev["run"]["status"] == "succeeded"

    def test_rule_trace_json_is_populated(self, db):
        """rule_trace_json must be a non-empty list."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert isinstance(result.rule_trace_json, list)
        assert len(result.rule_trace_json) > 0

    def test_evaluator_fields_are_set(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.evaluator_type == "deterministic_harness"
        assert result.evaluator_version == "harness_eval.v1"
        assert result.evaluated_at is not None


# ---------------------------------------------------------------------------
# outcome_status
# ---------------------------------------------------------------------------

class TestOutcomeStatus:
    def test_queued_run_is_unknown(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "queued"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "unknown"
        assert result.trajectory_status in TRAJECTORY_STATUSES

    def test_failed_run_is_failed(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "failed"

    def test_nonzero_exit_code_is_failed(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        run.exit_code = 1
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "failed"

    def test_error_json_with_code_is_failed(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        run.error_json = {"code": "runtime_error", "detail": "boom"}
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "failed"

    def test_degraded_run_is_partial(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "degraded"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"

    def test_succeeded_with_validation_failed_proposal_is_partial(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        factories.create_test_proposal(
            db,
            space_id=SPACE,
            run_id=run.id,
            payload_json={"validation": {"status": "failed"}, "proposed_content": "x"},
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"

    def test_succeeded_with_run_event_code_patch_incomplete_is_partial(self, db):
        """patch_collected warning event with code_patch_incomplete → partial outcome."""
        from app.runs.events import RunEventService
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        RunEventService(db).append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="warning",
            error_code="code_patch_incomplete",
            metadata_json={"incomplete_patch": True, "proposal_created": True},
        )
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        assert result.trajectory_status == "incomplete"

    def test_clean_succeeded_run_is_passed(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "passed"
        assert result.failure_layer is None


# ---------------------------------------------------------------------------
# RunStep semantics: adapter_started terminal status = adapter completed
# ---------------------------------------------------------------------------

class TestRunStepSemantics:
    def test_adapter_started_succeeded_plus_completed_is_acceptable(self, db):
        """adapter_started(succeeded) counts as adapter completion; full run is acceptable."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        actor = _actor(db, run)
        for st, ss in [
            ("run_created", "succeeded"),
            ("context_prepared", "succeeded"),
            ("adapter_started", "succeeded"),  # terminal status — no adapter_completed needed
            ("completed", "succeeded"),
        ]:
            factories.create_test_run_step(db, run=run, actor_id=actor.id,
                                           step_type=st, status=ss)

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "passed"
        assert result.trajectory_status == "acceptable"
        assert result.evidence_json["steps"]["adapter_started_terminal"] is True

    def test_adapter_started_failed_is_not_missing_completion(self, db):
        """adapter_started(failed) is terminal; missing_adapter_completion must be False."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(db, run=run, actor_id=actor.id,
                                       step_type="adapter_started", status="failed",
                                       error_type="adapter_runtime_error")
        factories.create_test_run_step(db, run=run, actor_id=actor.id,
                                       step_type="failed", status="failed")

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.evidence_json["steps"]["adapter_started_terminal"] is True
        # B2 exact map: adapter_runtime_error → runtime
        assert result.failure_layer == "runtime"
        assert result.failure_reason_code == "adapter_runtime_error"
        # NOT orchestration (adapter_started was terminal)
        assert result.failure_layer != "orchestration"

    def test_adapter_started_running_without_completion_is_incomplete(self, db):
        """adapter_started(running) — not terminal — and no completion → trajectory incomplete."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(db, run=run, actor_id=actor.id,
                                       step_type="adapter_started", status="running")
        # No completed or failed terminal step

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.evidence_json["steps"]["adapter_started_terminal"] is False
        assert result.trajectory_status == "incomplete"
        assert result.failure_layer == "orchestration"

    def test_complete_successful_run_is_acceptable(self, db):
        """Full adapter_started(succeeded) + adapter_completed + completed → acceptable."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        actor = _actor(db, run)
        for st in ("run_created", "context_prepared", "adapter_started",
                   "adapter_completed", "completed"):
            factories.create_test_run_step(db, run=run, actor_id=actor.id,
                                           step_type=st, status="succeeded")

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.trajectory_status == "acceptable"
        assert result.outcome_status == "passed"


# ---------------------------------------------------------------------------
# Exact error-code mapping (must run before heuristics)
# ---------------------------------------------------------------------------

class TestExactErrorCodeMapping:
    def _eval_with_error_code(self, db, error_code: str):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.error_json = {"error_code": error_code}
        db.flush()
        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()
        return result

    def test_context_snapshot_population_failed_maps_to_context(self, db):
        r = self._eval_with_error_code(db, "context_snapshot_population_failed")
        assert r.failure_layer == "context"
        assert r.failure_reason_code == "context_snapshot_population_failed"

    def test_sandbox_required_maps_to_sandbox(self, db):
        r = self._eval_with_error_code(db, "sandbox_required")
        assert r.failure_layer == "sandbox"
        assert r.failure_reason_code == "sandbox_required"

    def test_critical_runtime_docker_maps_to_sandbox(self, db):
        r = self._eval_with_error_code(
            db, "critical_runtime_requires_unimplemented_one_shot_docker"
        )
        assert r.failure_layer == "sandbox"

    def test_file_access_worktree_policy_maps_to_policy_not_sandbox(self, db):
        """Must map to policy, not sandbox, despite 'worktree' in the code."""
        r = self._eval_with_error_code(
            db, "file_access_adapter_requires_worktree_policy"
        )
        assert r.failure_layer == "policy"
        assert r.failure_reason_code == "file_access_adapter_requires_worktree_policy"

    def test_automation_preflight_no_adapter_maps_to_task_spec(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_no_adapter")
        assert r.failure_layer == "task_spec"

    def test_automation_preflight_no_workspace_maps_to_task_spec(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_no_workspace")
        assert r.failure_layer == "task_spec"

    def test_automation_preflight_workspace_not_git_repo_maps_to_task_spec(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_workspace_not_git_repo")
        assert r.failure_layer == "task_spec"

    def test_automation_preflight_dirty_workspace_maps_to_policy(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_dirty_workspace")
        assert r.failure_layer == "policy"

    def test_automation_preflight_no_credential_profile_maps_to_policy(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_no_credential_profile")
        assert r.failure_layer == "policy"

    def test_automation_preflight_invalid_runtime_policy_maps_to_policy(self, db):
        r = self._eval_with_error_code(db, "automation_preflight_invalid_runtime_policy")
        assert r.failure_layer == "policy"

    def test_credentials_missing_maps_to_policy(self, db):
        r = self._eval_with_error_code(db, "credentials_missing")
        assert r.failure_layer == "policy"

    def test_adapter_runtime_error_maps_to_runtime(self, db):
        r = self._eval_with_error_code(db, "adapter_runtime_error")
        assert r.failure_layer == "runtime"

    def test_runtime_removed_maps_to_runtime(self, db):
        r = self._eval_with_error_code(db, "runtime_removed")
        assert r.failure_layer == "runtime"

    def test_duplicate_execution_maps_to_orchestration(self, db):
        r = self._eval_with_error_code(db, "duplicate_execution")
        assert r.failure_layer == "orchestration"

    def test_run_cancelled_maps_to_orchestration(self, db):
        r = self._eval_with_error_code(db, "run_cancelled")
        assert r.failure_layer == "orchestration"

    def test_exact_map_overrides_worktree_substring_heuristic(self, db):
        """file_access_adapter_requires_worktree_policy must NOT be classified as sandbox
        even though it contains 'worktree'. Exact map runs first."""
        r = self._eval_with_error_code(
            db, "file_access_adapter_requires_worktree_policy"
        )
        assert r.failure_layer == "policy"
        assert r.failure_layer != "sandbox"

    def test_step_error_type_is_collected_for_exact_mapping(self, db):
        """A failed RunStep.error_type participates in exact error-code mapping."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(
            db, run=run, actor_id=actor.id,
            step_type="failed", status="failed",
            error_type="adapter_runtime_error",
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "runtime"
        assert result.failure_reason_code == "adapter_runtime_error"


# ---------------------------------------------------------------------------
# failure_layer heuristic fallbacks (when no exact code)
# ---------------------------------------------------------------------------

class TestFailureLayerHeuristics:
    def test_missing_context_snapshot_gives_context_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.context_snapshot_id = None
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "context"
        assert result.failure_reason_code == "context_snapshot_missing"

    def test_sandbox_keyword_in_step_error_gives_sandbox_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(
            db, run=run, actor_id=actor.id,
            step_type="failed", status="failed",
            error_type="sandbox_init_error",
            error_message="sandbox could not start",
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "sandbox"

    def test_validation_failed_proposal_gives_validation_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "degraded"
        db.flush()

        factories.create_test_proposal(
            db, space_id=SPACE, run_id=run.id,
            payload_json={"validation": {"status": "failed"}, "proposed_content": "x"},
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "validation"

    def test_missing_adapter_completed_gives_orchestration_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(
            db, run=run, actor_id=actor.id,
            step_type="adapter_started", status="running",
        )
        # No terminal adapter step — orchestration broken

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "orchestration"

    def test_adapter_completed_failed_step_gives_runtime_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.exit_code = 1
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(
            db, run=run, actor_id=actor.id,
            step_type="adapter_completed", status="failed",
            error_type="adapter_error",
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "runtime"


# ---------------------------------------------------------------------------
# ContextSnapshot handling
# ---------------------------------------------------------------------------

class TestContextSnapshotHandling:
    def test_terminal_managed_run_without_snapshot_gives_context_layer(self, db):
        """A terminal managed run with no ContextSnapshot → context failure."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.context_snapshot_id = None
        run.source = None  # managed/native — requires snapshot
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "context"
        assert result.trajectory_status in ("insufficient_evidence", "incomplete")

    def test_zero_retrieved_memories_does_not_cause_context_failure(self, db):
        """Empty memory retrieval in context snapshot is evidence only, not failure."""
        from app.models import ContextSnapshot
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        # Attach snapshot with retrieval_trace showing zero retrieved memories
        snap = db.query(ContextSnapshot).filter(
            ContextSnapshot.id == run.context_snapshot_id
        ).first()
        snap.retrieval_trace_json = [{"retrieved_count": 0, "memories": []}]
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        # Not a context failure — zero retrieval is acceptable
        assert result.outcome_status == "passed"
        assert result.failure_layer is None

    def test_stable_prefix_warning_is_evidence_not_failure(self, db):
        """stable_prefix_warning in token_budget_json is stored as a warning, not failure."""
        from app.models import ContextSnapshot
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        snap = db.query(ContextSnapshot).filter(
            ContextSnapshot.id == run.context_snapshot_id
        ).first()
        snap.token_budget_json = {
            "stable_prefix_chars": 10000,
            "dynamic_tail_chars": 5000,
            "total_chars": 15000,
            "stable_prefix_budget_chars": 8000,
            "stable_prefix_pct": 0.67,
            "stable_prefix_target_pct": 0.70,
            "stable_prefix_warning": True,
            "compiler_version": "v1",
        }
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "passed"
        assert result.failure_layer is None
        assert "stable_prefix_warning" in result.evidence_json["context"]["warnings"]

    def test_manual_import_run_exempt_from_snapshot_requirement(self, db):
        """manual_import runs do not require a ContextSnapshot."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.context_snapshot_id = None
        run.source = "manual_import"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        # context layer should NOT fire for manual_import
        assert result.failure_layer != "context"

    def test_requires_context_snapshot_helper(self):
        from unittest.mock import MagicMock
        run = MagicMock()
        run.source = None
        assert requires_context_snapshot(run) is True
        run.source = "managed"
        assert requires_context_snapshot(run) is True
        run.source = "manual_import"
        assert requires_context_snapshot(run) is False
        run.source = "remote_import"
        assert requires_context_snapshot(run) is False


# ---------------------------------------------------------------------------
# RunEvent structured evidence for patch/artifact classification (canonical path)
# ---------------------------------------------------------------------------

class TestRunEventPatchArtifactEvidence:
    """RunEvaluation must classify using RunEvent structured evidence only.

    output_json.materialization_errors is never parsed — it is not event evidence.
    """

    def test_proposal_incomplete_patch_gives_partial_and_trajectory_incomplete(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        factories.create_test_proposal(
            db, space_id=SPACE, run_id=run.id,
            payload_json={"incomplete_patch": True, "proposed_content": "x"},
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        assert result.trajectory_status == "incomplete"

    def test_patch_collected_warning_event_gives_partial_and_incomplete(self, db):
        """patch_collected status=warning with error_code=code_patch_incomplete → partial+incomplete."""
        from app.runs.events import RunEventService
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        RunEventService(db).append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="warning",
            error_code="code_patch_incomplete",
            metadata_json={"incomplete_patch": True, "proposal_created": True, "ops_count": 3},
        )
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        assert result.trajectory_status == "incomplete"
        mat = result.evidence_json.get("materialization", {})
        assert "code_patch_incomplete" in mat.get("code_patch_warnings", [])

    def test_patch_collected_failed_event_gives_partial_and_incomplete(self, db):
        """patch_collected status=failed with error_code=code_patch_collection_error → partial+incomplete."""
        from app.runs.events import RunEventService
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        RunEventService(db).append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="failed",
            error_code="code_patch_collection_error",
        )
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        assert result.trajectory_status == "incomplete"

    def test_artifact_ingested_warning_event_gives_partial(self, db):
        """artifact_ingested status=warning gives partial outcome on succeeded run."""
        from app.runs.events import RunEventService
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        RunEventService(db).append_event(
            run_id=run.id, space_id=SPACE,
            event_type="artifact_ingested", status="warning",
            error_code="produced_artifact_ingestion_error",
        )
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        mat = result.evidence_json.get("materialization", {})
        assert "produced_artifact_ingestion_error" in mat.get("codes", [])

    def test_output_json_materialization_errors_not_parsed_as_event_evidence(self, db):
        """materialization_errors in output_json must never drive classification.

        Even when no RunEvent rows exist, output_json.materialization_errors strings
        are not parsed. A clean succeeded run must be 'passed' regardless of what
        is stored in output_json.materialization_errors.
        """
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        run.output_json = {
            "materialization_errors": [
                "code_patch_skipped_files: a.png (binary)",
                "code_patch_collection_error: Traceback...",
            ]
        }
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        # Without RunEvent rows, output_json.materialization_errors must NOT cause partial
        assert result.outcome_status == "passed"
        # Materialization evidence must be empty (no fallback parsing)
        mat = result.evidence_json.get("materialization", {})
        assert mat.get("errors", []) == []
        assert mat.get("codes", []) == []
        assert mat.get("code_patch_warnings", []) == []

    def test_patch_collection_error_in_error_json_gives_tool_layer(self, db):
        """code_patch_collection_error in error_json on failed run → tool layer via exact map."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        run.error_json = {"error_code": "code_patch_collection_error"}
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.failure_layer == "tool"
        assert result.failure_reason_code == "code_patch_collection_error"

    def test_proposal_validation_failed_gives_validation_layer(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        factories.create_test_proposal(
            db, space_id=SPACE, run_id=run.id,
            payload_json={
                "proposed_content": "x",
                "validation": {"status": "failed", "command_count": 1},
            },
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "partial"
        assert result.failure_layer == "validation"


# ---------------------------------------------------------------------------
# Cancelled run outcome
# ---------------------------------------------------------------------------

class TestCancelledRunOutcome:
    def test_cancelled_run_no_error_json_is_failed_orchestration_run_cancelled(self, db):
        """status=cancelled + no error_json → failed / orchestration / run_cancelled."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "cancelled"
        run.error_json = None
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "failed"
        assert result.failure_layer == "orchestration"
        assert result.failure_reason_code == "run_cancelled"

    def test_cancelled_run_with_specific_error_code_uses_exact_mapping(self, db):
        """status=cancelled with error_json.error_code=sandbox_required → sandbox layer wins."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "cancelled"
        run.error_json = {"error_code": "sandbox_required"}
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "failed"
        assert result.failure_layer == "sandbox"
        assert result.failure_reason_code == "sandbox_required"

    def test_cancelled_run_is_not_unknown(self, db):
        """A cancelled run must never produce outcome_status=unknown."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "cancelled"
        run.error_json = None
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status != "unknown"

    def test_cancelled_run_run_cancelled_in_error_codes(self, db):
        """run_cancelled is synthesized into error_codes for cancelled runs."""
        from app.runs.evaluation import _collect_error_codes
        from unittest.mock import MagicMock

        run = MagicMock()
        run.status = "cancelled"
        run.error_json = None
        run.output_json = None

        codes = _collect_error_codes(run, [], [])
        assert "run_cancelled" in codes

    def test_cancelled_run_run_cancelled_not_duplicated_when_already_in_error_json(self, db):
        """If error_json already contains run_cancelled, it is not duplicated in codes."""
        from app.runs.evaluation import _collect_error_codes
        from unittest.mock import MagicMock

        run = MagicMock()
        run.status = "cancelled"
        run.error_json = {"error_code": "run_cancelled"}
        run.output_json = None

        codes = _collect_error_codes(run, [], [])
        assert codes.count("run_cancelled") == 1


# ---------------------------------------------------------------------------
# trajectory_status
# ---------------------------------------------------------------------------

class TestTrajectoryStatus:
    def test_no_steps_no_snapshot_no_artifacts_is_insufficient_evidence(self, db):
        # Use the low-level function directly with zero-evidence dict
        ev = {
            "steps": {"count": 0, "types": [], "failed": [],
                      "adapter_started_terminal": False, "has_terminal_step": False},
            "context": {"has_snapshot": False},
            "artifacts": {"count": 0, "low_trust_count": 0},
            "proposals": {"count": 0, "high_risk_count": 0,
                          "incomplete_patch": False, "validation_failed": False},
            "materialization": {"errors": [], "codes": [], "code_patch_warnings": []},
        }
        status, _ = _classify_trajectory(ev, "unknown")
        assert status == "insufficient_evidence"

    def test_high_risk_proposal_is_unsafe(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        proposal = factories.create_test_proposal(db, space_id=SPACE, run_id=run.id)
        proposal.risk_level = "critical"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.trajectory_status == "unsafe"

    def test_low_trust_artifact_is_unsafe(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        art = factories.create_test_artifact(db, space_id=SPACE, run_id=run.id)
        art.trust_level = "low"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.trajectory_status == "unsafe"

    def test_unsafe_trajectory_does_not_make_outcome_failed(self, db):
        """A run can be outcome_status=passed and trajectory_status=unsafe."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        proposal = factories.create_test_proposal(db, space_id=SPACE, run_id=run.id)
        proposal.risk_level = "high"
        db.flush()

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.outcome_status == "passed"
        assert result.trajectory_status == "unsafe"

    def test_adapter_started_running_without_completion_is_incomplete(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        actor = _actor(db, run)
        factories.create_test_run_step(
            db, run=run, actor_id=actor.id,
            step_type="adapter_started", status="running",
        )

        result = RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()

        assert result.trajectory_status == "incomplete"


# ---------------------------------------------------------------------------
# Hard invariants: evaluation never writes side-effect rows
# ---------------------------------------------------------------------------

class TestEvaluationInvariants:
    def test_evaluation_never_writes_memory_entry(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        before = db.query(MemoryEntry).count()
        RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()
        after = db.query(MemoryEntry).count()

        assert after == before

    def test_evaluation_never_writes_policy(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        before = db.query(Policy).count()
        RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()
        after = db.query(Policy).count()

        assert after == before

    def test_evaluation_never_creates_proposal(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "succeeded"
        db.flush()

        before = db.query(Proposal).count()
        RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()
        after = db.query(Proposal).count()

        assert after == before

    def test_evaluation_never_mutates_run_status(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.status = "failed"
        db.flush()

        RunEvaluationService(db).evaluate(run.id, space_id=SPACE)
        db.flush()
        db.refresh(run)

        assert run.status == "failed"  # unchanged


# ---------------------------------------------------------------------------
# Error-code collection unit tests
# ---------------------------------------------------------------------------

class TestCollectErrorCodes:
    def _mock_run(self, error_json=None, output_json=None, status="succeeded"):
        from unittest.mock import MagicMock
        run = MagicMock()
        run.error_json = error_json
        run.output_json = output_json
        run.status = status
        return run

    def test_collects_from_error_json_error_code(self):
        run = self._mock_run(error_json={"error_code": "sandbox_required"})
        codes = _collect_error_codes(run, [], [])
        assert "sandbox_required" in codes

    def test_collects_from_error_json_code(self):
        run = self._mock_run(error_json={"code": "runtime_removed"})
        codes = _collect_error_codes(run, [], [])
        assert "runtime_removed" in codes

    def test_does_not_parse_output_json_materialization_errors(self):
        """output_json.materialization_errors must never be parsed into error codes."""
        run = self._mock_run(output_json={"materialization_errors": ["code_patch_skipped_files"]})
        codes = _collect_error_codes(run, [], [])
        assert "code_patch_skipped_files" not in codes

    def test_collects_output_json_top_level_error_code(self):
        run = self._mock_run(output_json={"error_code": "adapter_runtime_error"})
        codes = _collect_error_codes(run, [], [])
        assert "adapter_runtime_error" in codes

    def test_deduplicates_codes(self):
        run = self._mock_run(
            error_json={"error_code": "adapter_runtime_error"},
            output_json={"error_code": "adapter_runtime_error"},
        )
        codes = _collect_error_codes(run, [], [])
        assert codes.count("adapter_runtime_error") == 1
