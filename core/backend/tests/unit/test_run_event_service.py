"""Unit tests for RunEventService and safe_append_run_event.

Tests verify:
- Append-only ordering (event_index increments monotonically)
- Cross-space isolation (events from another space are rejected)
- Invalid event_type and status rejection
- Redaction of error_message and metadata_json
- safe_append_run_event wrapper: catches exceptions, never poisons outer tx
- list_for_run and get_latest_for_run behavior
"""
from __future__ import annotations

import pytest

from app.models import RunEvent
from app.runs.events import RunEventService, safe_append_run_event, RUN_EVENT_TYPES, RUN_EVENT_STATUSES
from tests.support import factories


SPACE = "space-re-01"
SPACE_B = "space-re-02"
USER = "user-re-01"


def _setup(db):
    factories.create_test_space(db, space_id=SPACE)
    factories.create_test_space(db, space_id=SPACE_B)
    factories.create_test_user(db, space_id=SPACE, user_id=USER)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_run_event_types_is_frozenset_of_strings(self):
        assert isinstance(RUN_EVENT_TYPES, frozenset)
        assert all(isinstance(t, str) for t in RUN_EVENT_TYPES)
        assert "adapter_invoked" in RUN_EVENT_TYPES
        assert "patch_collected" in RUN_EVENT_TYPES
        assert "evaluation_created" in RUN_EVENT_TYPES

    def test_run_event_statuses_is_frozenset(self):
        assert isinstance(RUN_EVENT_STATUSES, frozenset)
        assert "warning" in RUN_EVENT_STATUSES
        assert "skipped" in RUN_EVENT_STATUSES


# ---------------------------------------------------------------------------
# append_event — ordering and basic persistence
# ---------------------------------------------------------------------------

