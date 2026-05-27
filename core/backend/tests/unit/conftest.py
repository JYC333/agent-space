"""Unit-test conftest: redirect SessionLocal to the test engine.

DurablePolicyAuditWriter opens its own session via ``from ..db import SessionLocal``
on each call. Without this fixture it would connect to the AGENT_SPACE_HOME database,
which is only initialised when a TestClient lifespan runs (i.e. in contract tests, not
unit tests).

This session-scoped autouse fixture replaces ``app.db.SessionLocal`` with a factory
bound to the same SQLite engine that the ``db`` fixture uses, so every
``DurablePolicyAuditWriter().write()`` call in unit tests lands on the already-migrated
test database.

The ``test_agent`` fixture is overridden here to commit after setup. The root conftest's
``test_agent`` only flushes, which holds a SQLite write lock for the test's duration and
prevents ``DurablePolicyAuditWriter`` from committing in its independent session.
Committing releases the lock. Because test IDs are ULIDs, accumulated agent rows across
tests do not cause unique-constraint collisions.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


@pytest.fixture(autouse=True)
def use_test_engine_for_durable_writer(db_engine):
    """Redirect app.db.SessionLocal to the in-process test engine for each unit test.

    Function-scoped (not session-scoped) to avoid bleeding into contract tests that run
    in the same pytest session but live outside tests/unit/.
    """
    TestSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    with patch("app.db.SessionLocal", TestSession):
        yield


@pytest.fixture
def test_agent(db, test_user, test_space):
    """Override: create agent and commit so no write lock blocks DurablePolicyAuditWriter."""
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
        name="fixture-agent",
    )
    db.commit()  # release write lock; DurablePolicyAuditWriter must commit independently
    return agent
