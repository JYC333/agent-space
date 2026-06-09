"""Pytest root conftest: DB fixtures + **AGENT_SPACE_HOME isolation** for app imports.

``app.config`` / ``app.db`` resolve ``AGENT_SPACE_HOME`` at import time. Before any
``from app…`` import, we point ``AGENT_SPACE_HOME`` at an ephemeral directory so
``TestClient`` lifespan ``init_db()`` never touches the developer's real
``~/.aspace/dev``. That directory is **not** ``~/.aspace/test`` (reserved for
human ``./scripts/start.sh --test`` stacks).

Escape hatch (integration / debugging against a real tree)::

    AGENT_SPACE_PYTEST_USE_REAL_HOME=1 pytest …

Keep the isolated tree after the run for inspection::

    AGENT_SPACE_PYTEST_KEEP_HOME=1 pytest …

Override where ephemeral session dirs are created::

    PYTEST_AGENT_SPACE_PARENT=/path/to/parent pytest …

**PostgreSQL via testcontainers — isolation strategy:**

- ``pg_container`` is **session-scoped**: one PostgreSQL container per pytest session.
  The container runs with ``fsync=off`` and ``synchronous_commit=off`` (safe for tests).
- ``db_engine`` is session-scoped: one Alembic upgrade per session.
- Normal DB and HTTP tests share a connection-level transaction and roll it back on
  teardown.  Engine-direct tests that really need committed cross-connection state
  opt in to ``db_engine_isolated``.

Host tree root (defaults to ``~/.aspace`` — the directory that contains ``dev/``,
``test/``, ``prod/`` mode dirs; pytest uses ``<ASPACE_ROOT>/.cache/pytest-runs/``,
not ``~/.aspace/test``)::

    ASPACE_ROOT=/data/aspace pytest …
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

_SESSION_HOME: Path | None = None


def _aspace_host_root() -> Path:
    raw = os.environ.get("ASPACE_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".aspace").expanduser().resolve()


def _default_pytest_parent() -> Path:
    return _aspace_host_root() / ".cache" / "pytest-runs"


def _configure_agent_space_home_for_pytest() -> None:
    global _SESSION_HOME
    if os.environ.get("AGENT_SPACE_PYTEST_USE_REAL_HOME", "").lower() in ("1", "true", "yes"):
        return
    raw_parent = os.environ.get("PYTEST_AGENT_SPACE_PARENT")
    parent = (
        Path(raw_parent).expanduser().resolve()
        if raw_parent
        else _default_pytest_parent()
    )
    parent.mkdir(parents=True, exist_ok=True)
    _SESSION_HOME = Path(tempfile.mkdtemp(prefix="pytest-session-", dir=str(parent))).resolve()
    os.environ["AGENT_SPACE_HOME"] = str(_SESSION_HOME)

    def _cleanup() -> None:
        if os.environ.get("AGENT_SPACE_PYTEST_KEEP_HOME", "").lower() in ("1", "true", "yes"):
            return
        if _SESSION_HOME is not None:
            shutil.rmtree(_SESSION_HOME, ignore_errors=True)

    atexit.register(_cleanup)


def _configure_settings_env_for_pytest() -> None:
    raw_debug = os.environ.get("DEBUG")
    if raw_debug is None:
        return
    if raw_debug.strip().lower() not in {
        "1",
        "true",
        "t",
        "yes",
        "y",
        "on",
        "0",
        "false",
        "f",
        "no",
        "n",
        "off",
    }:
        os.environ["DEBUG"] = "false"


_configure_agent_space_home_for_pytest()
_configure_settings_env_for_pytest()

import pytest
import anyio.to_thread
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi import Request
import fastapi.testclient as _fastapi_testclient
import starlette.testclient as _starlette_testclient
from alembic import command
from alembic.config import Config


async def _inline_anyio_run_sync(func, *args, **kwargs):
    kwargs.pop("abandon_on_cancel", None)
    kwargs.pop("cancellable", None)
    kwargs.pop("limiter", None)
    return func(*args)


anyio.to_thread.run_sync = _inline_anyio_run_sync

from app.db import get_db
from app.knowledge.seeder import seed_default_note_collections
from app.main import app
from app.models import Space, SpaceMembership, User
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID
from tests.support.http_client import SyncASGITestClient as TestClient

_fastapi_testclient.TestClient = TestClient
_starlette_testclient.TestClient = TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
SPACE = PERSONAL_SPACE_ID
USER = DEFAULT_USER_ID

pytest_plugins = ("tests.support.fixtures",)


def _postgres_major_from_env_example() -> str:
    env_example = REPO_ROOT / "deployments" / "local" / ".env.dev.example"
    for line in env_example.read_text().splitlines():
        if line.startswith("POSTGRES_MAJOR="):
            major = line.split("=", 1)[1].strip()
            if major.isdigit():
                return major
            break
    raise RuntimeError("deployments/local/.env.dev.example must declare POSTGRES_MAJOR=<major>")


POSTGRES_MAJOR = _postgres_major_from_env_example()


def _migrate_test_database(database_url: str) -> None:
    """Upgrade test DB; paths are absolute so ``pytest`` works from any cwd."""
    migrations_dir = BACKEND_ROOT / "migrations"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _seed_defaults(session) -> None:
    """Insert the three default rows every test expects to find."""
    session.add(Space(id=SPACE, name="Personal"))
    session.add(User(id=USER, email="default@example.com", display_name="Default User"))
    session.add(SpaceMembership(
        id="default_membership",
        space_id=SPACE,
        user_id=USER,
        role="owner",
        status="active",
    ))
    seed_default_note_collections(session, SPACE)
    session.commit()


def _truncate_all(engine) -> None:
    """TRUNCATE every table and restart sequences for committed-engine tests."""
    from app.db import Base
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        session.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
        session.commit()
    finally:
        session.close()


def _delete_policy_decision_records(engine) -> None:
    """Clean independently committed durable audit rows between HTTP tests."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.execute(text("DELETE FROM policy_decision_records"))
        session.commit()
    finally:
        session.close()


