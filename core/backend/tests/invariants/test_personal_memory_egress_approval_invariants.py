"""PersonalMemoryGrant egress approval invariants."""

from __future__ import annotations
import uuid

import pytest
from datetime import UTC, datetime, timedelta

from app.memory.apply_service import ProposalApplyError, ProposalApplyService
from app.models import AgentVersion, MemoryEntry, PersonalMemoryGrant, PersonalMemoryGrantEvent, Proposal, ProposalApproval, SpaceMembership
from app.proposals.approvals import (
    PersonalMemoryEgressApprovalError,
    record_egress_granting_user_approval,
)
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from tests.support import factories
from tests.support.assertions import assert_no_personal_content_fields


def _new_id() -> str:
    return str(uuid.uuid4())


def _space(db, *, space_type: str, name: str):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name=name, space_type=space_type)
    user = factories.create_test_user(db, space_id=sid, display_name=f"{name} User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str, role: str = "member") -> None:
    db.add(SpaceMembership(id=_new_id(), space_id=space_id, user_id=user_id, role=role, status="active"))
    db.flush()


def _private_memory(db, *, space_id: str, owner_user_id: str, content: str = "PRIVATE_SENTINEL") -> MemoryEntry:
    mem = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        sensitivity_level="normal",
    )
    db.add(mem)
    db.flush()
    return mem


def _active_grant(
    db,
    *,
    granting_user_id: str,
    personal_space_id: str,
    target_space_id: str,
    target_run_id: str,
) -> PersonalMemoryGrant:
    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=granting_user_id,
        personal_space_id=personal_space_id,
        target_space_id=target_space_id,
        target_run_id=target_run_id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(hours=1),
        egress_review_expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    db.add(grant)
    db.flush()
    return grant


def _grant_derived_run(db):
    personal_id, user = _space(db, space_type="personal", name="Personal")
    team_id, _ = _space(db, space_type="team", name="Team")
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="DO_NOT_PERSIST_PRIVATE")
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()
    db.refresh(run)
    db.refresh(grant)
    assert run.has_personal_grant_context is True
    assert grant.status == "used"
    return personal_id, team_id, user, run, grant


def _grant_memory_proposal(db, *, team_id: str, user_id: str, run_id: str, grant_id: str) -> Proposal:
    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        created_by_run_id=run_id,
        proposal_type="memory_create",
        status="pending",
        risk_level="high",
        urgency="normal",
        title="Sanitized team memory",
        payload_json={
            "operation": "create",
            "proposed_content": "sanitized team-safe output",
            "memory_type": "semantic",
            "target_scope": "space",
            "target_namespace": "space.knowledge",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
            "source_run_id": run_id,
            "grant_id": grant_id,
            "personal_context_derived": True,
            "egress_guard_required": True,
            "raw_private_memory_included": False,
            "personal_summary_persisted": False,
        },
        created_by_user_id=user_id,
        review_deadline=datetime.now(UTC) + timedelta(hours=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()
    return proposal


def _approve(db, *, proposal: Proposal, grant: PersonalMemoryGrant, user_id: str | None = None) -> ProposalApproval:
    return record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user_id or grant.granting_user_id,
    )


def _apply(db, proposal: Proposal, *, user_id: str):
    return ProposalApplyService(db).apply(
        proposal,
        user_id=user_id,
        accept_context="explicit_user_accept",
    )


def test_egress_review_proposal_requires_granting_user_approval(db):
    from app.memory.proposals import build_egress_review_proposal

    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = build_egress_review_proposal(
        _new_id(),
        team_id,
        user.id,
        source_run_id=run.id,
        grant_id=grant.id,
        granting_user_id=user.id,
        target_object_type="memory",
        target_space_id=team_id,
        review_deadline=datetime.now(UTC) + timedelta(hours=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal, user_id=user.id)

    _approve(db, proposal=proposal, grant=grant)
    result = _apply(db, proposal, user_id=user.id)
    assert result.egress_review is True


def test_space_admin_approval_cannot_substitute_for_granting_user(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    admin = factories.create_test_user(db, space_id=team_id, display_name="Admin", commit=False)
    membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == team_id, SpaceMembership.user_id == admin.id)
        .one()
    )
    membership.role = "owner"
    db.flush()
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=admin.id, run_id=run.id, grant_id=grant.id)
    db.commit()

    with pytest.raises(PersonalMemoryEgressApprovalError):
        _approve(db, proposal=proposal, grant=grant, user_id=admin.id)
    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal, user_id=admin.id)


def test_payload_metadata_cannot_satisfy_approval(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    proposal.payload_json = {**proposal.payload_json, "approved_by_granting_user": True, "granting_user_approved": True}
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal, user_id=user.id)


def test_wrong_user_approval_rejected(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    other = factories.create_test_user(db, space_id=team_id, display_name="Other", commit=True)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)

    db.add(ProposalApproval(
        id=_new_id(),
        proposal_id=proposal.id,
        approval_type="egress_granting_user",
        approver_user_id=other.id,
        grant_id=grant.id,
        target_space_id=team_id,
        status="approved",
        metadata_json={"raw_private_memory_included": False, "personal_summary_persisted": False},
    ))
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal, user_id=user.id)


