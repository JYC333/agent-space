"""Best-effort version metadata for backup manifests.

Every helper returns ``None`` when the value cannot be determined in the current
environment, never raising. These values are recorded in the backup manifest so a
later restore can validate compatibility. PostgreSQL is the server database.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# backup_format value carried in the manifest; bump on incompatible changes.
BACKUP_FORMAT = "agent-space-backup.v1"


def git_commit() -> Optional[str]:
    """Return the current git commit hash, or None outside a git checkout."""
    repo_root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            commit = out.stdout.strip()
            return commit or None
    except Exception:
        log.debug("git_commit: unable to resolve git commit", exc_info=True)
    return None


def pg_dump_version() -> Optional[str]:
    """Return the local pg_dump client version (e.g. '18.1'), or None if absent."""
    try:
        out = subprocess.run(
            ["pg_dump", "--version"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0:
            m = re.search(r"(\d+(?:\.\d+)*)", out.stdout)
            if m:
                return m.group(1)
    except Exception:
        log.debug("pg_dump_version: unable to resolve pg_dump version", exc_info=True)
    return None


def postgres_server_version(database_url: Optional[str]) -> Optional[str]:
    """Return the connected PostgreSQL server version string, or None on failure."""
    if not database_url:
        return None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                ver = conn.execute(text("SHOW server_version")).scalar()
                return str(ver) if ver is not None else None
        finally:
            engine.dispose()
    except Exception:
        log.debug("postgres_server_version: unable to query server version", exc_info=True)
    return None


def postgres_major(version: Optional[str]) -> Optional[int]:
    """Extract the integer major version from a Postgres version string."""
    if not version:
        return None
    m = re.match(r"(\d+)", version.strip())
    return int(m.group(1)) if m else None


def alembic_revision(database_url: Optional[str]) -> Optional[str]:
    """Return the alembic_version revision recorded in the DB, or None."""
    if not database_url:
        return None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                return str(rev) if rev is not None else None
        finally:
            engine.dispose()
    except Exception:
        log.debug("alembic_revision: unable to read alembic_version", exc_info=True)
    return None


def _redact(database_url: Optional[str]) -> Optional[str]:
    """Return host:port/db for logging — never user:pass."""
    if not database_url:
        return None
    parsed = urlparse(database_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    db = parsed.path or ""
    return f"{host}{port}{db}"
