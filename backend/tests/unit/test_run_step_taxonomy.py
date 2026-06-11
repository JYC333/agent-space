"""Unit tests for RunStep taxonomy: step types, statuses, and service validation."""
from __future__ import annotations

import pytest

from app.schemas import RUN_STEP_STATUSES, RUN_STEP_TYPES


class TestStepTypeTaxonomy:
    def test_required_types_present(self):
        required = {
            "run_created", "queued", "context_prepared", "runtime_selected",
            "adapter_started", "adapter_completed", "artifact_created",
            "proposal_created", "failed", "completed",
            "validation_started", "validation_completed", "cancelled",
        }
        assert required <= RUN_STEP_TYPES

    def test_types_is_frozenset(self):
        assert isinstance(RUN_STEP_TYPES, frozenset)

    def test_statuses_is_frozenset(self):
        assert isinstance(RUN_STEP_STATUSES, frozenset)

    def test_required_statuses_present(self):
        required = {"pending", "running", "succeeded", "failed", "skipped", "cancelled"}
        assert required <= RUN_STEP_STATUSES


class TestStepServiceValidation:
    def test_validate_step_type_rejects_unknown(self):
        from app.runs.steps import _validate_step_type
        with pytest.raises(ValueError, match="invalid step_type"):
            _validate_step_type("unknown_type")

    def test_validate_step_type_accepts_all_known(self):
        from app.runs.steps import _validate_step_type
        for t in RUN_STEP_TYPES:
            _validate_step_type(t)

    def test_validate_status_rejects_unknown(self):
        from app.runs.steps import _validate_status
        with pytest.raises(ValueError, match="invalid status"):
            _validate_status("not_a_status")

    def test_validate_status_accepts_all_known(self):
        from app.runs.steps import _validate_status
        for s in RUN_STEP_STATUSES:
            _validate_status(s)


class TestCreateStep:
    def test_create_step_persists_row(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.models import RunStep
        from app.runs.steps import create_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        step = create_step(
            db,
            run=run,
            actor_id=actor.id,
            step_type="queued",
            status="succeeded",
            title="Test step",
        )
        db.flush()
        assert step.id is not None
        assert step.run_id == run.id
        assert step.space_id == run.space_id
        assert step.actor_id == actor.id
        assert step.step_type == "queued"
        assert step.status == "succeeded"
        assert step.step_index == 0

    def test_step_index_increments(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        s0 = create_step(db, run=run, actor_id=actor.id, step_type="queued", status="succeeded")
        s1 = create_step(db, run=run, actor_id=actor.id, step_type="context_prepared", status="succeeded")
        s2 = create_step(db, run=run, actor_id=actor.id, step_type="completed", status="succeeded")

        assert s0.step_index == 0
        assert s1.step_index == 1
        assert s2.step_index == 2

    def test_create_step_rejects_invalid_type(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        with pytest.raises(ValueError, match="invalid step_type"):
            create_step(db, run=run, actor_id=actor.id, step_type="bad_type", status="succeeded")

    def test_create_step_rejects_invalid_status(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        with pytest.raises(ValueError, match="invalid status"):
            create_step(db, run=run, actor_id=actor.id, step_type="queued", status="bad_status")


class TestStepLifecycle:
    def test_start_step_transitions_to_running(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step, start_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        step = create_step(db, run=run, actor_id=actor.id, step_type="adapter_started", status="pending")
        start_step(db, step)

        assert step.status == "running"
        assert step.started_at is not None

    def test_complete_step_transitions_to_succeeded(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step, complete_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        step = create_step(db, run=run, actor_id=actor.id, step_type="adapter_started", status="running")
        complete_step(db, step, output_summary="done")

        assert step.status == "succeeded"
        assert step.ended_at is not None
        assert step.output_summary == "done"

    def test_fail_step_transitions_to_failed(self, db, test_user, test_space, test_agent):
        from app.actors.service import get_or_create_user_actor
        from app.runs.steps import create_step, fail_step
        from tests.support.factories import create_test_run

        actor = get_or_create_user_actor(db, test_user, test_space.id)
        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

        step = create_step(db, run=run, actor_id=actor.id, step_type="adapter_started", status="running")
        fail_step(db, step, error_type="timeout", error_message="took too long")

        assert step.status == "failed"
        assert step.ended_at is not None
        assert step.error_type == "timeout"
        assert step.error_message == "took too long"


class TestResolveRunActor:
    def test_user_run_resolves_user_actor(self, db, test_user, test_space, test_agent):
        from app.runs.steps import resolve_run_actor
        from tests.support.factories import create_test_run

        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
        actor = resolve_run_actor(db, run)

        assert actor.actor_type == "user"
        assert actor.user_id == test_user.id

    def test_no_user_no_agent_resolves_system_actor(self, db, test_user, test_space, test_agent):
        from app.runs.steps import resolve_run_actor
        from tests.support.factories import create_test_run

        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
        run.instructed_by_user_id = None
        db.flush()
        actor = resolve_run_actor(db, run)

        assert actor.actor_type == "system"
        assert actor.user_id is None

    def test_job_triggered_run_resolves_job_actor(self, db, test_user, test_space, test_agent):
        from app.runs.steps import resolve_run_actor
        from tests.support.factories import create_test_run

        run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
        run.instructed_by_user_id = None
        run.trigger_origin = "job"
        db.flush()
        actor = resolve_run_actor(db, run)

        assert actor.actor_type == "job"
        assert actor.user_id is None