def test_wrong_grant_approval_rejected(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    other_run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    other_grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=grant.personal_space_id,
        target_space_id=team_id,
        target_run_id=other_run.id,
    )
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    db.add(ProposalApproval(
        id=_new_id(),
        proposal_id=proposal.id,
        approval_type="egress_granting_user",
        approver_user_id=user.id,
        grant_id=other_grant.id,
        target_space_id=team_id,
        status="approved",
        metadata_json={"raw_private_memory_included": False, "personal_summary_persisted": False},
    ))
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal, user_id=user.id)


def test_revoked_grant_blocks_pending_egress_apply(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    _approve(db, proposal=proposal, grant=grant)
    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    db.flush()

    with pytest.raises(ProposalApplyError, match="revoked"):
        _apply(db, proposal, user_id=user.id)


def test_failed_grant_blocks_pending_egress_apply(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    _approve(db, proposal=proposal, grant=grant)
    grant.status = "failed"
    grant.failed_at = datetime.now(UTC)
    db.flush()

    with pytest.raises(ProposalApplyError, match="failed"):
        _apply(db, proposal, user_id=user.id)


def test_expired_grant_blocks_pending_egress_apply(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    _approve(db, proposal=proposal, grant=grant)
    grant.status = "expired"
    db.flush()

    with pytest.raises(ProposalApplyError, match="expired"):
        _apply(db, proposal, user_id=user.id)


def test_used_grant_for_same_run_can_be_approved_for_egress(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    assert grant.status == "used"
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    _approve(db, proposal=proposal, grant=grant)

    result = _apply(db, proposal, user_id=user.id)
    assert result.memory is not None


def test_approval_for_run_a_cannot_apply_run_b_proposal(db):
    personal_id, team_id, user, run_a, grant_a = _grant_derived_run(db)
    run_b = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant_b = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run_b.id,
    )
    proposal_b = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run_b.id, grant_id=grant_b.id)
    db.add(ProposalApproval(
        id=_new_id(),
        proposal_id=proposal_b.id,
        approval_type="egress_granting_user",
        approver_user_id=user.id,
        grant_id=grant_a.id,
        target_space_id=team_id,
        status="approved",
        metadata_json={"raw_private_memory_included": False, "personal_summary_persisted": False},
    ))
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        _apply(db, proposal_b, user_id=user.id)


def test_approval_metadata_contains_no_private_memory_content(db):
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    approval = _approve(db, proposal=proposal, grant=grant)

    raw = str(approval.metadata_json)
    assert "DO_NOT_PERSIST_PRIVATE" not in raw
    assert "content" not in raw.lower()
    assert "generated_summary" not in raw.lower()
    assert "memory_id" not in raw.lower()


# ---------------------------------------------------------------------------
# egress_approved event audit
# ---------------------------------------------------------------------------


def test_egress_approved_event_is_written_when_granting_user_approves(db):
    """record_egress_granting_user_approval writes an egress_approved audit event.

    The event must:
    - have event_type='egress_approved'
    - reference the correct grant_id
    - store the proposal_id in metadata_json
    - contain no content-bearing keys
    """
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    db.commit()

    _approve(db, proposal=proposal, grant=grant)
    db.commit()

    event = (
        db.query(PersonalMemoryGrantEvent)
        .filter(
            PersonalMemoryGrantEvent.grant_id == grant.id,
            PersonalMemoryGrantEvent.event_type == "egress_approved",
        )
        .first()
    )
    assert event is not None, "Expected egress_approved event to be written"
    assert event.target_space_id == team_id

    metadata = event.metadata_json or {}
    assert metadata.get("proposal_id") == proposal.id
    assert metadata.get("approval_type") == "egress_granting_user"
    assert metadata.get("raw_private_memory_included") is False
    assert metadata.get("personal_summary_persisted") is False

    # Event metadata must be content-free
    assert_no_personal_content_fields(metadata, msg="egress_approved event metadata must be content-free")


def test_egress_approved_event_not_duplicated_for_idempotent_approval(db):
    """Calling record_egress_granting_user_approval twice returns the existing approval row;
    a second egress_approved event must NOT be written for the duplicate call."""
    _, team_id, user, run, grant = _grant_derived_run(db)
    proposal = _grant_memory_proposal(db, team_id=team_id, user_id=user.id, run_id=run.id, grant_id=grant.id)
    db.commit()

    _approve(db, proposal=proposal, grant=grant)
    db.commit()
    _approve(db, proposal=proposal, grant=grant)  # idempotent — returns existing
    db.commit()

    events = (
        db.query(PersonalMemoryGrantEvent)
        .filter(
            PersonalMemoryGrantEvent.grant_id == grant.id,
            PersonalMemoryGrantEvent.event_type == "egress_approved",
        )
        .all()
    )
    assert len(events) == 1, "Idempotent approval must not write duplicate egress_approved events"
