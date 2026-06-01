"""Unit-test conftest: redirect SessionLocal to the test DB lazily.

DurablePolicyAuditWriter opens its own session via ``from ..db import SessionLocal``
on each call. Without this fixture it would connect to the AGENT_SPACE_HOME database,
which is only initialised when a TestClient lifespan runs (i.e. in contract tests, not
unit tests).

This autouse fixture replaces ``app.db.SessionLocal`` through the root
``test_sessionlocal_patch`` fixture.  The patch is lazy, so pure unit tests do
not start Postgres just because this conftest is loaded.

The ``test_agent`` fixture is overridden here to commit after setup so the agent row
is visible to any independent sessions opened by service code under test.
"""
from __future__ import annotations

import pytest

from tests.support import factories


@pytest.fixture(autouse=True)
def use_test_engine_for_durable_writer(test_sessionlocal_patch):
    """Redirect app.db.SessionLocal without eagerly requesting db_engine."""
    yield


@pytest.fixture
def test_agent(db, test_user, test_space):
    """Override: create agent and commit so the row is visible to independent sessions."""
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
        name="fixture-agent",
    )
    db.commit()
    return agent
