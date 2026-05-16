"""BackupScheduler — periodic auto-backup tied to app lifespan.

Started and stopped in app/main.py lifespan. Does not block startup.
Uses an asyncio.Lock to prevent overlapping backup runs.
Disabled when settings.backup_enabled is False (scheduler is never started).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import BackupService

log = logging.getLogger(__name__)

# Module-level singleton — set by main.py lifespan, read by api.py
_scheduler: BackupScheduler | None = None


class BackupScheduler:
    def __init__(
        self,
        service: BackupService,
        interval_hours: int,
        run_on_start: bool = False,
    ) -> None:
        self.service = service
        self._interval_seconds = interval_hours * 3600
        self._run_on_start = run_on_start
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is not None:
            return
        if self._run_on_start:
            await self._run_once()
        self._task = asyncio.create_task(self._loop(), name="backup-scheduler")
        log.info(
            "backup scheduler started (interval=%dh, run_on_start=%s)",
            self._interval_seconds // 3600,
            self._run_on_start,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("backup scheduler stopped")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self._run_once()

    async def _run_once(self) -> None:
        if self._lock.locked():
            log.info("backup already in progress — skipping scheduled run")
            return
        async with self._lock:
            try:
                path = await asyncio.to_thread(self.service.create_backup, "auto")
                await asyncio.to_thread(self.service.prune_old_backups)
                log.info("scheduled backup complete: %s", path.name)
            except Exception:
                log.exception("scheduled backup failed")

    def list_backups(self):
        return self.service.list_backups()

    async def run_manual_backup(self):
        """Run a manual backup; raises RuntimeError if a backup is already in progress."""
        if self._lock.locked():
            raise RuntimeError("backup already in progress")
        async with self._lock:
            path = await asyncio.to_thread(self.service.create_backup, "manual")
            return path


def get_scheduler() -> BackupScheduler | None:
    return _scheduler


def set_scheduler(s: BackupScheduler | None) -> None:
    global _scheduler
    _scheduler = s
