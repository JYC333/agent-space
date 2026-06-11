from __future__ import annotations
"""
DailyCaptureReportScheduler — scans enabled settings and enqueues
daily_capture_report jobs for those whose next_run_at is due.

Designed to be called from an async periodic task in the app lifespan.
The scan is idempotent: next_run_at is advanced only after a successful
enqueue, so a failed enqueue leaves the slot unchanged for the next scan.

Schedule semantics (local-calendar / DST):
  - next_run_at is stored in UTC, derived from a local-calendar slot.
  - local_date is derived from next_run_at converted to the setting's timezone —
    NOT from the current wall-clock time. This ensures a delayed run still
    generates the report for the intended day rather than silently skipping.
  - Advancing next_run_at: take the prior scheduled slot in local time, add one
    calendar day (keeping hour/minute), convert back to UTC.
  - Python's zoneinfo handles ambiguous times (DST fall-back) with fold=0 (the
    first occurrence). For nonexistent times (DST spring-forward), zoneinfo
    adjusts forward. The result may be ~1 hour early or late on transition days
    but the job is never skipped. This is acceptable for MVP.

Transaction safety:
  - Each due setting is processed as an independent unit of work.
  - On successful enqueue: next_run_at is advanced and committed immediately for
    that setting. A later failure on another setting cannot roll back this commit.
  - On enqueue failure: only that setting's uncommitted change is rolled back; the
    session is cleaned with expire_all() and scanning continues for remaining
    settings. The single-commit-after-all pattern is intentionally NOT used.

Retry semantics:
  - Jobs are enqueued with max_attempts=1. Product-level failures (provider
    missing, bad LLM JSON) are recorded on the Run row and the handler returns
    normally — the queue marks the job completed, not failed. Queue retry is not
    needed: if the enqueue itself fails, next_run_at is left unchanged so the
    scheduler naturally retries that slot on the next scan.

Timezone validation:
  - Settings with invalid timezone strings are skipped with a warning log.
  - next_run_at is not advanced for skipped settings so the administrator can
    correct the timezone and have the report run on the next scan.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from ..models import DailyCaptureReportSetting
from .schemas import zoneinfo_for_setting

log = logging.getLogger(__name__)


def _local_date_from_slot(slot_utc: datetime, tz: ZoneInfo) -> str:
    """Convert a UTC scheduled slot time to a local YYYY-MM-DD string."""
    return slot_utc.astimezone(tz).strftime("%Y-%m-%d")


def _compute_next_run_at_after_slot(
    slot_utc: datetime,
    row: DailyCaptureReportSetting,
    tz: ZoneInfo,
) -> datetime | None:
    """Compute next_run_at exactly one local calendar day after the given slot.

    DST: advancing by one local day means taking the prior slot in local time,
    adding 1 day, replacing hour/minute, then converting to UTC. See module
    docstring for ambiguous/nonexistent time handling.
    """
    if not row.enabled:
        return None
    try:
        h, m = int(row.local_time[:2]), int(row.local_time[3:5])
        slot_local = slot_utc.astimezone(tz)
        next_local = (slot_local + timedelta(days=1)).replace(
            hour=h, minute=m, second=0, microsecond=0
        )
        return next_local.astimezone(UTC)
    except Exception:
        return None


class DailyCaptureReportScheduler:
    """Scan due settings and enqueue daily_capture_report jobs."""

    def __init__(self, db: Session) -> None:
        self._db = db

    async def scan_and_enqueue(self, queue) -> int:
        """Find enabled settings due now and enqueue one job each.

        Returns the number of jobs successfully enqueued.

        Correctness guarantees:
        - local_date is derived from the scheduled slot (next_run_at) in the
          setting's timezone, not from current wall-clock date.
        - Each setting is committed independently; a failure on one setting does
          not roll back prior successful commits.
        - A failed enqueue leaves next_run_at unchanged so the next scan retries.
        - Running twice in the same window is idempotent: the first successful
          enqueue advances next_run_at past now, so the second scan skips it.
        - Settings with invalid timezone are skipped; next_run_at not advanced.
        """
        now = datetime.now(UTC)
        due_settings = (
            self._db.query(DailyCaptureReportSetting)
            .filter(
                DailyCaptureReportSetting.enabled == True,  # noqa: E712
                DailyCaptureReportSetting.next_run_at.isnot(None),
                DailyCaptureReportSetting.next_run_at <= now,
            )
            .all()
        )

        count = 0
        for setting in due_settings:
            # Validate timezone — skip (do not enqueue) if invalid
            tz = zoneinfo_for_setting(setting.timezone)
            if tz is None:
                log.warning(
                    "daily_report_scheduler: invalid timezone %r for space=%s user=%s"
                    " — skipping, next_run_at unchanged",
                    setting.timezone, setting.space_id, setting.user_id,
                )
                continue

            slot_utc = setting.next_run_at
            local_date = _local_date_from_slot(slot_utc, tz)

            payload = {
                "space_id": setting.space_id,
                "user_id": setting.user_id,
                "setting_id": setting.id,
                "local_date": local_date,
                "timezone": setting.timezone,
                "trigger_origin": "automation",
                "force": False,
            }

            try:
                await queue.enqueue(
                    "daily_capture_report",
                    payload,
                    space_id=setting.space_id,
                    user_id=setting.user_id,
                    priority=0,
                    max_attempts=1,  # product failures recorded on Run; no queue retry needed
                )
                # Advance next_run_at and commit immediately for this setting only
                next_slot = _compute_next_run_at_after_slot(slot_utc, setting, tz)
                setting.next_run_at = next_slot
                self._db.commit()
                count += 1
                log.info(
                    "daily_report_scheduler: enqueued job space=%s user=%s date=%s next_run_at=%s",
                    setting.space_id, setting.user_id, local_date, next_slot,
                )
            except Exception:
                # Rollback only this setting's change; clean session so other settings
                # can be processed safely on the same session.
                self._db.rollback()
                self._db.expire_all()
                log.exception(
                    "daily_report_scheduler: failed to enqueue space=%s user=%s"
                    " — next_run_at unchanged, continuing with remaining settings",
                    setting.space_id, setting.user_id,
                )

        return count
