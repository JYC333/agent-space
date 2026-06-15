"""Pytest fixtures layered on ``tests/conftest.py`` (db / client remain source of truth).

Import via ``pytest_plugins`` from ``conftest.py`` — do not import ``tests.conftest``
from here (collection order / circular imports).
"""

from __future__ import annotations
import uuid

import pytest

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
def test_agent(db, test_user, test_space):
    return factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
        name="fixture-agent",
    )


@pytest.fixture
def test_model_provider(db, test_space):
    return factories.create_test_model_provider(db, space_id=test_space.id)


@pytest.fixture
def test_workspace(db, test_user, test_space):
    return factories.create_test_workspace(
        db,
        space_id=test_space.id,
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
def cross_space_pair_db(db):
    """Lightweight cross-space fixture: two spaces + users, no HTTP client.

    Use for pure-service tests that don't make HTTP requests. Avoids starting
    the FastAPI lifespan (and its background worker) on teardown.
    """
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    factories.create_test_space(db, space_id=a, name="Iso A", space_type="team")
    factories.create_test_space(db, space_id=b, name="Iso B", space_type="team")
    ua = factories.create_test_user(db, space_id=a, display_name="User A")
    ub = factories.create_test_user(db, space_id=b, display_name="User B")
    db.flush()
    return {
        "space_a_id": a,
        "space_b_id": b,
        "user_a": ua,
        "user_b": ub,
    }


@pytest.fixture
def cross_space_pair(db, app_db_override):
    """Two distinct spaces each with a user — for isolation / ACL tests.

    ``client_a`` and ``client_b`` are TestClient instances with session cookies
    pre-set for each space so tests can call them directly without per-request
    ``cookies=`` arguments (which starlette deprecated).
    """
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app as _app
    from starlette.testclient import TestClient

    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
    factories.create_test_space(db, space_id=a, name="Iso A", space_type="team")
    factories.create_test_space(db, space_id=b, name="Iso B", space_type="team")
    # create_test_user already inserts an active owner SpaceMembership for (space_id, user).
    ua = factories.create_test_user(db, space_id=a, display_name="User A")
    ub = factories.create_test_user(db, space_id=b, display_name="User B")
    session_svc = UserSessionService(db)
    _, raw_a = session_svc.create(ua.id)
    _, raw_b = session_svc.create(ub.id)
    # Must commit: TestClient runs in another thread with its own DB connection.
    db.commit()

    # Create per-identity clients with cookies set at construction time. Tests
    # do not need app lifespan/background worker startup; app_db_override wires
    # routes to the migrated test DB and a non-running queue service.
    with (
        TestClient(_app, cookies={SESSION_COOKIE: raw_a}, raise_server_exceptions=True) as client_a,
        TestClient(_app, cookies={SESSION_COOKIE: raw_b}, raise_server_exceptions=True) as client_b,
    ):
        yield {
            "space_a_id": a,
            "space_b_id": b,
            "user_a": ua,
            "user_b": ub,
            "cookies_a": {SESSION_COOKIE: raw_a},
            "cookies_b": {SESSION_COOKIE: raw_b},
            "client_a": client_a,
            "client_b": client_b,
        }


@pytest.fixture
def two_spaces(cross_space_pair):
    """Alias for ``cross_space_pair``."""
    return cross_space_pair


@pytest.fixture
def same_space_pair(db, app_db_override):
    """Two users in the same space — for intra-space visibility / mutation tests.

    Both users are active members of the same space. ``client_a`` is authenticated
    as user_a (typically the creator/owner), ``client_b`` as user_b (a second member
    who does not own objects created by user_a).
    """
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app as _app
    from starlette.testclient import TestClient

    space = str(uuid.uuid4())
    factories.create_test_space(db, space_id=space, name="Shared Space", space_type="team")
    ua = factories.create_test_user(db, space_id=space, display_name="Owner A")
    ub = factories.create_test_user(db, space_id=space, display_name="Member B")
    session_svc = UserSessionService(db)
    _, raw_a = session_svc.create(ua.id)
    _, raw_b = session_svc.create(ub.id)
    db.commit()

    with (
        TestClient(_app, cookies={SESSION_COOKIE: raw_a}, raise_server_exceptions=True) as client_a,
        TestClient(_app, cookies={SESSION_COOKIE: raw_b}, raise_server_exceptions=True) as client_b,
    ):
        yield {
            "space_id": space,
            "user_a": ua,
            "user_b": ub,
            "client_a": client_a,
            "client_b": client_b,
        }


@pytest.fixture
def api_client(client):
    """Alias for the FastAPI ``TestClient`` from root ``conftest``."""
    return client
