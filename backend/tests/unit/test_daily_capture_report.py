"""Unit tests for DailyCaptureReportService and DailyCaptureReportSettingsService.

Uses unique space IDs per test-group to avoid cross-test interference (the
db_engine is session-scoped; data persists across tests within one session).

Covers:
  1. DailyCaptureReportSetting validation and persistence.
  2. Daily selector picks only that local day's user_capture rows.
  3. Manual run with no captures returns skipped.
  4. Successful daily report creates Run + daily_capture_report Artifact.
  5. Report Artifact has source_activity_ids, report_date, timezone metadata.
  6. Experience proposals created only when enabled and above threshold.
  7. Memory proposals created only when enabled and above threshold.
  8. create_memory_proposals=False creates no memory proposals.
  9. No MemoryEntry/KnowledgeItem written before proposal acceptance.
 10. Accepting a memory proposal creates MemoryEntry.
 11. Accepting an experience proposal creates KnowledgeItem item_type=experience.
 12. Re-running same date without force returns skipped.
 13. Provider missing marks run failed, no artifact/proposals.
 14. Invalid LLM JSON marks run failed, no artifact.
 15. Memory proposal provenance is user_confirmed; artifact not trust-bearing.
"""
from __future__ import annotations
import uuid

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.activity.service import ActivityService
from app.daily_reports.service import (
    DailyCaptureReportService,
    DailyCaptureReportSettingsService,
)
from app.proposals import ProposalService
from app.models import (
    Artifact,
    DailyCaptureReportSetting,
    KnowledgeItem,
    MemoryEntry,
    Proposal,
    Run,
    Space,
    SpaceMembership,
    User,
)

from app.providers.invocation import CompletionResult as _CompletionResult


def _CR(text):
    return _CompletionResult(text=text, model="gpt-4o-mini")


_FAKE_PROVIDER_TUPLE = ("prov-test", None)


def _uid() -> str:
    return str(uuid.uuid4())


def _make_space_and_user(db) -> tuple[str, str]:
    """Create an isolated space + user for one test."""
    user_id = _uid()
    space_id = _uid()
    user = User(id=user_id, display_name="Test", status="active")
    space = Space(id=space_id, name="Test Space", type="personal", created_by_user_id=user_id)
    ms = SpaceMembership(id=_uid(), space_id=space_id, user_id=user_id, role="owner", status="active")
    db.add(user)
    db.flush()
    db.add(space)
    db.flush()
    db.add(ms)
    db.commit()
    return space_id, user_id


def _make_capture(db, space_id: str, user_id: str, content="Test capture", occurred_at=None):
    if occurred_at is None:
        occurred_at = datetime(2000, 1, 15, 10, 0, 0, tzinfo=UTC)
    svc = ActivityService(db)
    return svc.create(
        space_id=space_id,
        source_type="user_capture",
        content=content,
        user_id=user_id,
        title="Test capture",
        occurred_at=occurred_at,
    )


def _get_setting(db, space_id: str, user_id: str) -> DailyCaptureReportSetting:
    return DailyCaptureReportSettingsService(db).get_or_create(space_id, user_id)


def _structured_json(themes=None) -> str:
    return json.dumps({
        "report_title": "Daily Report",
        "overview": "A productive day.",
        "themes": themes or [],
        "ideas": [],
        "decisions": [],
        "open_questions": [],
        "experience_candidates": [],
        "memory_candidates": [],
    })


def _structured_with_experience(activity_id: str, confidence: float) -> str:
    return json.dumps({
        "report_title": "Test",
        "overview": "Overview.",
        "themes": [],
        "ideas": [],
        "decisions": [],
        "open_questions": [],
        "experience_candidates": [
            {
                "title": "Learned something",
                "content": "I learned X.",
                "confidence": confidence,
                "source_activity_ids": [activity_id],
            }
        ],
        "memory_candidates": [],
    })


def _structured_with_memory(activity_id: str, confidence: float) -> str:
    return json.dumps({
        "report_title": "Test",
        "overview": "Overview.",
        "themes": [],
        "ideas": [],
        "decisions": [],
        "open_questions": [],
        "experience_candidates": [],
        "memory_candidates": [
            {
                "title": "Key fact",
                "content": "I know X.",
                "memory_type": "semantic",
                "confidence": confidence,
                "source_activity_ids": [activity_id],
            }
        ],
    })


