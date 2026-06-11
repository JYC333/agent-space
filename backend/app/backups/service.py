"""BackupService — creates and prunes local backup archives.

Primary backup mechanism for two-person dogfooding. Called by BackupScheduler
through SchedulerRegistry for automatic backups, and via API for manual backups.

PostgreSQL: uses pg_dump custom format (-Fc --no-owner --no-acl) for a consistent
database snapshot. If pg_dump fails, backup creation fails closed and no successful
archive is produced.

Never prints or logs raw secret values.
"""
from __future__ import annotations

import logging
import fcntl
import os
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from .manifest import BackupManifest

log = logging.getLogger(__name__)

# Dirs included from source root when they exist (explicit allowlist).
# backups/ is intentionally absent — recursion prevention.
_INCLUDE_DIRS = ("storage", "artifacts", "config", "secrets", "workspaces")

# Dirs always excluded with reasons for the manifest.
_ALWAYS_EXCLUDED: dict[str, str] = {
    "backups":   "recursion prevention",
    "cache":     "ephemeral",
    "sandboxes": "ephemeral",
    "db/postgres": "live PostgreSQL data",
}


@dataclass
class BackupEntry:
    path: Path
    kind: str         # "auto" | "manual" | "unknown"
    created_at: datetime
    size_bytes: int


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely completed."""


class BackupInProgressError(BackupError):
    """Raised when another local backend process already holds the backup lock."""


class BackupService:
    def __init__(
        self,
        data_root: Path,
        backup_root: Path,
        interval_hours: int = 24,
        retention_count: int = 7,
        include_logs: bool = False,
        database_url: str | None = None,
        app_version: str | None = None,
    ) -> None:
        self._data_root = data_root.resolve()
        self._backup_root = backup_root.resolve()
        self._interval_hours = interval_hours
        self._retention_count = retention_count
        self._include_logs = include_logs
        self._database_url = database_url
        self._app_version = app_version
        self._lock_path = self._backup_root / ".backup.lock"

    # ── Public API ─────────────────────────────────────────────────────────────

    def create_backup(self, kind: str = "auto") -> Path:
        """Create a backup archive. kind must be 'auto' or 'manual'."""
        if kind not in ("auto", "manual"):
            raise ValueError(f"kind must be 'auto' or 'manual', got {kind!r}")

        self._prepare_backup_root()

        with self._file_lock(blocking=False):
            ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            archive_path = self._backup_root / f"{kind}-{ts}.tar.gz"
            counter = 1
            while archive_path.exists():
                archive_path = self._backup_root / f"{kind}-{ts}-{counter}.tar.gz"
                counter += 1

            with tempfile.TemporaryDirectory(prefix="aspace-backup-staging-") as _staging:
                staging = Path(_staging)
                included, excluded, warnings = self._stage(staging)
                manifest = BackupManifest(
                    kind=kind,
                    created_at=datetime.now(UTC).isoformat(),
                    source_root=str(self._data_root),
                    included_paths=included,
                    excluded_paths=excluded,
                    db_snapshot_method="pg_dump_custom",
                    backup_interval_hours=self._interval_hours,
                    backup_retention_count=self._retention_count,
                    warnings=warnings,
                    **self._version_metadata(),
                )
                (staging / "backup_manifest.json").write_text(manifest.to_json())

                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(staging, arcname=".")

            archive_path.chmod(0o600)
            log.info("backup created: %s (%d bytes)", archive_path.name, archive_path.stat().st_size)
            return archive_path

    def list_backups(self) -> list[BackupEntry]:
        """List all backups in backup_root, newest first."""
        if not self._backup_root.exists():
            return []
        entries: list[BackupEntry] = []
        for p in self._backup_root.glob("*.tar.gz"):
            stem = p.name.removesuffix(".tar.gz")
            parts = stem.split("-", 1)
            kind = parts[0] if parts[0] in ("auto", "manual") else "unknown"
            try:
                st = p.stat()
                entries.append(
                    BackupEntry(
                        path=p,
                        kind=kind,
                        created_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                        size_bytes=st.st_size,
                    )
                )
            except OSError:
                continue
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def prune_old_backups(self) -> list[Path]:
        """Prune auto backups, keeping the latest retention_count. Never prunes manual."""
        self._prepare_backup_root()
        try:
            with self._file_lock(blocking=False):
                auto_backups = [b for b in self.list_backups() if b.kind == "auto"]
                to_prune = auto_backups[self._retention_count:]
                pruned: list[Path] = []
                for entry in to_prune:
                    try:
                        entry.path.unlink()
                        log.info("pruned old auto backup: %s", entry.path.name)
                        pruned.append(entry.path)
                    except OSError as exc:
                        log.warning("failed to prune %s: %s", entry.path, exc)
                return pruned
        except BackupInProgressError:
            log.info("backup prune skipped because another backup is in progress")
            return []

    # ── Internal ───────────────────────────────────────────────────────────────

    def _version_metadata(self) -> dict[str, str | None]:
        """Best-effort version metadata recorded in the manifest for restore checks.

        Every value is best-effort and may be None; gathering it must never abort
        a backup. PostgreSQL is the server database.
        """
        from . import versions

        def _safe(fn, *args):
            try:
                return fn(*args)
            except Exception:
                log.debug("version metadata gather failed for %s", getattr(fn, "__name__", fn), exc_info=True)
                return None

        return {
            "app_version": self._app_version,
            "git_commit": _safe(versions.git_commit),
            "alembic_revision": _safe(versions.alembic_revision, self._database_url),
            "postgres_server_version": _safe(versions.postgres_server_version, self._database_url),
            "pg_dump_version": _safe(versions.pg_dump_version),
        }

    def _stage(self, staging: Path) -> tuple[list[str], list[str], list[str]]:
        """Copy data into staging dir. Returns (included, excluded, warnings)."""
        included: list[str] = []
        excluded: list[str] = []
        warnings: list[str] = []

        # DB — pg_dump custom-format snapshot
        if self._database_url:
            dest_db_dir = staging / "db"
            dest_db_dir.mkdir(parents=True, exist_ok=True)
            dest_dump = dest_db_dir / "agent_space.dump"
            try:
                _pg_dump(self._database_url, dest_dump)
                included.append("db/agent_space.dump (pg_dump_custom)")
            except Exception as exc:
                raise BackupError("pg_dump failed; backup aborted") from exc
        else:
            excluded.append("db/ (DATABASE_URL not configured — skipped)")
            warnings.append("Database not backed up: DATABASE_URL not set in BackupService")

        # Regular dirs
        for dirname in _INCLUDE_DIRS:
            src = self._data_root / dirname
            if not src.exists():
                excluded.append(f"{dirname}/ (not found)")
                continue
            shutil.copytree(src, staging / dirname, symlinks=True, ignore_dangling_symlinks=True)
            included.append(f"{dirname}/")

        # Logs — optional
        logs_src = self._data_root / "logs"
        if self._include_logs and logs_src.exists():
            shutil.copytree(logs_src, staging / "logs", symlinks=True, ignore_dangling_symlinks=True)
            included.append("logs/")
        else:
            reason = "not found" if not logs_src.exists() else "excluded by config (backup_include_logs=false)"
            excluded.append(f"logs/ ({reason})")

        # Always-excluded dirs — record explicitly in manifest
        for dirname, reason in _ALWAYS_EXCLUDED.items():
            excluded.append(f"{dirname}/ ({reason})")

        return included, excluded, warnings

    def _prepare_backup_root(self) -> None:
        self._backup_root.mkdir(parents=True, exist_ok=True)
        self._backup_root.chmod(0o700)

    @contextmanager
    def _file_lock(self, *, blocking: bool) -> Iterator[None]:
        """Cross-process local lock."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+") as fh:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(fh.fileno(), flags)
            except BlockingIOError as exc:
                raise BackupInProgressError("backup already in progress") from exc
            fh.seek(0)
            fh.truncate()
            fh.write(f"pid={os.getpid()} acquired_at={datetime.now(UTC).isoformat()}\n")
            fh.flush()
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _pg_dump(database_url: str, dest: Path) -> None:
    """Dump PostgreSQL database to a custom-format archive using pg_dump.

    Uses -Fc (custom format) with --no-owner and --no-acl so the dump can be
    restored with pg_restore by any superuser without requiring original roles.
    """
    parsed = urlparse(database_url)
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    # -Fc          — custom format (portable, supports selective restore, smaller than plain SQL)
    # --no-owner   — omit ownership commands (restore as any superuser)
    # --no-acl     — omit GRANT/REVOKE (restore without needing original roles)
    cmd = ["pg_dump", "--no-password", "-Fc", "--no-owner", "--no-acl"]
    if parsed.hostname:
        cmd += ["--host", parsed.hostname]
    if parsed.port:
        cmd += ["--port", str(parsed.port)]
    if parsed.username:
        cmd += ["--username", parsed.username]
    db_name = parsed.path.lstrip("/")
    cmd.append(db_name)

    with dest.open("wb") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, timeout=300)

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"pg_dump exited with code {result.returncode}: {stderr[:500]}")
