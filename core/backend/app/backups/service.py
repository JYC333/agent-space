"""BackupService — creates and prunes local backup archives.

Primary backup mechanism for two-person dogfooding. Called by BackupScheduler
for automatic backups, and via API for manual backups.

SQLite consistency: uses sqlite3.backup() API which produces a WAL-safe
consistent snapshot even while the database is live. If the backup API fails,
backup creation fails closed and no successful archive is produced.

Never prints or logs raw secret values.
"""
from __future__ import annotations

import logging
import fcntl
import os
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Iterator

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
        db_path: Path | None = None,
    ) -> None:
        self._data_root = data_root.resolve()
        self._backup_root = backup_root.resolve()
        self._interval_hours = interval_hours
        self._retention_count = retention_count
        self._include_logs = include_logs
        # db_path defaults to the canonical AppPaths.db_file location.
        self._db_path = db_path or (self._data_root / "db" / "agent_space.sqlite")
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
            # Handle same-second collisions (e.g. tests creating many backups rapidly)
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
                    db_snapshot_method="sqlite-backup-api",
                    backup_interval_hours=self._interval_hours,
                    backup_retention_count=self._retention_count,
                    warnings=warnings,
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
                # list_backups returns newest first; prune the tail
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

    def _stage(self, staging: Path) -> tuple[list[str], list[str], list[str]]:
        """Copy data into staging dir. Returns (included, excluded, warnings)."""
        included: list[str] = []
        excluded: list[str] = []
        warnings: list[str] = []

        # DB — sqlite3 backup API for WAL-safe consistent snapshot
        if self._db_path.exists():
            dest_db_dir = staging / "db"
            dest_db_dir.mkdir(parents=True, exist_ok=True)
            dest_db = dest_db_dir / self._db_path.name
            try:
                _sqlite_snapshot(self._db_path, dest_db)
            except Exception as exc:
                raise BackupError("sqlite backup API failed; backup aborted without raw file fallback") from exc
            included.append(f"db/{self._db_path.name} (sqlite-backup-api)")
        else:
            excluded.append("db/ (sqlite file not found)")

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
        """Cross-process local lock.

        The lock file may remain after a crash, but the fcntl advisory lock is
        released by the OS when the owning process exits. A leftover unlocked
        file is therefore deterministic and safe to reuse.
        """

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


def _sqlite_snapshot(source: Path, dest: Path) -> None:
    """Copy source SQLite DB to dest using the backup API (WAL-safe)."""
    src_conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