@pytest.fixture(scope="session")
def pg_container():
    """Session-scoped PostgreSQL container via testcontainers.

    ``fsync=off`` and ``synchronous_commit=off`` remove disk-flush overhead that
    is irrelevant in a throwaway test container.
    """
    from testcontainers.postgres import PostgresContainer
    pg = PostgresContainer(f"postgres:{POSTGRES_MAJOR}").with_command(
        "postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off"
    )
    with pg:
        yield pg


@pytest.fixture(scope="session")
def db_engine(pg_container):
    database_url = pg_container.get_connection_url(driver="psycopg")
    _migrate_test_database(database_url)
    engine = create_engine(
        database_url,
        connect_args={"options": "-c synchronous_commit=off"},
    )

    Session = sessionmaker(bind=engine)
    import app.db as app_db

    previous_engine = app_db.engine
    previous_session_local = app_db.SessionLocal
    app_db.engine = engine
    app_db.SessionLocal = Session

    try:
        yield engine
    finally:
        app_db.engine = previous_engine
        app_db.SessionLocal = previous_session_local
        engine.dispose()


@pytest.fixture(scope="function")
def db_engine_isolated(db_engine):
    """Real committed DB isolation for tests that intentionally bypass ``db``.

    Most tests should use ``db`` so teardown can be a cheap rollback.  This
    fixture is for cases such as queue concurrency tests where the code under
    test must open multiple independent sessions against the engine.
    """
    _truncate_all(db_engine)
    session = sessionmaker(bind=db_engine)()
    try:
        _seed_defaults(session)
    finally:
        session.close()

    try:
        yield db_engine
    finally:
        _truncate_all(db_engine)


