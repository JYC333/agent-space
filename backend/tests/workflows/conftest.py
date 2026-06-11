"""Workflow-test isolation for independent durable policy audit sessions."""
import uuid

from fastapi import Request
import pytest
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def use_test_engine_for_durable_writer(test_sessionlocal_patch):
    yield


@pytest.fixture
def workflow_app_db_override(db):
    """Route workflow HTTP requests to the test DB without app lifespan startup."""
    from app.db import get_db
    from app.main import app

    Session = sessionmaker(
        bind=db.get_bind(),
        autocommit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    def override_get_db(request: Request):
        session = Session()
        request.state.db = session
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


@pytest.fixture
def api_client(workflow_app_db_override):
    """Workflow HTTP client without FastAPI lifespan/background worker startup."""
    from app.main import app
    from starlette.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def cross_space_pair(db, cross_space_pair_db, workflow_app_db_override):
    """Authenticated workflow HTTP clients without app lifespan startup."""
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app
    from starlette.testclient import TestClient

    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]
    session_svc = UserSessionService(db)
    _, raw_a = session_svc.create(ua.id)
    _, raw_b = session_svc.create(ub.id)
    db.commit()

    client_a = TestClient(app, cookies={SESSION_COOKIE: raw_a}, raise_server_exceptions=True)
    client_b = TestClient(app, cookies={SESSION_COOKIE: raw_b}, raise_server_exceptions=True)
    try:
        yield {
            "space_a_id": a,
            "space_b_id": b,
            "user_a": ua,
            "user_b": ub,
            "client_a": client_a,
            "client_b": client_b,
        }
    finally:
        client_a.close()
        client_b.close()


@pytest.fixture
def same_space_pair(db, workflow_app_db_override):
    """Authenticated same-space workflow HTTP clients without app lifespan startup."""
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app
    from starlette.testclient import TestClient
    from tests.support import factories

    space = str(uuid.uuid4())
    factories.create_test_space(db, space_id=space, name="Shared Space", space_type="team")
    ua = factories.create_test_user(db, space_id=space, display_name="Owner A")
    ub = factories.create_test_user(db, space_id=space, display_name="Member B")
    session_svc = UserSessionService(db)
    _, raw_a = session_svc.create(ua.id)
    _, raw_b = session_svc.create(ub.id)
    db.commit()

    client_a = TestClient(app, cookies={SESSION_COOKIE: raw_a}, raise_server_exceptions=True)
    client_b = TestClient(app, cookies={SESSION_COOKIE: raw_b}, raise_server_exceptions=True)
    try:
        yield {
            "space_id": space,
            "user_a": ua,
            "user_b": ub,
            "client_a": client_a,
            "client_b": client_b,
        }
    finally:
        client_a.close()
        client_b.close()


@pytest.fixture
def workflow_http_pair(cross_space_pair):
    return cross_space_pair
