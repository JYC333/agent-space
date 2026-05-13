import logging

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
from pathlib import Path

from app.db import get_db
from app.main import app
from app.models import Space, User, Workspace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
SPACE = "personal"
USER = "default_user"


@pytest.fixture(autouse=True)
def _reactivate_app_hooks_logger():
    """Starlette/FastAPI TestClient lifespan can call logging.shutdown(), which disables loggers.

    Post-run hook tests use caplog on ``app.agents.hooks``; re-enable that logger each test.
    """
    logging.getLogger("app.agents.hooks").disabled = False
    yield


def _migrate_test_database(database_url: str) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="function")
def db_engine(tmp_path):
    db_path = tmp_path / "test.sqlite"
    database_url = f"sqlite:///{db_path}"
    _migrate_test_database(database_url)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        session.add(Space(id=SPACE, name="Personal"))
        session.add(User(id=USER, space_id=SPACE, email="default@example.com", display_name="Default User"))
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


def ensure_space(db, space_id: str, name: str | None = None) -> None:
    """Insert a Space row if missing (FK targets for cross-space tests)."""
    if db.query(Space).filter(Space.id == space_id).first():
        return
    db.add(Space(id=space_id, name=name or space_id))
    db.commit()


def ensure_user(db, user_id: str, space_id: str = SPACE, *, email: str | None = None) -> None:
    """Insert a User row if missing (FK targets for subject_user_id / messages / proposals)."""
    if db.query(User).filter(User.id == user_id).first():
        return
    db.add(
        User(
            id=user_id,
            space_id=space_id,
            email=email or f"{user_id}@test.invalid",
            display_name=user_id,
        )
    )
    db.commit()


def ensure_workspace(
    db,
    workspace_id: str,
    space_id: str = SPACE,
    *,
    name: str | None = None,
    created_by_user_id: str | None = None,
) -> None:
    """Insert a Workspace row if missing."""
    if db.query(Workspace).filter(Workspace.id == workspace_id).first():
        return
    db.add(
        Workspace(
            id=workspace_id,
            space_id=space_id,
            name=name or workspace_id,
            created_by_user_id=created_by_user_id,
        )
    )
    db.commit()
