"""DATABASE_URL is PostgreSQL-backed, and app startup uses Alembic (not create_all).

Settings accepts PostgreSQL connection strings, normalizes the canonical
SQLAlchemy psycopg driver form, rejects non-PostgreSQL URLs, and the startup
schema path must run Alembic migrations rather than ``Base.metadata.create_all``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, normalize_database_url

VALID_URL = "postgresql+psycopg://agent_space:pw@localhost:5432/agent_space"

# Each of these must be rejected by the validator.
INVALID_URLS = [
    "",
    "   ",
    "postgresql+asyncpg://agent_space:pw@localhost:5432/agent_space",  # wrong driver
    "postgres://agent_space:pw@localhost:5432/agent_space",          # bare postgres scheme
    "mysql://agent_space:pw@localhost:3306/agent_space",
]


@pytest.mark.parametrize("url", INVALID_URLS)
def test_invalid_database_url_is_rejected(url):
    with pytest.raises(ValidationError):
        Settings(database_url=url)


def test_valid_postgresql_psycopg_url_is_accepted():
    s = Settings(database_url=VALID_URL)
    assert s.database_url == VALID_URL


def test_postgresql_url_is_normalized_to_psycopg():
    raw = "postgresql://agent_space:pw@localhost:5432/agent_space"
    s = Settings(database_url=raw)
    assert s.database_url == VALID_URL


def test_shared_database_url_validator_rejects_alembic_invalid_urls():
    for url in INVALID_URLS:
        with pytest.raises(ValueError):
            normalize_database_url(url)


def test_alembic_env_uses_shared_database_url_validator():
    env_py = Path(__file__).resolve().parents[2] / "migrations" / "env.py"
    text = env_py.read_text()
    assert "from app.config import normalize_database_url, settings" in text
    assert "return normalize_database_url(configured)" in text


def test_rejected_url_error_message_points_to_postgres():
    with pytest.raises(ValidationError) as ei:
        Settings(database_url="postgres://agent_space:pw@localhost:5432/agent_space")
    assert "postgresql+psycopg" in str(ei.value)


# ── Prod requires an explicit DATABASE_URL ──────────────────────────────────────

def test_dev_and_test_may_use_the_default_database_url(monkeypatch):
    """dev/test environments rely on the convenience default without configuration."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for env in ("dev", "test"):
        s = Settings(agent_space_env=env)
        assert s.database_url.startswith("postgresql+psycopg://")


def test_prod_without_explicit_database_url_is_rejected(monkeypatch):
    """prod must not silently fall back to the development default database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as ei:
        Settings(agent_space_env="prod")
    msg = str(ei.value)
    assert "AGENT_SPACE_ENV=prod" in msg
    assert "DATABASE_URL" in msg


def test_prod_with_explicit_postgres_url_is_accepted(monkeypatch):
    """prod accepts an explicit postgresql+psycopg:// connection string."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    prod_url = "postgresql+psycopg://agent_space:prodpw@db.internal:5432/agent_space"
    s = Settings(agent_space_env="prod", database_url=prod_url)
    assert s.database_url == prod_url


def test_app_startup_uses_alembic_not_create_all(monkeypatch):
    """init_db() must drive Alembic ``upgrade head`` — never create_all()."""
    import app.db as app_db

    calls: list[tuple] = []

    def _fake_upgrade(cfg, revision):
        calls.append((cfg, revision))

    # Patch the Alembic command used by init_db; never touch a real DB.
    monkeypatch.setattr("alembic.command.upgrade", _fake_upgrade)

    # Guard: if init_db ever switched to create_all, this would be called instead.
    created = {"called": False}
    real_create_all = app_db.Base.metadata.create_all

    def _tripwire_create_all(*args, **kwargs):  # pragma: no cover - must not run
        created["called"] = True
        return real_create_all(*args, **kwargs)

    monkeypatch.setattr(app_db.Base.metadata, "create_all", _tripwire_create_all)

    app_db.init_db()

    assert calls, "init_db() did not invoke Alembic command.upgrade"
    assert calls[-1][1] == "head", "init_db() must upgrade to 'head'"
    assert created["called"] is False, "init_db() must not use Base.metadata.create_all()"
