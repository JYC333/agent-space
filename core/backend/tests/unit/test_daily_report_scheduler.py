"""Unit tests for DailyCaptureReportScheduler.

Covers:
  1. Enabled setting with due next_run_at enqueues one job.
  2. Disabled setting never enqueues.
  3. Duplicate scan within the same window is idempotent (no second enqueue).
  4. Enqueue failure does not advance next_run_at.
  5. local_date is derived from the scheduled slot, not current wall-clock date
     (delayed-past-midnight scenario).
  6. Two due settings: first enqueue succeeds, second fails — first is committed
     and not re-enqueued on next scan; second remains due for retry.
  7. A failed enqueue on one setting does not block other independent settings.
  8. Setting with invalid timezone is skipped; next_run_at unchanged; no enqueue.
  9. Scheduler enqueues with max_attempts=1.
 10. DST spring-forward: next_run_at computed correctly across DST boundary.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from ulid import ULID
from zoneinfo import ZoneInfo

from app.daily_reports.scheduler import (
    DailyCaptureReportScheduler,
    _local_date_from_slot,
    _compute_next_run_at_after_slot,
)
from app.models import (
    DailyCaptureReportSetting,
    Space,
    SpaceMembership,
    User,
)


def _uid() -> str:
    return str(ULID())


def _make_space_and_user(db) -> tuple[str, str]:
    user_id = _uid()
    space_id = _uid()
    db.add(User(id=user_id, display_name="Sched Test", status="active"))
    db.add(Space(id=space_id, name="Sched Space", type="personal", created_by_user_id=user_id))
    db.add(SpaceMembership(id=_uid(), space_id=space_id, user_id=user_id, role="owner", status="active"))
    db.commit()
    return space_id, user_id


def _make_setting(
    db,
    space_id: str,
    user_id: str,
    *,
    enabled: bool = True,
    next_run_at: datetime | None = None,
    timezone: str = "UTC",
    local_time: str = "08:00",
) -> DailyCaptureReportSetting:
    if next_run_at is None:
        # Default: already due (5 minutes in the past)
        next_run_at = datetime.now(UTC) - timedelta(minutes=5)
    setting = DailyCaptureReportSetting(
        id=_uid(),
        space_id=space_id,
        user_id=user_id,
        enabled=enabled,
        local_time=local_time,
        timezone=timezone,
        include_source_types_json=["user_capture"],
        create_experience_proposals=True,
        create_memory_proposals=False,
        experience_confidence_threshold=0.75,
        memory_confidence_threshold=0.85,
        max_experience_proposals_per_day=5,
        max_memory_proposals_per_day=3,
        next_run_at=next_run_at,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def _make_queue(*, fail: bool = False) -> MagicMock:
    """Build a mock queue with an async enqueue method."""
    q = MagicMock()
    if fail:
        q.enqueue = AsyncMock(side_effect=RuntimeError("simulated enqueue failure"))
    else:
        q.enqueue = AsyncMock(return_value=None)
    return q


# ---------------------------------------------------------------------------
# 1. Enabled, due setting → one job enqueued
# ---------------------------------------------------------------------------

def test_enabled_due_setting_enqueues_one_job(db):
    space_id, user_id = _make_space_and_user(db)
    setting = _make_setting(db, space_id, user_id, enabled=True)
    original_next_run_at = setting.next_run_at

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)
    count = asyncio.run(scheduler.scan_and_enqueue(queue))

    assert count == 1
    queue.enqueue.assert_called_once()
    call_kwargs = queue.enqueue.call_args
    assert call_kwargs[0][0] == "daily_capture_report"
    payload = call_kwargs[0][1]
    assert payload["space_id"] == space_id
    assert payload["user_id"] == user_id
    assert payload["trigger_origin"] == "automation"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", payload["local_date"])

    # next_run_at must have been advanced beyond original slot
    db.refresh(setting)
    assert setting.next_run_at is not None
    assert setting.next_run_at > original_next_run_at


# ---------------------------------------------------------------------------
# 2. Disabled setting → no enqueue
# ---------------------------------------------------------------------------

def test_disabled_setting_does_not_enqueue(db):
    space_id, user_id = _make_space_and_user(db)
    _make_setting(db, space_id, user_id, enabled=False)

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)
    count = asyncio.run(scheduler.scan_and_enqueue(queue))

    assert count == 0
    queue.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Duplicate scan is idempotent (second scan finds nothing due)
# ---------------------------------------------------------------------------

def test_duplicate_scan_does_not_enqueue_twice(db):
    space_id, user_id = _make_space_and_user(db)
    _make_setting(db, space_id, user_id, enabled=True)

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)

    count1 = asyncio.run(scheduler.scan_and_enqueue(queue))
    count2 = asyncio.run(scheduler.scan_and_enqueue(queue))

    assert count1 == 1
    assert count2 == 0
    assert queue.enqueue.call_count == 1


# ---------------------------------------------------------------------------
# 4. Enqueue failure → next_run_at unchanged
# ---------------------------------------------------------------------------

def test_enqueue_failure_does_not_advance_next_run_at(db):
    space_id, user_id = _make_space_and_user(db)
    slot = datetime.now(UTC) - timedelta(minutes=10)
    setting = _make_setting(db, space_id, user_id, enabled=True, next_run_at=slot)
    original_next_run_at = setting.next_run_at

    queue = _make_queue(fail=True)
    scheduler = DailyCaptureReportScheduler(db)
    count = asyncio.run(scheduler.scan_and_enqueue(queue))

    assert count == 0

    # Re-fetch from DB to confirm no advance
    db.expire(setting)
    db.refresh(setting)
    # next_run_at must not have advanced past the original slot
    assert setting.next_run_at is not None
    assert setting.next_run_at <= original_next_run_at + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# 5. Delayed past midnight: local_date comes from slot, not wall clock
# ---------------------------------------------------------------------------

def test_delayed_scheduler_uses_slot_date_not_wallclock(db):
    """Scheduler delayed past midnight should report for the intended day.

    The session-scoped DB may have due settings from prior tests, so we verify
    the correct local_date is used for our specific setting rather than checking
    total count.
    """
    space_id, user_id = _make_space_and_user(db)

    # Slot was 2000-01-15 23:00 UTC — well in the past, clearly due
    yesterday_slot = datetime(2000, 1, 15, 23, 0, 0, tzinfo=UTC)
    setting = _make_setting(db, space_id, user_id, enabled=True, next_run_at=yesterday_slot, timezone="UTC")

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)
    count = asyncio.run(scheduler.scan_and_enqueue(queue))

    assert count >= 1  # our setting was enqueued (may include others from session DB)

    # Find the enqueue call for our specific setting
    our_call = None
    for call in queue.enqueue.call_args_list:
        payload = call[0][1]
        if payload.get("setting_id") == setting.id:
            our_call = payload
            break

    assert our_call is not None, "Our setting was not enqueued"
    # local_date must be derived from the 2000-01-15 slot, not today's wall-clock date
    assert our_call["local_date"] == "2000-01-15"


# ---------------------------------------------------------------------------
# 6. Two due settings: first succeeds, second fails
#    → first committed and skipped by next scan; second remains due
# ---------------------------------------------------------------------------

def test_partial_failure_first_committed_second_retryable(db):
    """First setting committed and not re-enqueued; second remains due for retry."""
    space_id1, user_id1 = _make_space_and_user(db)
    space_id2, user_id2 = _make_space_and_user(db)

    setting1 = _make_setting(db, space_id1, user_id1)
    setting2 = _make_setting(db, space_id2, user_id2)

    orig1 = setting1.next_run_at
    orig2 = setting2.next_run_at

    # Fail enqueue for space_id2
    async def selective_fail(*args, **kwargs):
        payload = args[1] if len(args) > 1 else {}
        if payload.get("space_id") == space_id2:
            raise RuntimeError("simulated failure for setting2")

    queue = MagicMock()
    queue.enqueue = AsyncMock(side_effect=selective_fail)

    scheduler = DailyCaptureReportScheduler(db)
    count = asyncio.run(scheduler.scan_and_enqueue(queue))

    # At least setting1 enqueued (other tests' residual due settings may also be picked up)
    assert count >= 1

    db.expire_all()
    db.refresh(setting1)
    db.refresh(setting2)

    # setting1: next_run_at advanced (committed)
    assert setting1.next_run_at is not None
    assert setting1.next_run_at > orig1

    # setting2: next_run_at unchanged (not committed)
    assert setting2.next_run_at is not None
    assert setting2.next_run_at <= orig2 + timedelta(seconds=1)

    # Second scan: setting1 must NOT be enqueued again (its slot is in the future)
    queue2 = _make_queue()
    asyncio.run(scheduler.scan_and_enqueue(queue2))

    enqueued_setting_ids = {
        call[0][1].get("setting_id")
        for call in queue2.enqueue.call_args_list
    }
    assert setting1.id not in enqueued_setting_ids, "setting1 must not be re-enqueued on second scan"
    # setting2 should be enqueued on second scan (still due)
    assert setting2.id in enqueued_setting_ids


# ---------------------------------------------------------------------------
# 7. Failure on one setting does not block other independent settings
# ---------------------------------------------------------------------------

def test_failure_on_one_setting_does_not_block_others(db):
    """A failed enqueue on one setting should not prevent other settings from being processed."""
    space_id1, user_id1 = _make_space_and_user(db)
    space_id2, user_id2 = _make_space_and_user(db)
    space_id3, user_id3 = _make_space_and_user(db)

    setting1 = _make_setting(db, space_id1, user_id1)
    setting2 = _make_setting(db, space_id2, user_id2)
    setting3 = _make_setting(db, space_id3, user_id3)

    orig1 = setting1.next_run_at
    orig2 = setting2.next_run_at
    orig3 = setting3.next_run_at

    async def fail_for_space2(*args, **kwargs):
        payload = args[1] if len(args) > 1 else {}
        if payload.get("space_id") == space_id2:
            raise RuntimeError("simulated failure")

    queue = MagicMock()
    queue.enqueue = AsyncMock(side_effect=fail_for_space2)

    scheduler = DailyCaptureReportScheduler(db)
    asyncio.run(scheduler.scan_and_enqueue(queue))

    db.expire_all()
    db.refresh(setting1)
    db.refresh(setting2)
    db.refresh(setting3)

    # setting1 and setting3 must have advanced next_run_at (enqueued successfully)
    assert setting1.next_run_at > orig1, "setting1 should have been enqueued"
    assert setting3.next_run_at > orig3, "setting3 should have been enqueued despite setting2 failure"

    # setting2 must be unchanged (rollback after failure)
    assert setting2.next_run_at <= orig2 + timedelta(seconds=1), "setting2 next_run_at must not advance"


# ---------------------------------------------------------------------------
# 8. Invalid timezone setting is skipped; next_run_at not advanced
# ---------------------------------------------------------------------------

def test_invalid_timezone_setting_is_skipped(db):
    space_id, user_id = _make_space_and_user(db)
    # Bypass schema validation — directly write an invalid timezone to DB
    setting = _make_setting(db, space_id, user_id, enabled=True, timezone="Not/A/Timezone")
    original_next_run_at = setting.next_run_at

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)
    asyncio.run(scheduler.scan_and_enqueue(queue))

    # Verify our specific invalid-timezone setting was never enqueued
    for call in queue.enqueue.call_args_list:
        payload = call[0][1]
        assert payload.get("setting_id") != setting.id, \
            "Setting with invalid timezone must not be enqueued"

    # next_run_at must not have advanced
    db.expire(setting)
    db.refresh(setting)
    assert setting.next_run_at is not None
    assert setting.next_run_at <= original_next_run_at + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# 9. Scheduler enqueues with max_attempts=1
# ---------------------------------------------------------------------------

def test_scheduled_job_enqueued_with_max_attempts_1(db):
    space_id, user_id = _make_space_and_user(db)
    setting = _make_setting(db, space_id, user_id, enabled=True)

    queue = _make_queue()
    scheduler = DailyCaptureReportScheduler(db)
    asyncio.run(scheduler.scan_and_enqueue(queue))

    # Find the call for our specific setting
    our_call = None
    for call in queue.enqueue.call_args_list:
        payload = call[0][1]
        if payload.get("setting_id") == setting.id:
            our_call = call
            break

    assert our_call is not None
    assert our_call.kwargs.get("max_attempts") == 1


# ---------------------------------------------------------------------------
# 10. DST spring-forward: next_run_at computed correctly
# ---------------------------------------------------------------------------

def test_dst_spring_forward_next_run_at():
    """After DST spring-forward in America/New_York (2024-03-10), next slot is UTC-4."""
    from app.models import DailyCaptureReportSetting

    tz = ZoneInfo("America/New_York")
    # 2024-03-09 08:00 EST (UTC-5) = 13:00 UTC (day before spring-forward)
    slot_utc = datetime(2024, 3, 9, 13, 0, 0, tzinfo=UTC)

    setting = DailyCaptureReportSetting(
        id=_uid(),
        space_id="s",
        user_id="u",
        local_time="08:00",
        timezone="America/New_York",
        enabled=True,
        include_source_types_json=[],
        create_experience_proposals=True,
        create_memory_proposals=False,
        experience_confidence_threshold=0.75,
        memory_confidence_threshold=0.85,
        max_experience_proposals_per_day=5,
        max_memory_proposals_per_day=3,
    )

    next_utc = _compute_next_run_at_after_slot(slot_utc, setting, tz)

    # 2024-03-10 is DST spring-forward day (clocks: 2:00 → 3:00, UTC-5 → UTC-4)
    # 08:00 EDT on 2024-03-10 = 12:00 UTC (UTC-4 after spring-forward)
    assert next_utc == datetime(2024, 3, 10, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helper unit: _local_date_from_slot
# ---------------------------------------------------------------------------

def test_local_date_from_slot_converts_timezone():
    # 2000-01-15 23:00 UTC = 2000-01-16 09:00 in UTC+10
    slot_utc = datetime(2000, 1, 15, 23, 0, 0, tzinfo=UTC)
    assert _local_date_from_slot(slot_utc, ZoneInfo("Australia/Sydney")) == "2000-01-16"
    assert _local_date_from_slot(slot_utc, ZoneInfo("UTC")) == "2000-01-15"