_TEST_DATE = "2000-01-15"
_TEST_DATE_OCC = datetime(2000, 1, 15, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Settings validation and persistence
# ---------------------------------------------------------------------------

def test_setting_created_with_defaults(db):
    space_id, user_id = _make_space_and_user(db)
    setting = _get_setting(db, space_id, user_id)
    assert setting.enabled is False
    assert setting.local_time == "08:00"
    assert setting.timezone == "UTC"
    assert setting.create_experience_proposals is True
    assert setting.create_memory_proposals is False
    assert setting.experience_confidence_threshold == 0.75
    assert setting.memory_confidence_threshold == 0.85
    assert setting.max_experience_proposals_per_day == 5
    assert setting.max_memory_proposals_per_day == 3


def test_setting_update_persists(db):
    space_id, user_id = _make_space_and_user(db)
    svc = DailyCaptureReportSettingsService(db)
    svc.get_or_create(space_id, user_id)
    updated = svc.update(space_id, user_id, {
        "enabled": True,
        "local_time": "09:00",
        "timezone": "America/New_York",
        "create_memory_proposals": True,
        "memory_confidence_threshold": 0.90,
    })
    assert updated.enabled is True
    assert updated.local_time == "09:00"
    assert updated.timezone == "America/New_York"
    assert updated.create_memory_proposals is True
    assert updated.memory_confidence_threshold == 0.90


def test_setting_idempotent_get_or_create(db):
    space_id, user_id = _make_space_and_user(db)
    svc = DailyCaptureReportSettingsService(db)
    s1 = svc.get_or_create(space_id, user_id)
    s2 = svc.get_or_create(space_id, user_id)
    assert s1.id == s2.id


# ---------------------------------------------------------------------------
# Capture selection
# ---------------------------------------------------------------------------

def test_selector_picks_only_local_day_captures(db):
    space_id, user_id = _make_space_and_user(db)
    # In-range: 2000-01-15 UTC
    cap_in = _make_capture(db, space_id, user_id, occurred_at=datetime(2000, 1, 15, 14, 0, 0, tzinfo=UTC))
    # Out-of-range: 2000-01-16 UTC
    cap_out = _make_capture(db, space_id, user_id, occurred_at=datetime(2000, 1, 16, 2, 0, 0, tzinfo=UTC))

    svc = DailyCaptureReportService(db)
    from datetime import date
    captures = svc.select_captures_for_date(
        space_id=space_id,
        user_id=user_id,
        local_date=date(2000, 1, 15),
        timezone="UTC",
    )
    ids = [c.id for c in captures]
    assert cap_in.id in ids
    assert cap_out.id not in ids


def test_selector_excludes_archived(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    ActivityService(db).mark_archived(cap.id, space_id)

    svc = DailyCaptureReportService(db)
    from datetime import date
    captures = svc.select_captures_for_date(
        space_id=space_id,
        user_id=user_id,
        local_date=date(2000, 1, 15),
        timezone="UTC",
    )
    assert cap.id not in [c.id for c in captures]


# ---------------------------------------------------------------------------
# Manual run — no captures
# ---------------------------------------------------------------------------

def test_run_with_no_captures_returns_skipped(db):
    space_id, user_id = _make_space_and_user(db)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
            trigger_origin="manual",
        )

    assert result.status == "skipped"
    assert result.capture_count == 0
    assert result.artifact_id is None


# ---------------------------------------------------------------------------
# Successful run: Run + Artifact
# ---------------------------------------------------------------------------

def test_successful_run_creates_run_and_artifact(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_json())):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
            trigger_origin="manual",
        )

    assert result.status == "succeeded"
    assert result.run_id
    assert result.artifact_id
    assert result.capture_count == 1

    run = db.query(Run).filter(Run.id == result.run_id).first()
    assert run is not None
    assert run.status == "succeeded"
    assert run.run_type == "reflection"

    artifact = db.query(Artifact).filter(Artifact.id == result.artifact_id).first()
    assert artifact is not None
    assert artifact.artifact_type == "daily_capture_report"
    assert artifact.run_id == result.run_id


def test_artifact_metadata_contains_required_fields(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_json())):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    artifact = db.query(Artifact).filter(Artifact.id == result.artifact_id).first()
    meta = artifact.metadata_json or {}
    assert meta["report_type"] == "daily_capture_report"
    assert meta["report_date"] == _TEST_DATE
    assert meta["timezone"] == "UTC"  # default timezone
    assert cap.id in meta["source_activity_ids"]
    assert meta["capture_count"] == 1
    assert "structured_report" in meta


# ---------------------------------------------------------------------------
# Experience proposals
# ---------------------------------------------------------------------------

