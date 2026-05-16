"""Unit tests for BackupService, BackupScheduler, and BackupManifest.

Covers M7b automatic backup service invariants:
  - BackupService creates archive with correct structure.
  - backup_manifest.json is present and well-formed.
  - Exclusions: backups/, cache/, sandboxes/ are never archived.
  - Logs excluded by default; included when configured.
  - SQLite snapshot included via backup API; backup fails closed if snapshot fails.
  - No raw secret patterns in manifest.
  - Retention prunes auto backups only.
  - Scheduler skips run when lock is held (overlap prevention).
  - backup_enabled defaults to False (explicit opt-in).
  - BackupService requires no DB session or automation model.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from app.backups.service import BackupError, BackupInProgressError, BackupService
from app.backups.scheduler import BackupScheduler


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_data_root(base: Path) -> Path:
    """Create a minimal, realistic data root for testing."""
    data = base / "data"
    (data / "db").mkdir(parents=True)
    (data / "storage" / "files").mkdir(parents=True)
    (data / "artifacts").mkdir()
    (data / "config").mkdir()
    (data / "secrets").mkdir()
    (data / "workspaces" / "project1").mkdir(parents=True)
    (data / "cache").mkdir()
    (data / "sandboxes").mkdir()
    (data / "logs").mkdir()

    # Minimal SQLite DB
    conn = sqlite3.connect(str(data / "db" / "agent_space.sqlite"))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()

    (data / "storage" / "files" / "file.bin").write_bytes(b"\x01\x02")
    (data / "artifacts" / "run1.txt").write_text("output")
    (data / "config" / "settings.yaml").write_text("key: value")
    (data / "secrets" / "provider_keys.key").write_bytes(b"\x00" * 32)
    (data / "cache" / "ephemeral.dat").write_text("tmp")
    (data / "sandboxes" / "sb1").mkdir()
    (data / "logs" / "app.log").write_text("log line\n")
    return data


def _make_service(base: Path, **kwargs) -> BackupService:
    data_root = _make_data_root(base)
    backup_root = base / "backups"
    return BackupService(data_root=data_root, backup_root=backup_root, **kwargs)


def _archive_names(archive: Path) -> set[str]:
    with tarfile.open(archive) as tar:
        return {m.name for m in tar.getmembers()}


def _read_manifest(archive: Path) -> dict:
    with tarfile.open(archive) as tar:
        member = tar.extractfile("./backup_manifest.json")
        assert member is not None, "backup_manifest.json missing from archive"
        return json.load(member)


# ── Archive creation ───────────────────────────────────────────────────────────

class TestCreateBackup:
    def test_creates_archive_file(self, tmp_path):
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        assert archive.exists()
        assert archive.name.endswith(".tar.gz")

    def test_auto_kind_in_name(self, tmp_path):
        svc = _make_service(tmp_path)
        assert svc.create_backup("auto").name.startswith("auto-")

    def test_manual_kind_in_name(self, tmp_path):
        svc = _make_service(tmp_path)
        assert svc.create_backup("manual").name.startswith("manual-")

    def test_invalid_kind_raises(self, tmp_path):
        svc = _make_service(tmp_path)
        with pytest.raises(ValueError, match="kind must be"):
            svc.create_backup("arbitrary")

    def test_archive_permissions_are_600(self, tmp_path):
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        assert oct(archive.stat().st_mode & 0o777) == "0o600"

    def test_backup_root_created_with_700(self, tmp_path):
        data_root = _make_data_root(tmp_path)
        backup_root = tmp_path / "backups"
        assert not backup_root.exists()
        svc = BackupService(data_root=data_root, backup_root=backup_root)
        svc.create_backup("auto")
        assert oct(backup_root.stat().st_mode & 0o777) == "0o700"


# ── Manifest ──────────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_present(self, tmp_path):
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        m = _read_manifest(archive)
        assert m["backup_format"] == "agent-space-backup.v1"

    def test_manifest_kind_matches_auto(self, tmp_path):
        svc = _make_service(tmp_path)
        assert _read_manifest(svc.create_backup("auto"))["kind"] == "auto"

    def test_manifest_kind_matches_manual(self, tmp_path):
        svc = _make_service(tmp_path)
        assert _read_manifest(svc.create_backup("manual"))["kind"] == "manual"

    def test_manifest_has_created_at(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert m["created_at"]  # non-empty ISO timestamp

    def test_manifest_source_root_is_data_root(self, tmp_path):
        data_root = _make_data_root(tmp_path)
        svc = BackupService(data_root=data_root, backup_root=tmp_path / "bk")
        m = _read_manifest(svc.create_backup("auto"))
        assert m["source_root"] == str(data_root)

    def test_manifest_included_paths_contains_db(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert any("db/" in p for p in m["included_paths"])

    def test_manifest_excluded_paths_documents_backups(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert any("backups/" in p for p in m["excluded_paths"])

    def test_manifest_excluded_paths_documents_cache(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert any("cache/" in p for p in m["excluded_paths"])

    def test_manifest_excluded_paths_documents_sandboxes(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert any("sandboxes/" in p for p in m["excluded_paths"])

    def test_manifest_has_no_raw_api_key_pattern(self, tmp_path):
        """Manifest JSON must never contain raw API key patterns."""
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        manifest_str = json.dumps(_read_manifest(archive))
        assert not re.search(r"sk-ant-[A-Za-z0-9\-_]{10,}", manifest_str)
        assert not re.search(r"ANTHROPIC_API_KEY\s*=\s*\S+", manifest_str)

    def test_manifest_db_snapshot_method_present(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert m["db_snapshot_method"] == "sqlite-backup-api"

    def test_manifest_config_fields_match_service(self, tmp_path):
        svc = _make_service(tmp_path, interval_hours=12, retention_count=5)
        m = _read_manifest(svc.create_backup("auto"))
        assert m["backup_interval_hours"] == 12
        assert m["backup_retention_count"] == 5


# ── Inclusions ────────────────────────────────────────────────────────────────

class TestInclusions:
    def test_db_snapshot_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        names = _archive_names(archive)
        assert any(n.lstrip("./").startswith("db/") for n in names)

    def test_storage_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("storage") for n in names)

    def test_artifacts_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("artifacts") for n in names)

    def test_config_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("config") for n in names)

    def test_secrets_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("secrets") for n in names)

    def test_workspaces_in_archive(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("workspaces") for n in names)


# ── Exclusions ────────────────────────────────────────────────────────────────

class TestExclusions:
    def test_excludes_cache(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert not any(n.lstrip("./").startswith("cache") for n in names)

    def test_excludes_sandboxes(self, tmp_path):
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        assert not any(n.lstrip("./").startswith("sandboxes") for n in names)

    def test_excludes_logs_by_default(self, tmp_path):
        svc = _make_service(tmp_path, include_logs=False)
        names = _archive_names(svc.create_backup("auto"))
        assert not any(n.lstrip("./").startswith("logs") for n in names)

    def test_includes_logs_when_configured(self, tmp_path):
        svc = _make_service(tmp_path, include_logs=True)
        names = _archive_names(svc.create_backup("auto"))
        assert any(n.lstrip("./").startswith("logs") for n in names)

    def test_excludes_backups_dir_recursion_prevention(self, tmp_path):
        """backup_root inside data_root must not appear in the archive."""
        data_root = _make_data_root(tmp_path)
        backup_root = data_root / "backups"  # intentionally inside data root
        backup_root.mkdir()
        svc = BackupService(data_root=data_root, backup_root=backup_root)
        # Create a file inside backup_root to prove it is excluded
        (backup_root / "old-backup.tar.gz").write_bytes(b"fake")
        names = _archive_names(svc.create_backup("auto"))
        assert not any(n.lstrip("./").startswith("backups") for n in names)

    def test_does_not_include_backup_root_even_when_external(self, tmp_path):
        """Backups dir is never in the include list regardless of location."""
        svc = _make_service(tmp_path)
        names = _archive_names(svc.create_backup("auto"))
        # "backups" only appears in backup_manifest.json excluded_paths, not as a directory
        non_manifest = {n for n in names if "manifest" not in n}
        assert not any("backups" in n for n in non_manifest)


# ── SQLite snapshot ────────────────────────────────────────────────────────────

class TestSQLiteSnapshot:
    def test_db_snapshot_is_valid_sqlite(self, tmp_path):
        svc = _make_service(tmp_path)
        archive = svc.create_backup("auto")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(extract_dir, filter="data")
        db_file = extract_dir / "db" / "agent_space.sqlite"
        assert db_file.exists()
        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("SELECT val FROM test WHERE id=1").fetchall()
        conn.close()
        assert rows == [("hello",)]

    def test_db_snapshot_method_in_manifest(self, tmp_path):
        svc = _make_service(tmp_path)
        m = _read_manifest(svc.create_backup("auto"))
        assert m["db_snapshot_method"] == "sqlite-backup-api"

    def test_sqlite_snapshot_opens_independent_connections(self, tmp_path, monkeypatch):
        import app.backups.service as service_mod

        data_root = _make_data_root(tmp_path)
        backup_root = tmp_path / "backups"
        db_path = data_root / "db" / "agent_space.sqlite"
        opened: list[str] = []
        real_connect = service_mod.sqlite3.connect

        def tracking_connect(path, *args, **kwargs):
            opened.append(str(path))
            return real_connect(path, *args, **kwargs)

        monkeypatch.setattr(service_mod.sqlite3, "connect", tracking_connect)

        BackupService(data_root=data_root, backup_root=backup_root, db_path=db_path).create_backup("manual")

        assert str(db_path) in opened
        assert any(Path(p).name == "agent_space.sqlite" and Path(p) != db_path for p in opened)

    def test_sqlite_snapshot_failure_fails_closed_without_archive(self, tmp_path, monkeypatch):
        import app.backups.service as service_mod

        svc = _make_service(tmp_path)

        def fail_snapshot(source, dest):
            raise sqlite3.Error("backup api unavailable")

        monkeypatch.setattr(service_mod, "_sqlite_snapshot", fail_snapshot)

        with pytest.raises(BackupError, match="backup aborted"):
            svc.create_backup("auto")

        assert [p for p in (tmp_path / "backups").glob("*.tar.gz")] == []


# ── Retention ─────────────────────────────────────────────────────────────────

class TestRetention:
    def test_prune_keeps_latest_n_auto_backups(self, tmp_path):
        svc = _make_service(tmp_path, retention_count=3)
        for _ in range(5):
            svc.create_backup("auto")
        pruned = svc.prune_old_backups()
        remaining_auto = [b for b in svc.list_backups() if b.kind == "auto"]
        assert len(remaining_auto) == 3
        assert len(pruned) == 2

    def test_prune_never_removes_manual_backups(self, tmp_path):
        svc = _make_service(tmp_path, retention_count=1)
        for _ in range(3):
            svc.create_backup("auto")
        svc.create_backup("manual")
        svc.prune_old_backups()
        manual = [b for b in svc.list_backups() if b.kind == "manual"]
        assert len(manual) == 1

    def test_list_backups_newest_first(self, tmp_path):
        svc = _make_service(tmp_path)
        for _ in range(3):
            svc.create_backup("auto")
        entries = svc.list_backups()
        assert len(entries) == 3
        for i in range(len(entries) - 1):
            assert entries[i].created_at >= entries[i + 1].created_at

    def test_list_backups_empty_when_none_exist(self, tmp_path):
        data_root = _make_data_root(tmp_path)
        svc = BackupService(data_root=data_root, backup_root=tmp_path / "bk")
        assert svc.list_backups() == []

    def test_prune_removes_pruned_files(self, tmp_path):
        svc = _make_service(tmp_path, retention_count=1)
        for _ in range(3):
            svc.create_backup("auto")
        pruned = svc.prune_old_backups()
        for p in pruned:
            assert not p.exists()

    def test_prune_at_exactly_retention_count_removes_nothing(self, tmp_path):
        svc = _make_service(tmp_path, retention_count=3)
        for _ in range(3):
            svc.create_backup("auto")
        pruned = svc.prune_old_backups()
        assert pruned == []

    def test_prune_skips_when_backup_lock_held(self, tmp_path):
        svc = _make_service(tmp_path, retention_count=1)
        svc.create_backup("auto")
        lock_path = tmp_path / "backups" / ".backup.lock"
        proc = _hold_lock_in_subprocess(lock_path)
        try:
            assert svc.prune_old_backups() == []
        finally:
            proc.terminate()
            proc.wait(timeout=5)


class TestFileLock:
    def test_file_lock_prevents_second_service_backup(self, tmp_path):
        data_root = _make_data_root(tmp_path)
        backup_root = tmp_path / "backups"
        backup_root.mkdir()
        lock_path = backup_root / ".backup.lock"
        svc = BackupService(data_root=data_root, backup_root=backup_root)

        proc = _hold_lock_in_subprocess(lock_path)
        try:
            with pytest.raises(BackupInProgressError):
                svc.create_backup("manual")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_stale_unlocked_lock_file_does_not_block_backup(self, tmp_path):
        data_root = _make_data_root(tmp_path)
        backup_root = tmp_path / "backups"
        backup_root.mkdir()
        (backup_root / ".backup.lock").write_text("pid=1 acquired_at=old\n")
        svc = BackupService(data_root=data_root, backup_root=backup_root)

        archive = svc.create_backup("manual")
        assert archive.exists()


def _hold_lock_in_subprocess(lock_path: Path) -> subprocess.Popen:
    code = (
        "import fcntl, pathlib, sys, time\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "fh = p.open('a+')\n"
        "fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "locked"
    return proc


# ── Scheduler ─────────────────────────────────────────────────────────────────

class TestScheduler:
    def _run_once_inline(self, scheduler, monkeypatch):
        import app.backups.scheduler as scheduler_mod

        async def inline_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr(scheduler_mod.asyncio, "to_thread", inline_to_thread)
        asyncio.run(scheduler._run_once())

    def test_scheduler_skips_when_lock_held(self, tmp_path, monkeypatch):
        """_run_once must skip if a backup is already in progress."""
        svc = _make_service(tmp_path)
        call_count = 0
        orig = svc.create_backup

        def counting_create(kind):
            nonlocal call_count
            call_count += 1
            return orig(kind)

        svc.create_backup = counting_create
        scheduler = BackupScheduler(service=svc, interval_hours=1)

        async def _test():
            # Simulate in-progress backup by holding the lock
            await scheduler._lock.acquire()
            await scheduler._run_once()
            scheduler._lock.release()

        import app.backups.scheduler as scheduler_mod

        async def inline_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr(scheduler_mod.asyncio, "to_thread", inline_to_thread)
        asyncio.run(_test())
        assert call_count == 0, "backup ran despite lock being held"

    def test_scheduler_runs_when_lock_free(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path)
        scheduler = BackupScheduler(service=svc, interval_hours=1)

        self._run_once_inline(scheduler, monkeypatch)
        assert len(svc.list_backups()) == 1

    def test_scheduler_run_once_creates_auto_backup(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path)
        scheduler = BackupScheduler(service=svc, interval_hours=1)

        self._run_once_inline(scheduler, monkeypatch)
        backups = svc.list_backups()
        assert backups[0].kind == "auto"

    def test_scheduler_run_once_prunes_after_backup(self, tmp_path, monkeypatch):
        svc = _make_service(tmp_path, retention_count=2)
        # Pre-populate more than retention_count backups
        for _ in range(4):
            svc.create_backup("auto")
        scheduler = BackupScheduler(service=svc, interval_hours=1)

        self._run_once_inline(scheduler, monkeypatch)
        # _run_once creates one more then prunes → retention_count=2 remain
        auto = [b for b in svc.list_backups() if b.kind == "auto"]
        assert len(auto) == 2


# ── Config and isolation ───────────────────────────────────────────────────────

class TestConfigAndIsolation:
    def test_backup_enabled_false_by_default(self):
        """Tests must not start automatic backups accidentally."""
        from app.config import settings
        assert settings.backup_enabled is False

    def test_backup_service_requires_no_db_session(self, tmp_path):
        """BackupService must be constructable and usable without any DB session."""
        svc = _make_service(tmp_path)
        archive = svc.create_backup("manual")
        assert archive.exists()

    def test_backup_service_requires_no_automation_model(self, tmp_path):
        """No Automation/Trigger model needed — service is self-contained."""
        from app.backups.service import BackupService
        data_root = _make_data_root(tmp_path)
        # Construct with only the required path args — no DB, no models
        svc = BackupService(data_root=data_root, backup_root=tmp_path / "bk")
        archive = svc.create_backup("manual")
        assert archive.exists()
