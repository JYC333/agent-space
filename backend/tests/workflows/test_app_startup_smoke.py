"""Real-lifespan startup smoke test against a fresh PostgreSQL database.

Most HTTP tests patch the FastAPI lifespan out (see ``app_db_override`` in the
root conftest). This test does the opposite: it runs the *real* application
lifespan against a brand-new, empty PostgreSQL database created inside the
session test container, and verifies the full cold-start path:

  * Alembic ``upgrade head`` runs on an empty database,
  * the app starts (``/health`` responds),
  * the durable job queue is initialised,
  * the background worker task starts and shuts down cleanly.

Unrelated background schedulers (daily capture report, backup) are disabled via
test-only settings overrides — not by changing production defaults — so this
test exercises only queue + worker startup. ``AGENT_SPACE_HOME`` is already an
ephemeral directory (root conftest), so this never touches a real mode root.
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
    # admin_url ends with /<default_db>; swap in the fresh database name.
    base, _, _old = admin_url.rpartition("/")
    return f"{base}/{db_name}"


def test_real_lifespan_cold_start_on_empty_postgres(pg_container, monkeypatch):
    fresh_url = _make_empty_database(pg_container, "lifespan_smoke")

    import app.config as app_config
    import app.db as app_db
    from app.main import app, lifespan
    from app.jobs.queue import PostgresQueueService, get_queue

    # Point the app at the fresh empty database for both the module-level engine
    # and the Alembic upgrade that init_db() runs from settings.database_url.
    fresh_engine = create_engine(fresh_url, pool_pre_ping=True)
    fresh_sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=fresh_engine)
    monkeypatch.setattr(app_config.settings, "database_url", fresh_url, raising=False)
    monkeypatch.setattr(app_db, "engine", fresh_engine, raising=False)
    monkeypatch.setattr(app_db, "SessionLocal", fresh_sessionmaker, raising=False)

    # Disable unrelated schedulers for this smoke test (test-only overrides).
    monkeypatch.setattr(app_config.settings, "daily_report_scheduler_enabled", False, raising=False)
    monkeypatch.setattr(app_config.settings, "automation_scheduler_enabled", False, raising=False)
    monkeypatch.setattr(app_config.settings, "backup_enabled", False, raising=False)

    async def _run() -> None:
        # Entering the real lifespan runs init_db() (Alembic upgrade on the empty
        # DB), capability/seed bootstrap, queue init, and worker startup.
        async with lifespan(app):
            # Schema was actually created by the migration on the empty DB.
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

            # Fresh-instance bootstrap reached a usable initial state on the
            # empty database: the owner's personal space (a generated UUID),
            # owner user + membership, and default execution planes.
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

            # Queue initialised.
            queue = get_queue()
            assert isinstance(queue, PostgresQueueService)

            # Background worker task is running.
            worker_tasks = [
                t for t in asyncio.all_tasks() if t.get_name() == "job-worker"
            ]
            assert len(worker_tasks) == 1, "expected exactly one running job-worker task"
            assert not worker_tasks[0].done()

            # /health responds via the real ASGI app (lifespan already active).
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json().get("status") in ("ok", "healthy")

        # After the lifespan exits, the worker task must be cleanly stopped.
        leftover = [t for t in asyncio.all_tasks() if t.get_name() == "job-worker" and not t.done()]
        assert not leftover, "job-worker task did not shut down cleanly"

    try:
        asyncio.run(_run())
    finally:
        fresh_engine.dispose()
        # Drop the smoke database so the container stays clean for other tests.
        admin = create_engine(pg_container.get_connection_url(driver="psycopg"))
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text('DROP DATABASE IF EXISTS "lifespan_smoke" WITH (FORCE)'))
        finally:
            admin.dispose()
