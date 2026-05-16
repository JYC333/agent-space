"""Backup status and manual trigger API.

GET  /api/v1/system/backups         — list backups (auth required)
POST /api/v1/system/backups/manual  — trigger immediate manual backup (auth required)

Returns 503 when backup_enabled=False (scheduler not running).
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.api_key import get_identity
from .scheduler import get_scheduler

log = logging.getLogger(__name__)
router = APIRouter(prefix="/system/backups", tags=["system"])


class BackupInfo(BaseModel):
    name: str
    kind: str
    created_at: datetime
    size_bytes: int


@router.get("", response_model=list[BackupInfo])
def list_backups(_: tuple[str, str] = Depends(get_identity)):
    sched = get_scheduler()
    if sched is None:
        return []
    return [
        BackupInfo(
            name=e.path.name,
            kind=e.kind,
            created_at=e.created_at,
            size_bytes=e.size_bytes,
        )
        for e in sched.list_backups()
    ]


@router.post("/manual", status_code=202)
def trigger_manual_backup(_: tuple[str, str] = Depends(get_identity)):
    sched = get_scheduler()
    if sched is None:
        raise HTTPException(
            status_code=503,
            detail="Backup service not running — set BACKUP_ENABLED=true to enable",
        )
    try:
        path = sched.service.create_backup("manual")
        sched.service.prune_old_backups()
        return {"status": "ok", "backup": path.name}
    except Exception as exc:
        log.exception("manual backup failed")
        raise HTTPException(status_code=500, detail="Backup failed") from exc