@pytest.fixture(scope="function")
def queue_service(db_engine_isolated):
    """Dedicated queue fixture.

    Returns a ``PostgresQueueService`` bound to the committed test engine, with
    TRUNCATE + reseed before and after each test (inherited from
    ``db_engine_isolated``).  Queue code opens its own independent sessions and
    commits across them, so it needs committed cross-session state rather than
    the rollback-only ``db`` fixture.  Using this fixture keeps every queue test
    isolated from committed rows left by any other test.
    """
    from app.jobs.queue import PostgresQueueService
    Session = sessionmaker(bind=db_engine_isolated)
    return PostgresQueueService(Session)


@pytest.fixture(scope="function")
def db(db_engine):
    """Function-scoped database session.

    Opens a fresh connection, wraps the entire test in a connection-level
    transaction, seeds default rows inside it, and rolls back on teardown.
    HTTP tests bind request sessions to this same connection via
    ``app_db_override``.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )()
    _seed_defaults(session)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def test_sessionlocal_patch(request):
    """Patch app.db.SessionLocal without forcing Postgres into pure-logic tests.

    Most services that need an independent session do so through ``SessionLocal``.
    If a test already uses ``db``, bind those independent sessions to the same
    connection-level transaction so all writes roll back together and fresh
    sessions can see uncommitted test setup.  If a test does not use ``db`` but
    calls ``SessionLocal`` directly, lazily create the same rollback-style
    transaction instead of falling back to TRUNCATE.

    Wired in via the autouse ``use_test_engine_for_durable_writer`` fixture in
    ``tests/unit/conftest.py`` so durable-writer service code under unit tests
    never connects to a real AGENT_SPACE_HOME database.
    """
    from unittest.mock import patch

    factories = {}
    local_connection = None
    local_transaction = None

    def _factory_for(bind):
        key = id(bind)
        factory = factories.get(key)
        if factory is None:
            factory = sessionmaker(
                bind=bind,
                autocommit=False,
                autoflush=False,
                join_transaction_mode="create_savepoint",
            )
            factories[key] = factory
        return factory

    def _local_transaction_bind():
        nonlocal local_connection, local_transaction
        if local_connection is None:
            engine = request.getfixturevalue("db_engine")
            local_connection = engine.connect()
            local_transaction = local_connection.begin()
            seed_session = sessionmaker(
                bind=local_connection,
                join_transaction_mode="create_savepoint",
            )()
            try:
                _seed_defaults(seed_session)
            finally:
                seed_session.close()

            def _cleanup():
                if local_transaction is not None:
                    local_transaction.rollback()
                if local_connection is not None:
                    local_connection.close()

            request.addfinalizer(_cleanup)
        return local_connection

    def _session_local(*args, **kwargs):
        if "db" in request.fixturenames:
            bind = request.getfixturevalue("db").get_bind()
        else:
            bind = _local_transaction_bind()
        return _factory_for(bind)(*args, **kwargs)

    with patch("app.db.SessionLocal", _session_local):
        yield


@pytest.fixture(scope="function")
def app_db_override(request, db, db_engine):
    durable_audit = request.node.get_closest_marker("durable_audit") is not None
    Session = sessionmaker(
        bind=db.get_bind(),
        autocommit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    EngineSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db(request: Request):
        session = Session()
        request.state.db = session
        try:
            yield session
        finally:
            session.close()

    from app.jobs.queue import PostgresQueueService, init_queue
    import app.db as app_db

    @asynccontextmanager
    async def test_lifespan(_app):
        yield

    previous_lifespan = app.router.lifespan_context
    previous_session_local = app_db.SessionLocal
    if durable_audit:
        _delete_policy_decision_records(db_engine)
    app.dependency_overrides[get_db] = override_get_db
    app.router.lifespan_context = test_lifespan
    app_db.SessionLocal = EngineSession if durable_audit else Session
    init_queue(PostgresQueueService(Session))
    try:
        yield
    finally:
        if durable_audit:
            _delete_policy_decision_records(db_engine)
        app_db.SessionLocal = previous_session_local
        app.router.lifespan_context = previous_lifespan
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def client(app_db_override):
    """FastAPI client for tests without app lifespan/background worker startup."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
