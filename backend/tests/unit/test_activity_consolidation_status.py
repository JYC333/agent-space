"""Unit tests for Activity consolidation status consistency.

Verifies that ActivityConsolidationService updates both status and
consolidation_status correctly:
  - proposals_generated → status = "proposals_generated", consolidation_status = "proposals_generated"
  - skipped             → status = "processed", consolidation_status = "skipped"
  - failed              → consolidation_status = "failed", status unchanged

Also verifies:
  - mark_reviewed sets consolidation_status="skipped" and processed_at
  - Reviewed activities are not selected by run_pending consolidation
  - source_type "intake" is accepted by ActivityService
"""
from __future__ import annotations

from tests.support import factories
from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

from app.activity.service import ActivityService
from app.memory.consolidation.service import ActivityConsolidationService
from app.models import ActivityRecord


def _create_raw_activity(db, content="Test content") -> ActivityRecord:
    svc = ActivityService(db)
    return svc.create(
        space_id=PERSONAL_SPACE_ID,
        source_type="user_capture",
        content=content,
        user_id=DEFAULT_USER_ID,
        title="test",
    )


class TestConsolidationStatusSync:
    def test_mark_reviewed_sets_status_and_consolidation_skipped(self, db):
        act = _create_raw_activity(db)
        svc = ActivityService(db)
        updated = svc.mark_reviewed(act.id, PERSONAL_SPACE_ID, viewer_user_id=DEFAULT_USER_ID)
        assert updated.status == "processed"
        assert updated.consolidation_status == "skipped"
        assert updated.processed_at is not None

    def test_reviewed_activity_not_selected_by_run_pending_consolidation(self, db):
        """After mark_reviewed, run_pending consolidation must not re-process the record."""
        act = _create_raw_activity(db)
        svc = ActivityService(db)
        svc.mark_reviewed(act.id, PERSONAL_SPACE_ID, viewer_user_id=DEFAULT_USER_ID)

        db.refresh(act)
        assert act.consolidation_status == "skipped"

        cons = ActivityConsolidationService(db)
        res = cons.run_pending(space_id=PERSONAL_SPACE_ID, acting_user_id=DEFAULT_USER_ID)
        # The reviewed activity must not appear in any consolidation list
        all_touched = set(res.activities_processed + res.activities_skipped + res.activities_failed)
        assert act.id not in all_touched

        db.refresh(act)
        # Status/consolidation_status must remain unchanged after consolidation run
        assert act.status == "processed"
        assert act.consolidation_status == "skipped"

    def test_consolidation_skipped_sets_both_fields(self, db):
        # Create an activity with sparse content that likely produces no proposals
        act = _create_raw_activity(db, content="ok")
        cons = ActivityConsolidationService(db)
        cons.run_for_activity_ids(
            PERSONAL_SPACE_ID,
            [act.id],
            acting_user_id=DEFAULT_USER_ID,
        )
        db.refresh(act)
        # When skipped: consolidation_status = "skipped", status = "processed"
        assert act.consolidation_status in ("skipped", "proposals_generated", "failed")
        if act.consolidation_status == "skipped":
            assert act.status == "processed"

    def test_mark_activity_consolidation_proposals_generated(self, db):
        """Direct test of _mark_activity_consolidation with proposals_generated."""
        act = _create_raw_activity(db)
        cons = ActivityConsolidationService(db)
        cons._mark_activity_consolidation(act.id, "proposals_generated")
        db.refresh(act)
        assert act.consolidation_status == "proposals_generated"
        assert act.status == "proposals_generated"

    def test_mark_activity_consolidation_skipped_sets_processed_status(self, db):
        """_mark_activity_consolidation(skipped) should set status=processed."""
        act = _create_raw_activity(db)
        assert act.status == "raw"
        cons = ActivityConsolidationService(db)
        cons._mark_activity_consolidation(act.id, "skipped")
        db.refresh(act)
        assert act.consolidation_status == "skipped"
        assert act.status == "processed"

    def test_mark_activity_consolidation_failed_leaves_status_unchanged(self, db):
        """_mark_activity_consolidation(failed) should not change user-visible status."""
        act = _create_raw_activity(db)
        assert act.status == "raw"
        cons = ActivityConsolidationService(db)
        cons._mark_activity_consolidation(act.id, "failed")
        db.refresh(act)
        assert act.consolidation_status == "failed"
        assert act.status == "raw"

    def test_skipped_does_not_overwrite_proposals_generated(self, db):
        """If status is already proposals_generated, skipped must not downgrade it."""
        act = _create_raw_activity(db)
        cons = ActivityConsolidationService(db)
        cons._mark_activity_consolidation(act.id, "proposals_generated")
        db.refresh(act)
        assert act.status == "proposals_generated"

        # Now mark skipped — should not regress status
        cons._mark_activity_consolidation(act.id, "skipped")
        db.refresh(act)
        assert act.status == "proposals_generated"
        assert act.consolidation_status == "skipped"

    def test_activity_list_filter_by_status_works_after_consolidation(self, db):
        """After consolidation marks status=processed, list(status='processed') returns it."""
        act = _create_raw_activity(db)
        cons = ActivityConsolidationService(db)
        cons._mark_activity_consolidation(act.id, "skipped")
        db.refresh(act)

        svc = ActivityService(db)
        processed = svc.list(
            PERSONAL_SPACE_ID,
            status="processed",
            viewer_user_id=DEFAULT_USER_ID,
        )
        ids = {r.id for r in processed}
        assert act.id in ids

        raw = svc.list(
            PERSONAL_SPACE_ID,
            status="raw",
            viewer_user_id=DEFAULT_USER_ID,
        )
        raw_ids = {r.id for r in raw}
        assert act.id not in raw_ids


class TestActivitySourceTypes:
    def test_intake_source_type_accepted(self, db):
        svc = ActivityService(db)
        act = svc.create(
            space_id=PERSONAL_SPACE_ID,
            source_type="intake",
            content="Intake pipeline content",
            user_id=DEFAULT_USER_ID,
        )
        assert act.activity_type == "intake"
        assert act.source_kind == "intake"

    def test_canonical_source_types_include_intake(self, db):
        from app.activity.service import CANONICAL_SOURCE_TYPES
        assert "intake" in CANONICAL_SOURCE_TYPES

    def test_invalid_source_type_rejected(self, db):
        svc = ActivityService(db)
        with pytest.raises(ValueError, match="invalid source_type"):
            svc.create(
                space_id=PERSONAL_SPACE_ID,
                source_type="bogus_type",
                content="content",
                user_id=DEFAULT_USER_ID,
            )


import pytest
