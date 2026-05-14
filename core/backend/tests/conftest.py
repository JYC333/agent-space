"""Pytest root conftest: DB fixtures + **AGENT_SPACE_HOME isolation** for app imports.

``app.config`` / ``app.db`` resolve ``AGENT_SPACE_HOME`` at import time. Before any
``from app…`` import, we point ``AGENT_SPACE_HOME`` at an ephemeral directory so
``TestClient`` lifespan ``init_db()`` never migrates the developer's real
``~/aspace/dev`` (or stale ``~/aspace``) SQLite. That directory is **not**
``~/aspace/test`` (reserved for human ``./scripts/start.sh --test`` stacks).

Escape hatch (integration / debugging against a real tree)::

    AGENT_SPACE_PYTEST_USE_REAL_HOME=1 pytest …

Keep the isolated tree after the run for inspection::

    AGENT_SPACE_PYTEST_KEEP_HOME=1 pytest …

Override where ephemeral session dirs are created::

    PYTEST_AGENT_SPACE_PARENT=/path/to/parent pytest …

Host tree root (defaults to ``~/aspace`` — the directory that contains ``dev/``,
``test/``, ``prod/`` mode dirs; pytest uses ``<ASPACE_ROOT>/.cache/pytest-runs/``,
not ``~/aspace/test``)::

    ASPACE_ROOT=/data/aspace pytest …
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_SESSION_HOME: Path | None = None


def _aspace_host_root() -> Path:
    """Local Agent Space data parent (mode trees live under ``dev/``, ``test/``, …).

    Ephemeral pytest dirs stay under ``<root>/.cache/`` only — never a freestanding
    ``~/.cache/...`` tree outside this host root.
    """
    raw = os.environ.get("ASPACE_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "aspace").expanduser().resolve()


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


_configure_agent_space_home_for_pytest()

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config

from app.db import get_db
from app.main import app
from app.models import Space, User
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
SPACE = PERSONAL_SPACE_ID
USER = DEFAULT_USER_ID

pytest_plugins = ("tests.support.fixtures",)


def _migrate_test_database(database_url: str) -> None:
    """Upgrade test DB; paths are absolute so ``pytest`` works from any cwd."""
    migrations_dir = BACKEND_ROOT / "migrations"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="function")
def db_engine(tmp_path):
    db_path = tmp_path / "test.sqlite"
    database_url = f"sqlite:///{db_path}"
    _migrate_test_database(database_url)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add(Space(id=SPACE, name="Personal"))
        session.add(
            User(
                id=USER,
                space_id=SPACE,
                email="default@example.com",
                display_name="Default User",
            )
        )
        session.commit()
    finally:
        session.close()

    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_engine):
    Session = sessionmaker(bind=db_engine)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
