from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


def _json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    json_serializer=lambda obj: json.dumps(obj, default=_json_serializer),
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Apply the canonical Alembic schema.

    Alembic migrations are the authoritative schema path. Tests may still use
    Base.metadata directly for isolated model checks, but application startup
    should not create or mutate schema through SQLAlchemy create_all().
    """
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    alembic_ini = backend_root / "alembic.ini"
    migrations_dir = backend_root / "migrations"
    cfg = Config(str(alembic_ini) if alembic_ini.exists() else None)
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("prepend_sys_path", str(backend_root))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def migrate_db():
    """Compatibility hook kept for callers; schema changes live in Alembic."""
    return None
