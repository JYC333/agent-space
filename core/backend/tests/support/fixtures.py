"""Pytest fixtures layered on ``tests/conftest.py`` (db / client remain source of truth).

Import via ``pytest_plugins`` from ``conftest.py`` — do not import ``tests.conftest``
from here (collection order / circular imports).
"""

from __future__ import annotations

import pytest
from ulid import ULID

from tests.support.fake_provider import DeterministicFakeProvider, FakeProviderConfig
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID
from tests.support import factories


@pytest.fixture
def test_space(db):
    """Default seeded space row (``personal``) — returns ORM object from DB."""
    from app.models import Space

    row = db.query(Space).filter(Space.id == PERSONAL_SPACE_ID).first()
    assert row is not None, "seed Space missing; check tests/conftest.py"
    return row


@pytest.fixture
def test_user(db):
    """Default seeded user (``default_user`` in ``personal``)."""
    from app.models import User

    row = db.query(User).filter(User.id == DEFAULT_USER_ID).first()
    assert row is not None, "seed User missing; check tests/conftest.py"
    return row


@pytest.fixture
def test_agent(db, test_user):
    return factories.create_test_agent(
        db,
        space_id=test_user.space_id,
        owner_user_id=test_user.id,
        name="fixture-agent",
    )


@pytest.fixture
def test_model_provider(db, test_space):
    return factories.create_test_model_provider(db, space_id=test_space.id)


@pytest.fixture
def test_runtime_adapter(db, test_space):
    return factories.create_test_runtime_adapter(db, space_id=test_space.id)


@pytest.fixture
def test_workspace(db, test_user):
    return factories.create_test_workspace(
        db,
        space_id=test_user.space_id,
        created_by_user_id=test_user.id,
        name="fixture-workspace",
    )


@pytest.fixture
def fake_runtime():
    return ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig())


@pytest.fixture
def fake_provider():
    return DeterministicFakeProvider(FakeProviderConfig())


@pytest.fixture
def cross_space_pair(db):
    """Two distinct spaces each with a user — for isolation / ACL tests."""
    a = str(ULID())
    b = str(ULID())
    factories.create_test_space(db, space_id=a, name="Iso A", space_type="team")
    factories.create_test_space(db, space_id=b, name="Iso B", space_type="team")
    ua = factories.create_test_user(db, space_id=a, display_name="User A")
    ub = factories.create_test_user(db, space_id=b, display_name="User B")
    # Must commit: TestClient runs in another thread with its own DB connection.
    # An open write transaction here would block inserts (sqlite "database is locked").
    db.commit()
    return {
        "space_a_id": a,
        "space_b_id": b,
        "user_a": ua,
        "user_b": ub,
    }


@pytest.fixture
def two_spaces(cross_space_pair):
    """Alias for ``cross_space_pair``."""
    return cross_space_pair


@pytest.fixture
def api_client(client):
    """Alias for the FastAPI ``TestClient`` from root ``conftest``."""
    return client
