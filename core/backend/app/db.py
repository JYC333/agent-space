from __future__ import annotations
import json
from datetime import datetime
from sqlalchemy import create_engine, event, text
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
    from . import models  # noqa: F401 — triggers model registration
    Base.metadata.create_all(bind=engine)


def migrate_db():
    """Add columns to existing tables that were added after initial schema creation."""
    with engine.connect() as conn:
        _ensure_column(conn, "spaces", "created_by_user_id", "TEXT")


def _ensure_column(conn, table: str, column: str, col_type: str) -> None:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    existing = [row[1] for row in result.fetchall()]
    if column not in existing:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        conn.commit()