class TestAppendEventOrdering:
    def test_first_event_gets_index_zero(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="context_compiled", status="succeeded",
        )
        db.flush()
        assert ev.event_index == 0

    def test_second_event_gets_index_one(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        db.flush()
        ev2 = svc.append_event(run_id=run.id, space_id=SPACE, event_type="runtime_selected", status="succeeded")
        db.flush()
        assert ev2.event_index == 1

    def test_events_for_different_runs_have_independent_indexes(self, db):
        _setup(db)
        run1 = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run2 = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)

        svc.append_event(run_id=run1.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        svc.append_event(run_id=run1.id, space_id=SPACE, event_type="runtime_selected", status="succeeded")
        db.flush()
        ev2_run2 = svc.append_event(run_id=run2.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        db.flush()

        assert ev2_run2.event_index == 0

    def test_event_fields_are_persisted(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="adapter_invoked", status="running",
            summary="adapter started",
            metadata_json={"adapter_type": "echo", "executor_mode": "local"},
        )
        db.flush()

        fetched = db.query(RunEvent).filter(RunEvent.id == ev.id).first()
        assert fetched is not None
        assert fetched.event_type == "adapter_invoked"
        assert fetched.status == "running"
        assert fetched.summary == "adapter started"
        assert fetched.metadata_json["adapter_type"] == "echo"


# ---------------------------------------------------------------------------
# Invalid type and status rejection
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_event_type_raises_value_error(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        with pytest.raises(ValueError, match="invalid event_type"):
            svc.append_event(run_id=run.id, space_id=SPACE, event_type="nonexistent_type", status="succeeded")

    def test_invalid_status_raises_value_error(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        with pytest.raises(ValueError, match="invalid status"):
            svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="bad_status")

    def test_all_valid_event_types_accepted(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        for etype in sorted(RUN_EVENT_TYPES):
            svc.append_event(run_id=run.id, space_id=SPACE, event_type=etype, status="succeeded")
        db.flush()
        count = db.query(RunEvent).filter(RunEvent.run_id == run.id).count()
        assert count == len(RUN_EVENT_TYPES)

    def test_all_valid_statuses_accepted(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        statuses = sorted(RUN_EVENT_STATUSES)
        for i, s in enumerate(statuses):
            svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status=s)
        db.flush()
        count = db.query(RunEvent).filter(RunEvent.run_id == run.id).count()
        assert count == len(statuses)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedaction:
    def test_error_message_is_redacted(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="adapter_completed", status="failed",
            error_message="failed: sk-ant-test-key-12345678 is invalid",
        )
        db.flush()
        assert "sk-ant-test-key" not in (ev.error_message or "")
        assert "[REDACTED]" in (ev.error_message or "")

    def test_metadata_sensitive_key_is_redacted(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="context_compiled", status="succeeded",
            metadata_json={"adapter_type": "echo", "api_key": "sk-secret-12345678"},
        )
        db.flush()
        assert ev.metadata_json is not None
        assert ev.metadata_json.get("api_key") == "[REDACTED]"
        assert ev.metadata_json.get("adapter_type") == "echo"

    def test_safe_metadata_is_preserved(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="patch_collected", status="succeeded",
            metadata_json={
                "proposal_created": True,
                "ops_count": 5,
                "skipped_count": 0,
                "incomplete_patch": False,
            },
        )
        db.flush()
        assert ev.metadata_json["proposal_created"] is True
        assert ev.metadata_json["ops_count"] == 5


# ---------------------------------------------------------------------------
# list_for_run and get_latest_for_run
# ---------------------------------------------------------------------------

class TestQuery:
    def test_list_for_run_returns_ordered_by_event_index(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="runtime_selected", status="succeeded")
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="adapter_invoked", status="running")
        db.flush()

        total, items = svc.list_for_run(run.id, SPACE)
        assert total == 3
        assert [e.event_type for e in items] == ["context_compiled", "runtime_selected", "adapter_invoked"]
        assert [e.event_index for e in items] == [0, 1, 2]

    def test_list_for_run_respects_space_isolation(self, db):
        _setup(db)
        run_a = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(run_id=run_a.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        db.flush()

        # Querying from a different space returns nothing
        total, items = svc.list_for_run(run_a.id, SPACE_B)
        assert total == 0
        assert items == []

    def test_get_latest_returns_last_event(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        svc.append_event(run_id=run.id, space_id=SPACE, event_type="runtime_selected", status="succeeded")
        db.flush()

        latest = svc.get_latest_for_run(run.id, SPACE)
        assert latest is not None
        assert latest.event_type == "runtime_selected"
        assert latest.event_index == 1

    def test_get_latest_returns_none_when_no_events(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        latest = svc.get_latest_for_run(run.id, SPACE)
        assert latest is None

    def test_list_for_run_pagination(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        for _ in range(5):
            svc.append_event(run_id=run.id, space_id=SPACE, event_type="context_compiled", status="succeeded")
        db.flush()

        total, page1 = svc.list_for_run(run.id, SPACE, limit=3, offset=0)
        _, page2 = svc.list_for_run(run.id, SPACE, limit=3, offset=3)
        assert total == 5
        assert len(page1) == 3
        assert len(page2) == 2
        assert page1[-1].event_index < page2[0].event_index


# ---------------------------------------------------------------------------
# safe_append_run_event — best-effort wrapper
# ---------------------------------------------------------------------------

class TestSafeWrapper:
    def test_safe_wrapper_returns_event_on_success(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        ev = safe_append_run_event(
            db,
            run_id=run.id, space_id=SPACE,
            event_type="context_compiled", status="succeeded",
            log_context="test",
        )
        db.flush()
        assert ev is not None
        assert ev.event_type == "context_compiled"

    def test_safe_wrapper_returns_none_on_invalid_type(self, db):
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        # Invalid event_type — should not raise, just return None
        result = safe_append_run_event(
            db,
            run_id=run.id, space_id=SPACE,
            event_type="not_a_real_type", status="succeeded",
            log_context="test",
        )
        assert result is None

    def test_safe_wrapper_does_not_raise_on_bad_run_id(self, db):
        _setup(db)
        # nonexistent run — should fail gracefully
        result = safe_append_run_event(
            db,
            run_id="nonexistent-run-id", space_id=SPACE,
            event_type="context_compiled", status="succeeded",
            log_context="test",
        )
        # Returns None (FK violation caught and logged)
        assert result is None

    def test_safe_wrapper_does_not_poison_outer_session(self, db):
        """A failed safe_append_run_event must not rollback the outer session."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        run.prompt = "test prompt"
        db.flush()

        # Write a bad event — should fail silently
        safe_append_run_event(
            db,
            run_id="bad-id", space_id=SPACE,
            event_type="not_valid", status="succeeded",
        )

        # Outer session must still be usable
        run_check = db.query(type(run)).filter_by(id=run.id).first()
        assert run_check is not None


# ---------------------------------------------------------------------------
# Append-only: no mutations after creation
# ---------------------------------------------------------------------------

class TestAppendOnly:
    def test_events_are_not_updated_after_creation(self, db):
        """Events should not be mutated after creation — append-only invariant."""
        _setup(db)
        run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
        svc = RunEventService(db)
        ev = svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="adapter_invoked", status="running",
        )
        db.flush()
        original_id = ev.id

        # Append a second event — the first must remain unchanged
        svc.append_event(
            run_id=run.id, space_id=SPACE,
            event_type="adapter_completed", status="succeeded",
        )
        db.flush()

        first = db.query(RunEvent).filter(RunEvent.id == original_id).first()
        assert first.event_type == "adapter_invoked"
        assert first.status == "running"
        assert first.event_index == 0
