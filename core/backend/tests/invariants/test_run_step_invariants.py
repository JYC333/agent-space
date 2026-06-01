"""Invariant tests for RunStep execution replay spine (M3)."""
from __future__ import annotations
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import RunStep
from tests.support import factories


def test_run_step_actor_id_is_required(db, test_user, test_space, test_agent):
    """RunStep.actor_id must not be nullable at the ORM level."""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(RunStep)
    col = mapper.columns["actor_id"]
    assert not col.nullable, "RunStep.actor_id must be NOT NULL"


def test_run_step_space_id_is_required(db, test_user, test_space, test_agent):
    """RunStep.space_id must not be nullable."""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(RunStep)
    col = mapper.columns["space_id"]
    assert not col.nullable, "RunStep.space_id must be NOT NULL"


def test_run_step_run_id_is_required(db, test_user, test_space, test_agent):
    """RunStep.run_id must not be nullable."""
    from sqlalchemy import inspect as sa_inspect
    mapper = sa_inspect(RunStep)
    col = mapper.columns["run_id"]
    assert not col.nullable, "RunStep.run_id must be NOT NULL"


def test_factory_creates_valid_step(db, test_user, test_space, test_agent):
    from app.actors.service import get_or_create_user_actor
    from tests.support.factories import create_test_run, create_test_run_step

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
    step = create_test_run_step(db, run=run, actor_id=actor.id)

    db.flush()
    assert step.id is not None
    assert step.actor_id == actor.id
    assert step.run_id == run.id
    assert step.space_id == run.space_id


def test_metadata_sanitized_on_write(db, test_user, test_space, test_agent):
    """RunStep.metadata_json must not persist raw secrets."""
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import create_step
    from tests.support.factories import create_test_run

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

    step = create_step(
        db, run=run, actor_id=actor.id,
        step_type="adapter_started", status="running",
        metadata_json={"api_key": "sk-realkey123456789", "info": "safe"},
    )
    db.flush()

    assert step.metadata_json["api_key"] == "[REDACTED]"
    assert step.metadata_json["info"] == "safe"


def test_error_message_sanitized_on_fail(db, test_user, test_space, test_agent):
    """RunStep.error_message must not persist raw API keys or secrets."""
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import create_step, fail_step
    from tests.support.factories import create_test_run

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

    step = create_step(db, run=run, actor_id=actor.id, step_type="adapter_started", status="running")
    fail_step(db, step, error_message="failed with sk-abc123def456ghi in the header")
    db.flush()

    assert "sk-abc123def456ghi" not in (step.error_message or "")
    assert "[REDACTED]" in (step.error_message or "")


def test_step_index_is_monotonic_per_run(db, test_user, test_space, test_agent):
    """step_index must be monotonically increasing within a run."""
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import create_step
    from tests.support.factories import create_test_run

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

    steps = [
        create_step(db, run=run, actor_id=actor.id, step_type=t, status="succeeded")
        for t in ("queued", "context_prepared", "runtime_selected", "completed")
    ]

    indexes = [s.step_index for s in steps]
    assert indexes == list(range(len(steps))), "step_index must be 0-based monotonic"


def test_run_step_duplicate_run_id_step_index_rejected_by_db(db, test_user, test_space, test_agent):
    from app.actors.service import get_or_create_user_actor
    from tests.support.factories import create_test_run, create_test_run_step

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
    create_test_run_step(db, run=run, actor_id=actor.id, step_index=0)
    db.flush()
    with pytest.raises(IntegrityError):
        create_test_run_step(db, run=run, actor_id=actor.id, step_index=0)
    db.rollback()


def test_list_run_steps_returns_stable_step_index_order(db, test_user, test_space, test_agent):
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import list_run_steps
    from tests.support.factories import create_test_run, create_test_run_step

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
    create_test_run_step(db, run=run, actor_id=actor.id, step_index=2, step_type="completed")
    create_test_run_step(db, run=run, actor_id=actor.id, step_index=0, step_type="queued")
    create_test_run_step(db, run=run, actor_id=actor.id, step_index=1, step_type="context_prepared")
    db.flush()

    assert [s.step_index for s in list_run_steps(db, run.id, test_space.id)] == [0, 1, 2]


def test_run_step_duplicate_conflict_does_not_corrupt_terminal_run_state(
    db, test_user, test_space, test_agent, monkeypatch
):
    from app.actors.service import get_or_create_user_actor
    from app.db_uow import UnitOfWork
    from app.runs import steps as steps_mod
    from app.runs.steps import create_step
    from tests.support.factories import create_test_run, create_test_run_step

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
    create_test_run_step(db, run=run, actor_id=actor.id, step_index=0)
    db.flush()

    monkeypatch.setattr(steps_mod, "_next_step_index", lambda _db, _run_id: 0)
    try:
        with UnitOfWork(db).savepoint():
            create_step(db, run=run, actor_id=actor.id, step_type="completed", status="succeeded")
    except Exception:
        pass

    run.status = "failed"
    db.add(run)
    UnitOfWork(db).commit()
    db.refresh(run)

    assert run.status == "failed"
    assert db.query(RunStep).filter(RunStep.run_id == run.id).count() == 1


def test_step_index_independent_across_runs(db, test_user, test_space, test_agent):
    """step_index resets to 0 for each run independently."""
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import create_step
    from tests.support.factories import create_test_run

    actor = get_or_create_user_actor(db, test_user, test_space.id)
    run_a = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)
    run_b = create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=test_agent)

    s_a0 = create_step(db, run=run_a, actor_id=actor.id, step_type="queued", status="succeeded")
    s_a1 = create_step(db, run=run_a, actor_id=actor.id, step_type="completed", status="succeeded")
    s_b0 = create_step(db, run=run_b, actor_id=actor.id, step_type="queued", status="succeeded")

    assert s_a0.step_index == 0
    assert s_a1.step_index == 1
    assert s_b0.step_index == 0, "Each run starts at step_index=0 independently"


def test_steps_space_scoped_query(db):
    """list_run_steps only returns steps for the correct space."""
    from app.actors.service import get_or_create_user_actor
    from app.runs.steps import create_step, list_run_steps
    from tests.support.factories import create_test_run

    space_a = factories.create_test_space(db, space_id=str(uuid.uuid4()), name="RunStep A", space_type="team")
    space_b = factories.create_test_space(db, space_id=str(uuid.uuid4()), name="RunStep B", space_type="team")
    ua = factories.create_test_user(db, space_id=space_a.id, display_name="RunStep User A")
    ub = factories.create_test_user(db, space_id=space_b.id, display_name="RunStep User B")
    a = space_a.id
    b = space_b.id

    actor_a = get_or_create_user_actor(db, ua, a)
    actor_b = get_or_create_user_actor(db, ub, b)

    agent_a = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id)
    agent_b = factories.create_test_agent(db, space_id=b, owner_user_id=ub.id)

    run_a = create_test_run(db, space_id=a, user_id=ua.id, agent=agent_a)
    run_b = create_test_run(db, space_id=b, user_id=ub.id, agent=agent_b)

    create_step(db, run=run_a, actor_id=actor_a.id, step_type="queued", status="succeeded")
    create_step(db, run=run_b, actor_id=actor_b.id, step_type="queued", status="succeeded")
    db.flush()

    steps_a = list_run_steps(db, run_a.id, a)
    steps_b = list_run_steps(db, run_b.id, b)

    assert all(s.space_id == a for s in steps_a)
    assert all(s.space_id == b for s in steps_b)
    assert len(steps_a) == 1
    assert len(steps_b) == 1
