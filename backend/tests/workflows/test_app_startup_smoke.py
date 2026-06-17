"""Real-lifespan startup smoke test against a fresh PostgreSQL database.

Most HTTP tests patch the FastAPI lifespan out (see ``app_db_override`` in the
root conftest). This test runs the *real* application lifespan against a
brand-new, empty PostgreSQL database and verifies the cold-start path:

  * Alembic ``upgrade head`` runs on an empty database,
  * the app starts (``/health`` responds),
  * bootstrap seeds the default owner space and execution planes.

Job queue, schedulers, and backup ticks are owned by the TypeScript control
plane and are not started from the Python lifespan.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _make_empty_database(pg_container, db_name: str) -> str:
    """Create a fresh empty database in the container and return its psycopg URL."""
    admin_url = pg_container.get_connection_url(driver="psycopg")
    admin = create_engine(admin_url)
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()
    base, _, _old = admin_url.rpartition("/")
    return f"{base}/{db_name}"


def test_real_lifespan_cold_start_on_empty_postgres(pg_container, monkeypatch):
    fresh_url = _make_empty_database(pg_container, "lifespan_smoke")

    import app.config as app_config
    import app.db as app_db
    from app.main import app, lifespan

    fresh_engine = create_engine(fresh_url, pool_pre_ping=True)
    fresh_sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=fresh_engine)
    monkeypatch.setattr(app_config.settings, "database_url", fresh_url, raising=False)
    monkeypatch.setattr(app_db, "engine", fresh_engine, raising=False)
    monkeypatch.setattr(app_db, "SessionLocal", fresh_sessionmaker, raising=False)

    async def _run() -> None:
        async with lifespan(app):
            with fresh_engine.connect() as conn:
                tables = conn.execute(text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )).scalar()
                assert tables and tables > 0, "Alembic upgrade did not create tables"
                assert conn.execute(text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'jobs'"
                )).scalar() == 1

            with fresh_engine.connect() as conn:
                user_id = app_config.settings.default_user_id
                space_id = conn.execute(
                    text(
                        "SELECT s.id FROM spaces s "
                        "JOIN space_memberships m ON m.space_id = s.id "
                        "WHERE m.user_id = :u AND m.role = 'owner' "
                        "AND m.status = 'active' AND s.type = 'personal'"
                    ),
                    {"u": user_id},
                ).scalar()
                assert space_id, "default personal space not bootstrapped"
                assert conn.execute(
                    text("SELECT count(*) FROM users WHERE id = :u"), {"u": user_id}
                ).scalar() == 1, "default owner user not bootstrapped"
                assert conn.execute(
                    text(
                        "SELECT count(*) FROM space_memberships "
                        "WHERE space_id = :s AND user_id = :u AND role = 'owner' AND status = 'active'"
                    ),
                    {"s": space_id, "u": user_id},
                ).scalar() == 1, "owner membership not bootstrapped"
                assert conn.execute(
                    text("SELECT count(*) FROM execution_planes WHERE space_id = :s"),
                    {"s": space_id},
                ).scalar() > 0, "default execution planes not seeded"

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json().get("status") in ("ok", "healthy")

    try:
        asyncio.run(_run())
    finally:
        fresh_engine.dispose()
        admin = create_engine(pg_container.get_connection_url(driver="psycopg"))
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text('DROP DATABASE IF EXISTS "lifespan_smoke" WITH (FORCE)'))
        finally:
            admin.dispose()
