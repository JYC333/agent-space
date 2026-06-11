"""Workflow tests for RunStep execution replay spine (M3)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import RunStep
from app.runs.steps import list_run_steps
from app.runtimes.base import RuntimeAdapterResult
from tests.support import factories


@pytest.fixture(autouse=True)
def _stub_durable_policy_audit(monkeypatch):
    """Stub policy audit writes — this module covers run-step behavior."""
    monkeypatch.setattr(
        "app.policy.audit.DurablePolicyAuditWriter.write",
        lambda _writer, _envelope: "stub-policy-audit",
    )


def _setup_paths(monkeypatch, tmp_path, settings):
    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))


def _poison_run_step_flush(db, run):
    db.add(
        RunStep(
            id="00000000-0000-0000-0000-00000000dead",
            space_id=run.space_id,
            run_id=run.id,
            actor_id=None,
            step_index=999,
            step_type="failed",
            status="failed",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            metadata_json={},
        )
    )
    db.flush()


class _RaisingAdapter:
    def execute(self, ctx):
        raise RuntimeError("adapter exploded with sk-ant-1234567890abcdef")


class _FailingAdapter:
    def execute(self, ctx):
        now = datetime.now(UTC)
        return RuntimeAdapterResult(
            success=False,
            stdout="",
            stderr="",
            output_text="",
            exit_code=1,
            error_text="adapter failed with sk-ant-1234567890abcdef",
            error_code="adapter_failed",
            started_at=now,
            completed_at=now,
        )


class _AssertingNoTransactionAdapter:
    def __init__(self, db):
        self._db = db

    def execute(self, ctx):
        assert not self._db.in_transaction()
        now = datetime.now(UTC)
        return RuntimeAdapterResult(
            success=False,
            stdout="",
            stderr="",
            output_text="",
            exit_code=1,
            error_text="adapter failed",
            error_code="adapter_failed",
            started_at=now,
            completed_at=now,
        )


def test_successful_run_emits_coarse_step_sequence(db, cross_space_pair_db, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "hello-echo"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    steps = list_run_steps(db, run.id, a)
    assert len(steps) >= 4, f"Expected at least 4 coarse steps, got {len(steps)}: {[s.step_type for s in steps]}"

    step_types = [s.step_type for s in steps]
    assert "queued" in step_types
    assert "runtime_selected" in step_types
    assert "context_prepared" in step_types
    assert "adapter_started" in step_types
    assert "completed" in step_types

    for s in steps:
        assert s.actor_id is not None
        assert s.space_id == a
        assert s.run_id == run.id


def test_successful_run_steps_are_ordered_by_step_index(db, cross_space_pair_db, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "echo-test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)

    steps = list_run_steps(db, run.id, a)
    indexes = [s.step_index for s in steps]
    assert indexes == sorted(indexes), "Steps must be returned in step_index order"
    assert indexes[0] == 0


def test_failed_run_emits_failed_step(db, cross_space_pair_db, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "simulate-fail"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a, simulate_failure=True)
    db.expire_all()

    steps = list_run_steps(db, run.id, a)
    step_types = [s.step_type for s in steps]

    assert "queued" in step_types
    failed_steps = [s for s in steps if s.status == "failed"]
    assert len(failed_steps) >= 1, "Failed run must have at least one failed step"


def test_run_with_output_emits_artifact_step(db, cross_space_pair_db, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "hello-echo"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    steps = list_run_steps(db, run.id, a)
    step_types = [s.step_type for s in steps]
    assert "artifact_created" in step_types

    art_steps = [s for s in steps if s.step_type == "artifact_created"]
    for s in art_steps:
        assert s.artifact_id is not None


def test_all_run_steps_have_non_null_actor_id(db, cross_space_pair_db, tmp_path, monkeypatch):
    """Invariant: every RunStep written by execution must carry actor_id (M3 contract)."""
    from app.config import settings
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "actor-check"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)

    steps = db.query(RunStep).filter(RunStep.run_id == run.id).all()
    assert len(steps) > 0
    for s in steps:
        assert s.actor_id is not None, f"step {s.step_type!r} has null actor_id"


def test_job_triggered_run_uses_job_actor_not_default_user(db, cross_space_pair_db, tmp_path, monkeypatch):
    """Job-triggered runs must use job actor, not default_user_id."""
    from app.config import settings
    from app.models import Actor
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    # Simulate job-triggered: no instructed_by_user_id, trigger_origin=job
    run.instructed_by_user_id = None
    run.trigger_origin = "job"
    run.prompt = "job-actor-test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    steps = db.query(RunStep).filter(RunStep.run_id == run.id).all()
    assert len(steps) > 0
    for s in steps:
        actor = db.query(Actor).filter(Actor.id == s.actor_id).one()
        assert actor.actor_type == "job"
        assert actor.user_id is None
        assert actor.user_id != settings.default_user_id


def test_run_terminal_failure_survives_run_step_create_db_failure(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.config import settings
    import app.runs.execution as execution_mod
    import app.runs.steps as steps_mod
    from app.models import Run
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = test_space.id
    ua = test_user

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "create-step-failure"
    db.flush()
    db.commit()

    def broken_create_step(db_arg, *, run, **kwargs):
        _poison_run_step_flush(db_arg, run)

    monkeypatch.setattr(steps_mod, "create_step", broken_create_step)
    monkeypatch.setattr(execution_mod, "instantiate_runtime_adapter", lambda adapter_type: _RaisingAdapter())

    result = RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()
    row = db.query(Run).filter(Run.id == run.id).one()

    assert result.success is False
    assert row.status == "failed"
    assert "adapter exploded" in (row.error_message or "")
    assert "sk-ant-1234567890abcdef" not in (row.error_message or "")
    assert db.query(RunStep).filter(RunStep.run_id == run.id, RunStep.actor_id.is_(None)).count() == 0


def test_run_terminal_failure_survives_run_step_fail_db_failure(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.config import settings
    import app.runs.execution as execution_mod
    import app.runs.steps as steps_mod
    from app.models import Run
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = test_space.id
    ua = test_user

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "fail-step-failure"
    db.flush()
    db.commit()

    def broken_fail_step(db_arg, step, **kwargs):
        _poison_run_step_flush(db_arg, run)

    monkeypatch.setattr(steps_mod, "fail_step", broken_fail_step)
    monkeypatch.setattr(execution_mod, "instantiate_runtime_adapter", lambda adapter_type: _FailingAdapter())

    result = RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()
    row = db.query(Run).filter(Run.id == run.id).one()

    assert result.success is False
    assert row.status == "failed"
    assert "adapter failed" in (row.error_message or "")
    assert "sk-ant-1234567890abcdef" not in (row.error_message or "")
    assert db.query(RunStep).filter(RunStep.run_id == run.id, RunStep.actor_id.is_(None)).count() == 0


def test_runtime_adapter_executes_outside_open_db_transaction(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.config import settings
    import app.runs.execution as execution_mod
    from app.runs.execution import RunExecutionService

    _setup_paths(monkeypatch, tmp_path, settings)
    a = test_space.id
    ua = test_user

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "transaction-boundary"
    db.flush()
    db.commit()

    monkeypatch.setattr(
        execution_mod,
        "instantiate_runtime_adapter",
        lambda adapter_type: _AssertingNoTransactionAdapter(db),
    )

    result = RunExecutionService(db).execute_run(run.id, space_id=a)

    assert result.success is False
    assert result.error == "adapter failed"