def test_experience_proposals_created_when_enabled_and_above_threshold(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_experience_proposals = True
    setting.experience_confidence_threshold = 0.70
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_experience(cap.id, 0.80))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert len(result.experience_proposal_ids) == 1
    prop = db.query(Proposal).filter(Proposal.id == result.experience_proposal_ids[0]).first()
    assert prop.proposal_type == "knowledge_create"
    payload = prop.payload_json or {}
    assert payload.get("item_type") == "summary"
    assert payload.get("verification_status") == "unverified"
    assert "daily-capture-report" in payload.get("tags", [])


def test_experience_proposals_skipped_below_threshold(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_experience_proposals = True
    setting.experience_confidence_threshold = 0.90
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_experience(cap.id, 0.75))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert len(result.experience_proposal_ids) == 0


def test_accepting_experience_proposal_creates_knowledge_item(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_experience_proposals = True
    setting.experience_confidence_threshold = 0.70
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_experience(cap.id, 0.80))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    prop_id = result.experience_proposal_ids[0]
    accept_result = ProposalService(db).accept(prop_id, space_id=space_id, user_id=user_id)
    assert accept_result.knowledge_item is not None
    assert accept_result.knowledge_item.item_type == "summary"
    assert db.query(KnowledgeItem).filter(KnowledgeItem.space_id == space_id).count() == 1


# ---------------------------------------------------------------------------
# Memory proposals
# ---------------------------------------------------------------------------

def test_memory_proposals_not_created_when_disabled(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_memory_proposals = False
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_memory(cap.id, 0.90))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert len(result.memory_proposal_ids) == 0


def test_memory_proposals_created_when_enabled_and_above_threshold(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_memory_proposals = True
    setting.memory_confidence_threshold = 0.80
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_memory(cap.id, 0.90))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert len(result.memory_proposal_ids) == 1
    prop = db.query(Proposal).filter(Proposal.id == result.memory_proposal_ids[0]).first()
    assert prop.proposal_type == "memory_create"
    assert prop.status == "pending"
    # Provenance must be user_confirmed (not artifact/run_step)
    prov = (prop.payload_json or {}).get("provenance_entries", [])
    prov_types = [e.get("source_type") for e in prov]
    assert "artifact" not in prov_types
    assert "run_step" not in prov_types
    activity_prov = [e for e in prov if e.get("source_type") == "activity"]
    assert len(activity_prov) >= 1
    for e in activity_prov:
        assert e.get("source_trust") == "user_confirmed"


def test_no_direct_memory_or_knowledge_before_acceptance(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_memory_proposals = True
    setting.memory_confidence_threshold = 0.50
    setting.create_experience_proposals = True
    setting.experience_confidence_threshold = 0.50
    db.commit()

    llm_json = json.loads(_structured_with_memory(cap.id, 0.80))
    llm_json["experience_candidates"] = [
        {"title": "Exp", "content": "Exp content", "confidence": 0.80, "source_activity_ids": [cap.id]}
    ]

    memory_before = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    knowledge_before = db.query(KnowledgeItem).filter(KnowledgeItem.space_id == space_id).count()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(json.dumps(llm_json))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count() == memory_before
    assert db.query(KnowledgeItem).filter(KnowledgeItem.space_id == space_id).count() == knowledge_before


def test_accepting_memory_proposal_creates_memory_entry(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_memory_proposals = True
    setting.memory_confidence_threshold = 0.80
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_memory(cap.id, 0.90))):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    prop_id = result.memory_proposal_ids[0]
    accept_result = ProposalService(db).accept(prop_id, space_id=space_id, user_id=user_id)
    assert accept_result.memory is not None
    assert db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count() == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_rerun_same_date_without_force_returns_existing(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_json())):
        result1 = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    artifact_count = db.query(Artifact).filter(
        Artifact.space_id == space_id,
        Artifact.artifact_type == "daily_capture_report",
    ).count()

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_json())):
        result2 = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
            force=False,
        )

    assert result2.status == "skipped"
    assert result2.skipped is True
    assert db.query(Artifact).filter(
        Artifact.space_id == space_id,
        Artifact.artifact_type == "daily_capture_report",
    ).count() == artifact_count


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------

