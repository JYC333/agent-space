"""Scan due schedule automations and fire them.

In-app scheduler (no external cron). A background loop in the app lifespan calls
``scan_and_fire`` periodically. Each due automation is fired through the normal
``AutomationService.fire`` path (policy gates + preflight + queued Run); the job
worker then executes the Run. Pre-authorization (Option A) lets the resulting
automation-origin run pass the ``runtime.use_credential`` gate unattended.

Correctness guarantees (mirroring DailyCaptureReportScheduler):
- ``next_run_at`` is advanced and committed per-automation; one failure does not
  roll back others.
- Idempotent within a scan window: a successful fire advances next_run_at past now,
  so a concurrent/second scan skips it.
- A fire failure still advances next_run_at to the next slot (skip, do not retry the
  same slot forever) and records nothing else — the automation is not blocked.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Automation
from .service import AutomationService

log = logging.getLogger(__name__)


class AutomationScheduler:
    """Fire schedule-trigger automations whose next_run_at is due."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def scan_and_fire(self) -> int:
        """Fire all due schedule automations. Returns the number fired successfully."""
        now = datetime.now(UTC)
        due = (
            self._db.query(Automation)
            .filter(
                Automation.trigger_type == "schedule",
                Automation.status == "active",
                Automation.next_run_at.isnot(None),
                Automation.next_run_at <= now,
            )
            .all()
        )

        fired = 0
        svc = AutomationService(self._db)
        for auto in due:
            try:
                svc.fire(
                    automation_id=auto.id,
                    space_id=auto.space_id,
                    actor_user_id=auto.owner_user_id,
                    trigger_type="schedule",
                )
                svc.advance_schedule(auto)
                self._db.commit()
                fired += 1
                log.info(
                    "automation_scheduler: fired automation=%s space=%s next_run_at=%s",
                    auto.id, auto.space_id, auto.next_run_at,
                )
            except HTTPException as exc:
                # Preflight/policy rejected this fire — skip this slot, keep scheduling.
                self._db.rollback()
                self._db.expire_all()
                self._skip_slot(auto.id)
                log.warning(
                    "automation_scheduler: fire rejected automation=%s (%s) — advanced past slot",
                    auto.id, getattr(exc, "detail", exc),
                )
            except Exception:
                self._db.rollback()
                self._db.expire_all()
                self._skip_slot(auto.id)
                log.exception(
                    "automation_scheduler: fire failed automation=%s — advanced past slot", auto.id
                )
        return fired

    def _skip_slot(self, automation_id: str) -> None:
        """Advance next_run_at past the current slot after a failed fire (own txn)."""
        try:
            auto = self._db.query(Automation).filter(Automation.id == automation_id).first()
            if auto is not None:
                AutomationService(self._db).advance_schedule(auto)
                self._db.commit()
        except Exception:
            self._db.rollback()
            log.exception(
                "automation_scheduler: could not advance next_run_at for automation=%s",
                automation_id,
            )
