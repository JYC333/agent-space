"""BackupScheduler — one backup tick plus manual/list API support.

Cadence and task lifecycle are owned by ``app.scheduler.SchedulerRegistry``.
This object keeps the backup lock and exposes the operations used by the
registry tick and the backup API.
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
    ) -> None:
        self.service = service
        self._lock = asyncio.Lock()

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

    async def run_scheduled_backup(self) -> None:
        """Run one scheduled auto-backup tick."""
        await self._run_once()

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
