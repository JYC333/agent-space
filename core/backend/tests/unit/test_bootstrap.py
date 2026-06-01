"""Fresh-instance bootstrap tests (empty PostgreSQL -> usable initial state).

These run against the committed test engine. The DB is truncated to a truly
empty state first, then ``bootstrap_instance`` is exercised directly. The
``db_engine_isolated`` fixture TRUNCATEs + reseeds on teardown, so these tests
never leak rows into others.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.bootstrap import bootstrap_instance
from app.db import Base
from app.models import ExecutionPlane, Space, SpaceMembership, User

SPACE_ID = "personal"
USER_ID = "default_user"


def _truncate_all(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as s:
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        s.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        s.commit()


@pytest.fixture()
def empty_engine(db_engine_isolated):
    """Committed engine truncated to a completely empty state (no seeded rows)."""
    _truncate_all(db_engine_isolated)
    return db_engine_isolated


def test_bootstrap_creates_usable_initial_state(empty_engine):
    Session = sessionmaker(bind=empty_engine)
    with Session() as db:
        created = bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)

    assert created == {
        "space": True,
        "user": True,
        "membership": True,
        "execution_planes": True,
    }

    with Session() as db:
        space = db.query(Space).filter(Space.id == SPACE_ID).one()
        assert space.type == "personal"
        user = db.query(User).filter(User.id == USER_ID).one()
        assert user.status == "active"
        ms = (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == SPACE_ID, SpaceMembership.user_id == USER_ID)
            .one()
        )
        assert ms.role == "owner"
        assert ms.status == "active"
        plane_count = db.query(ExecutionPlane).filter(ExecutionPlane.space_id == SPACE_ID).count()
        assert plane_count > 0


def test_bootstrap_is_idempotent(empty_engine):
    Session = sessionmaker(bind=empty_engine)
    with Session() as db:
        bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)

    # Second run must not create or duplicate anything.
    with Session() as db:
        created = bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)
    assert created == {
        "space": False,
        "user": False,
        "membership": False,
        # Second run inserts nothing: the summary must accurately report that no
        # execution-plane rows were created (and must not duplicate rows below).
        "execution_planes": False,
    }

    with Session() as db:
        assert db.query(Space).filter(Space.id == SPACE_ID).count() == 1
        assert db.query(User).filter(User.id == USER_ID).count() == 1
        assert (
            db.query(SpaceMembership)
            .filter(SpaceMembership.space_id == SPACE_ID, SpaceMembership.user_id == USER_ID)
            .count()
            == 1
        )
        planes_first = db.query(ExecutionPlane).filter(ExecutionPlane.space_id == SPACE_ID).count()

    # Run a third time; plane count stays stable (no duplicates).
    with Session() as db:
        bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)
    with Session() as db:
        planes_again = db.query(ExecutionPlane).filter(ExecutionPlane.space_id == SPACE_ID).count()
    assert planes_again == planes_first


def test_bootstrap_summary_reports_execution_planes_only_when_rows_inserted(empty_engine):
    """The summary's execution_planes flag must reflect real inserts, not invocation.

    First bootstrap on an empty DB inserts the default planes -> True.
    A second bootstrap inserts nothing -> False (accurate, not "always True").
    """
    Session = sessionmaker(bind=empty_engine)
    with Session() as db:
        first = bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)
    assert first["execution_planes"] is True

    with Session() as db:
        second = bootstrap_instance(db, space_id=SPACE_ID, user_id=USER_ID)
    assert second["execution_planes"] is False, (
        "execution_planes must be False when no plane rows were inserted"
    )


def test_bootstrap_can_skip_execution_planes(empty_engine):
    Session = sessionmaker(bind=empty_engine)
    with Session() as db:
        created = bootstrap_instance(
            db, space_id=SPACE_ID, user_id=USER_ID, seed_execution_planes=False
        )
    assert created["execution_planes"] is False
    with Session() as db:
        assert db.query(ExecutionPlane).filter(ExecutionPlane.space_id == SPACE_ID).count() == 0
