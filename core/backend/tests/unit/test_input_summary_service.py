"""Unit tests for InputSummaryService.

Covers:
  1. Creates Run + Artifact linked together from ActivityRecord content.
  2. Run status becomes succeeded on success.
  3. Run status becomes failed on provider failure; no success Artifact/proposals created.
  4. Artifact.run_id links back to the Run.
  5. Creates canonical memory_create proposal when requested; proposal can be accepted.
  6. Creates canonical knowledge_create proposal when requested; proposal can be accepted.
  7. Never writes Memory or Knowledge directly before proposal acceptance.
  8. Missing ModelProvider raises InputSummaryProviderMissingError.
  9. Cross-space IDs raise InputSummaryCrossSpaceError.
 10. Empty content raises InputSummaryNoContentError.
 11. IntakeItem with evidence uses evidence content in preference to title/excerpt.
 12. IntakeItem with only title produces bounded metadata-only summary block.
 13. SummaryRunResult includes run_id.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.support import factories
from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID

from app.activity.input_summary_service import (
    InputSummaryCrossSpaceError,
    InputSummaryNoContentError,
    InputSummaryProviderMissingError,
    InputSummaryProviderCallError,
    InputSummaryService,
)
from app.activity.service import ActivityService
from app.memory.proposals import ProposalService
from app.models import Artifact, KnowledgeItem, MemoryEntry, Proposal, Run


_FAKE_PROVIDER_TUPLE = ("openai", None, "gpt-4o-mini", "test-key")
_FAKE_SUMMARY = "This is a deterministic test summary."


def _make_activity(db, content="Test activity content", title="Test", space_id=PERSONAL_SPACE_ID):
    svc = ActivityService(db)
    return svc.create(
        space_id=space_id,
        source_type="user_capture",
        content=content,
        user_id=DEFAULT_USER_ID,
        title=title,
    )


# ---------------------------------------------------------------------------
# Run + Artifact basics
# ---------------------------------------------------------------------------

def test_creates_run_and_artifact_from_activity(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
        )

    assert result.status == "succeeded"
    assert result.run_id
    assert result.artifact_id

    run = db.query(Run).filter(Run.id == result.run_id).first()
    assert run is not None
    assert run.status == "succeeded"
    assert run.run_type == "reflection"
    assert run.space_id == PERSONAL_SPACE_ID

    artifact = db.query(Artifact).filter(Artifact.id == result.artifact_id).first()
    assert artifact is not None
    assert artifact.artifact_type == "summary"
    assert artifact.content == _FAKE_SUMMARY
    assert artifact.space_id == PERSONAL_SPACE_ID
    assert artifact.run_id == result.run_id


def test_run_status_succeeded_on_success(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID, activity_ids=[act.id])

    run = db.query(Run).filter(Run.id == result.run_id).first()
    assert run.status == "succeeded"
    assert run.ended_at is not None


def test_run_status_failed_on_provider_error_no_artifact(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    runs_before = db.query(Run).filter(Run.space_id == PERSONAL_SPACE_ID, Run.run_type == "reflection").count()
    artifacts_before = db.query(Artifact).filter(
        Artifact.space_id == PERSONAL_SPACE_ID, Artifact.artifact_type == "summary"
    ).count()

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", side_effect=RuntimeError("network error")):
        with pytest.raises(InputSummaryProviderCallError):
            svc.run(space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID, activity_ids=[act.id])

    db.expire_all()

    # One more run was created, and it is failed (get the most-recently created one)
    run = (
        db.query(Run)
        .filter(Run.space_id == PERSONAL_SPACE_ID, Run.run_type == "reflection")
        .order_by(Run.created_at.desc())
        .first()
    )
    assert run is not None
    assert run.status == "failed"
    assert run.error_message is not None
    assert db.query(Run).filter(Run.space_id == PERSONAL_SPACE_ID, Run.run_type == "reflection").count() == runs_before + 1

    # No new summary artifact was created
    assert db.query(Artifact).filter(
        Artifact.space_id == PERSONAL_SPACE_ID, Artifact.artifact_type == "summary"
    ).count() == artifacts_before

    # No proposals for this run
    proposals = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
    assert len(proposals) == 0


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

def test_creates_memory_proposal_when_requested(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_memory_proposal=True,
        )

    assert len(result.proposal_ids) == 1
    prop = db.query(Proposal).filter(Proposal.id == result.proposal_ids[0]).first()
    assert prop is not None
    assert prop.proposal_type == "memory_create"
    assert prop.status == "pending"
    assert prop.created_by_run_id == result.run_id
    # Provenance entries must exist for source monitoring to allow accept
    prov = (prop.payload_json or {}).get("provenance_entries", [])
    assert len(prov) >= 1


def test_memory_proposal_can_be_accepted(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_memory_proposal=True,
        )

    prop_id = result.proposal_ids[0]
    # Use ProposalService.accept (the API surface) so source monitoring runs correctly
    accept_result = ProposalService(db).accept(
        prop_id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )
    assert accept_result.memory is not None
    assert accept_result.memory.space_id == PERSONAL_SPACE_ID

    # MemoryEntry linked back through proposal/artifact/run provenance
    assert db.query(MemoryEntry).filter(MemoryEntry.space_id == PERSONAL_SPACE_ID).count() == 1


def test_creates_knowledge_proposal_when_requested(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_knowledge_proposal=True,
        )

    assert len(result.proposal_ids) == 1
    prop = db.query(Proposal).filter(Proposal.id == result.proposal_ids[0]).first()
    assert prop.proposal_type == "knowledge_create"
    assert prop.status == "pending"
    assert prop.created_by_run_id == result.run_id
    payload = prop.payload_json or {}
    assert payload.get("operation") == "create"
    assert payload.get("title")
    assert payload.get("content")
    assert payload.get("verification_status") == "unverified"
    assert payload.get("reflection_status") == "unreviewed"


def test_knowledge_proposal_can_be_accepted(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_knowledge_proposal=True,
        )

    prop_id = result.proposal_ids[0]
    accept_result = ProposalService(db).accept(
        prop_id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )
    assert accept_result.knowledge_item is not None
    assert accept_result.knowledge_item.space_id == PERSONAL_SPACE_ID
    assert accept_result.knowledge_item.source_artifact_id == result.artifact_id
    assert accept_result.knowledge_item.created_by_run_id == result.run_id

    assert db.query(KnowledgeItem).filter(KnowledgeItem.space_id == PERSONAL_SPACE_ID).count() == 1


def test_creates_both_proposals_when_both_requested(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_memory_proposal=True,
            create_knowledge_proposal=True,
        )

    assert len(result.proposal_ids) == 2
    types = {
        db.query(Proposal).filter(Proposal.id == pid).first().proposal_type
        for pid in result.proposal_ids
    }
    assert "memory_create" in types
    assert "knowledge_create" in types


def test_no_proposals_created_by_default(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
        )

    assert result.proposal_ids == []


def test_never_writes_memory_or_knowledge_directly(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    memory_before = db.query(MemoryEntry).filter(MemoryEntry.space_id == PERSONAL_SPACE_ID).count()
    knowledge_before = db.query(KnowledgeItem).filter(KnowledgeItem.space_id == PERSONAL_SPACE_ID).count()

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_memory_proposal=True,
            create_knowledge_proposal=True,
        )

    # Proposals are pending, not applied
    for pid in result.proposal_ids:
        prop = db.query(Proposal).filter(Proposal.id == pid).first()
        assert prop.status == "pending"

    # No direct Memory or Knowledge rows written (count unchanged)
    assert db.query(MemoryEntry).filter(MemoryEntry.space_id == PERSONAL_SPACE_ID).count() == memory_before
    assert db.query(KnowledgeItem).filter(KnowledgeItem.space_id == PERSONAL_SPACE_ID).count() == knowledge_before


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_provider_call_failure_raises_call_error_not_missing(db):
    """Provider call failure raises InputSummaryProviderCallError, not MissingError."""
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", side_effect=RuntimeError("timeout")):
        with pytest.raises(InputSummaryProviderCallError):
            svc.run(space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID, activity_ids=[act.id])


def test_missing_provider_raises_typed_error(db):
    act = _make_activity(db)
    svc = InputSummaryService(db)

    from app.memory.provider_client import ReflectorModelProviderMissingError

    with patch(
        "app.activity.input_summary_service.resolve_reflector_provider",
        side_effect=ReflectorModelProviderMissingError("no provider"),
    ):
        with pytest.raises(InputSummaryProviderMissingError):
            svc.run(
                space_id=PERSONAL_SPACE_ID,
                user_id=DEFAULT_USER_ID,
                activity_ids=[act.id],
            )


def test_cross_space_activity_raises_error(db):
    other_space = "other-space-id"
    act = _make_activity(db, space_id=PERSONAL_SPACE_ID)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        with pytest.raises(InputSummaryCrossSpaceError):
            svc.run(
                space_id=other_space,
                user_id=DEFAULT_USER_ID,
                activity_ids=[act.id],
            )


def test_empty_content_raises_no_content_error(db):
    svc_act = ActivityService(db)
    act = svc_act.create(
        space_id=PERSONAL_SPACE_ID,
        source_type="user_capture",
        content="   ",
        user_id=DEFAULT_USER_ID,
    )
    summary_svc = InputSummaryService(db)
    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE):
        with pytest.raises(InputSummaryNoContentError):
            summary_svc.run(
                space_id=PERSONAL_SPACE_ID,
                user_id=DEFAULT_USER_ID,
                activity_ids=[act.id],
            )


# ---------------------------------------------------------------------------
# IntakeItem content resolution
# ---------------------------------------------------------------------------

def test_intake_item_with_evidence_uses_evidence_content(db):
    from app.intake.service import IntakeService
    from app.models import IntakeItem, ExtractedEvidence
    from ulid import ULID

    svc_intake = IntakeService(db)

    # Create IntakeItem
    item = IntakeItem(
        id=str(ULID()),
        space_id=PERSONAL_SPACE_ID,
        item_type="external_url",
        title="Test Article",
        status="new",
        excerpt=None,
    )
    db.add(item)
    db.flush()

    # Create evidence linked to item
    evidence = svc_intake.create_evidence(
        space_id=PERSONAL_SPACE_ID,
        intake_item_id=item.id,
        source_object_type=None,
        source_object_id=None,
        evidence_type="excerpt",
        title="Evidence from article",
        content_excerpt="This is the rich evidence content from the article.",
        created_by_user_id=DEFAULT_USER_ID,
    )
    db.commit()

    summary_svc = InputSummaryService(db)
    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY) as mock_llm:
        result = summary_svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            intake_item_ids=[item.id],
        )

    # Check that the evidence content reached the LLM call
    call_args = mock_llm.call_args
    user_prompt = call_args[0][5]  # 6th positional arg to call_reflector_llm
    assert "evidence content from the article" in user_prompt
    assert result.artifact_id


def test_intake_item_title_only_produces_metadata_only_block(db):
    from app.models import IntakeItem
    from ulid import ULID

    item = IntakeItem(
        id=str(ULID()),
        space_id=PERSONAL_SPACE_ID,
        item_type="external_url",
        title="Just a title",
        status="new",
        excerpt=None,
    )
    db.add(item)
    db.commit()

    summary_svc = InputSummaryService(db)
    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY) as mock_llm:
        result = summary_svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            intake_item_ids=[item.id],
        )

    # metadata_only flag set in source_refs
    artifact = db.query(Artifact).filter(Artifact.id == result.artifact_id).first()
    source_refs = (artifact.metadata_json or {}).get("source_refs", [])
    item_ref = next((r for r in source_refs if r.get("id") == item.id), None)
    assert item_ref is not None
    assert item_ref.get("metadata_only") is True

    # "[metadata only]" was sent to LLM
    user_prompt = mock_llm.call_args[0][5]
    assert "metadata only" in user_prompt


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_memory_proposal_provenance_does_not_include_artifact_as_trusted(db):
    """Artifact and run must not appear as internal_system trust-bearing provenance entries."""
    act = _make_activity(db)
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=_FAKE_SUMMARY):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
            create_memory_proposal=True,
        )

    prop = db.query(Proposal).filter(Proposal.id == result.proposal_ids[0]).first()
    prov = (prop.payload_json or {}).get("provenance_entries", [])

    # No provenance entry should have source_type="artifact" or source_type="run_step"
    # (run/artifact refs go to source_refs_metadata, not to trust-bearing provenance)
    prov_types = [e.get("source_type") for e in prov]
    assert "artifact" not in prov_types, f"Artifact must not be a trust-bearing provenance: {prov}"
    assert "run_step" not in prov_types, f"Run must not add internal_system provenance: {prov}"

    # Activity provenance must be user_confirmed for user_capture
    activity_prov = [e for e in prov if e.get("source_type") == "activity"]
    assert len(activity_prov) >= 1
    for e in activity_prov:
        assert e.get("source_trust") == "user_confirmed"


def test_summary_preview_truncated(db):
    long_content = "A" * 300
    act = _make_activity(db, content=long_content)
    long_summary = "B" * 400
    svc = InputSummaryService(db)

    with patch("app.activity.input_summary_service.resolve_reflector_provider", return_value=_FAKE_PROVIDER_TUPLE), \
         patch("app.activity.input_summary_service.call_reflector_llm", return_value=long_summary):
        result = svc.run(
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            activity_ids=[act.id],
        )

    assert len(result.summary_preview) <= 204  # 200 chars + "…" (1 char)
    assert result.summary_preview.endswith("…")
