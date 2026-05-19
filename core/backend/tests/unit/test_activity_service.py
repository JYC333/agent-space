"""Unit tests: ActivityService.create() occurred_at behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.support import factories
from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

from app.activity.service import ActivityService


def test_create_uses_insertion_time_when_occurred_at_omitted(db):
    before = datetime.now(UTC)
    svc = ActivityService(db)
    record = svc.create(
        space_id=PERSONAL_SPACE_ID,
        source_type="user_capture",
        content="no explicit time",
        user_id=DEFAULT_USER_ID,
    )
    after = datetime.now(UTC)
    occ = record.occurred_at
    if occ.tzinfo is None:
        occ = occ.replace(tzinfo=UTC)
    assert before <= occ <= after


def test_create_preserves_explicit_occurred_at(db):
    past = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    svc = ActivityService(db)
    record = svc.create(
        space_id=PERSONAL_SPACE_ID,
        source_type="file_import",
        content="historical import",
        user_id=DEFAULT_USER_ID,
        occurred_at=past,
    )
    occ = record.occurred_at
    if occ.tzinfo is None:
        occ = occ.replace(tzinfo=UTC)
    assert abs((occ - past).total_seconds()) < 1


def test_create_explicit_occurred_at_differs_from_created_at(db):
    past = datetime(2023, 6, 1, 8, 0, 0, tzinfo=UTC)
    svc = ActivityService(db)
    record = svc.create(
        space_id=PERSONAL_SPACE_ID,
        source_type="external_source",
        content="old event",
        user_id=DEFAULT_USER_ID,
        occurred_at=past,
    )
    occ = record.occurred_at
    if occ.tzinfo is None:
        occ = occ.replace(tzinfo=UTC)
    assert abs((occ - past).total_seconds()) < 1
    # created_at should be close to now, not to the past occurred_at
    created = record.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    assert (created - past).total_seconds() > 60