def test_provider_missing_marks_result_failed_no_artifact(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    from app.memory.provider_client import ReflectorModelProviderMissingError

    with patch(
        "app.daily_reports.service.resolve_reflector_provider_id",
        side_effect=ReflectorModelProviderMissingError("no provider"),
    ):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert result.status == "failed"
    assert result.artifact_id is None
    assert len(result.proposal_ids) == 0
    # A failed Run is created so users can inspect the failed attempt
    assert result.run_id
    run = db.query(Run).filter(Run.id == result.run_id).first()
    assert run is not None
    assert run.status == "failed"


def test_provider_missing_no_captures_returns_skipped_without_provider(db):
    """When there are 0 captures, the report skips without requiring a provider."""
    space_id, user_id = _make_space_and_user(db)
    # No captures created for _TEST_DATE
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    # resolve_reflector_provider is never called when captures == 0
    from app.memory.provider_client import ReflectorModelProviderMissingError

    with patch(
        "app.daily_reports.service.resolve_reflector_provider_id",
        side_effect=ReflectorModelProviderMissingError("should not be called"),
    ) as mock_provider:
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert result.status == "skipped"
    assert result.capture_count == 0
    mock_provider.assert_not_called()


def test_invalid_llm_json_marks_run_failed_no_artifact(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    svc = DailyCaptureReportService(db)

    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR("not valid json at all")):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert result.status == "failed"
    assert result.artifact_id is None
    run = db.query(Run).filter(Run.id == result.run_id).first()
    assert run.status == "failed"


# ---------------------------------------------------------------------------
# Strict validation (schema-level; no DB needed)
# ---------------------------------------------------------------------------

import pydantic

def test_invalid_local_time_format_raises():
    with pytest.raises(pydantic.ValidationError):
        from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
        DailyCaptureReportSettingUpdate(local_time="9:00")  # missing leading zero


def test_invalid_local_time_hour_raises():
    with pytest.raises(pydantic.ValidationError):
        from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
        DailyCaptureReportSettingUpdate(local_time="25:00")


def test_invalid_local_time_minute_raises():
    with pytest.raises(pydantic.ValidationError):
        from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
        DailyCaptureReportSettingUpdate(local_time="08:60")


def test_invalid_timezone_raises():
    with pytest.raises(pydantic.ValidationError):
        from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
        DailyCaptureReportSettingUpdate(timezone="Not/AReal/Timezone")


def test_valid_timezone_accepted():
    from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
    u = DailyCaptureReportSettingUpdate(timezone="America/New_York")
    assert u.timezone == "America/New_York"


def test_invalid_source_type_raises():
    with pytest.raises(pydantic.ValidationError):
        from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
        DailyCaptureReportSettingUpdate(include_source_types=["user_capture", "unknown_type"])


def test_valid_source_types_accepted():
    from app.daily_reports.schemas import DailyCaptureReportSettingUpdate
    u = DailyCaptureReportSettingUpdate(include_source_types=["user_capture"])
    assert u.include_source_types == ["user_capture"]


# ---------------------------------------------------------------------------
# Guard candidate source refs: empty source_activity_ids dropped
# ---------------------------------------------------------------------------

def _structured_with_empty_source_ids() -> str:
    return json.dumps({
        "report_title": "Test",
        "overview": "Overview.",
        "themes": [],
        "ideas": [],
        "decisions": [],
        "open_questions": [],
        "experience_candidates": [
            {
                "title": "Empty source exp",
                "content": "No sources.",
                "confidence": 0.90,
                "source_activity_ids": [],  # empty — should be dropped
            }
        ],
        "memory_candidates": [
            {
                "title": "Empty source mem",
                "content": "No sources.",
                "memory_type": "semantic",
                "confidence": 0.90,
                "source_activity_ids": [],  # empty — should be dropped
            }
        ],
    })


def test_empty_source_activity_ids_drops_experience_candidate(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_experience_proposals = True
    setting.experience_confidence_threshold = 0.50
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_empty_source_ids())):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    # Candidate with empty source_activity_ids must be dropped
    assert len(result.experience_proposal_ids) == 0


def test_empty_source_activity_ids_drops_memory_candidate(db):
    space_id, user_id = _make_space_and_user(db)
    cap = _make_capture(db, space_id, user_id, occurred_at=_TEST_DATE_OCC)
    setting = _get_setting(db, space_id, user_id)
    setting.create_memory_proposals = True
    setting.memory_confidence_threshold = 0.50
    db.commit()

    svc = DailyCaptureReportService(db)
    with patch("app.daily_reports.service.resolve_reflector_provider_id", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.daily_reports.service.complete_text", return_value=_CR(_structured_with_empty_source_ids())):
        result = svc.generate_for_date(
            space_id=space_id,
            user_id=user_id,
            setting=setting,
            local_date=_TEST_DATE,
        )

    assert len(result.memory_proposal_ids) == 0
