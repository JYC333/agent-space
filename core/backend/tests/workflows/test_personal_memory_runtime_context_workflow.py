"""Workflow tests: PersonalMemoryGrant integration with run context building.

The runtime context integration tests verify the
baseline security boundary (no grant → no cross-space read) and the grant
resolver/context integration pass as normal tests.

The egress guard tests verify grant-derived output
cannot be written to non-personal targets now pass as normal tests.

The proposal approval gate requires grant-derived shared apply
requires first-class granting-user approval.
"""

from __future__ import annotations
import uuid

import pytest
from datetime import UTC, datetime, timedelta

from app.memory.retriever import MemoryRetriever
from app.models import ContextSnapshot, MemoryEntry, PersonalMemoryGrant, Proposal, SpaceMembership
from app.personal_memory_grants.resolver import (
    resolve_personal_memory_context_for_run,
    retrieve_eligible_memories,
)
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


def _personal_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=sid, display_name="Personal User")
    db.commit()
    return sid, user


def _team_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=sid, display_name="Team User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str) -> None:
    db.add(SpaceMembership(
        id=_new_id(), space_id=space_id, user_id=user_id, role="member", status="active"
    ))


def _private_memory(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    content: str = "private",
    sensitivity_level: str = "normal",
) -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        sensitivity_level=sensitivity_level,
    )
    db.add(m)
    db.flush()
    return m


def _active_grant(
    db,
    *,
    granting_user_id: str,
    personal_space_id: str,
    target_space_id: str,
    target_run_id: str,
    expires_in_seconds: int = 3600,
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
        read_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )
    db.add(grant)
    db.flush()
    return grant


# ---------------------------------------------------------------------------
# Baseline: deny is enforced without a grant
# ---------------------------------------------------------------------------


def test_no_grant_shared_run_still_cannot_read_personal_private_memory(db):
    """Without any grant, a shared-space run cannot read personal-space private memory.

    This is the baseline security invariant enforced by the space_id hard filter
    in MemoryRetriever.  PersonalMemoryGrant does not weaken this.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    private = _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=team_id, user_id=user.id)
    assert private.id not in {m.id for m in result.memories}, (
        "Personal-space private memory must not appear in shared-space run context."
    )


# ---------------------------------------------------------------------------
# Grant resolver and runtime context integration
# ---------------------------------------------------------------------------


def test_shared_run_with_valid_grant_receives_summary_only_personal_context(db):
    """Runtime context: resolver returns a personal memory summary when a valid grant exists.

    When a user creates a PersonalMemoryGrant with status=active for the run,
    the resolver produces an ephemeral personal_context_block (a structured summary
    — not raw memory entries) and transitions the grant to 'used'.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="work context A")
    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="work context B")
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

    result = resolve_personal_memory_context_for_run(db, run=run)

    assert result.has_personal_context, "Resolver should return a non-empty personal context block"
    assert result.personal_context_block, "personal_context_block must be a non-empty string"
    assert result.memory_count >= 1, "At least one personal memory should be counted"

    # Verify grant state transitioned to 'used'
    db.refresh(grant)
    assert grant.status == "used", f"Grant should be 'used' after resolution; got {grant.status!r}"
    assert grant.used_at is not None, "used_at must be set"

    # Verify personal memory content is NOT in the summary (only aggregate metadata)
    assert "work context A" not in result.personal_context_block
    assert "work context B" not in result.personal_context_block


def test_context_snapshot_records_grant_metadata_without_raw_memory(db):
    """Runtime context: shared ContextSnapshot records only grant metadata, never raw memory or summary.

    compiled_prefix_text, compiled_tail_text, and source_refs_json must not contain:
    raw personal memory text, the generated personal summary, or personal memory IDs.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    private = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="HIGHLY_IDENTIFIABLE_SECRET_XYZ"
    )
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    # Use the populator (same as real run path) to build the full snapshot
    from app.models import AgentVersion
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None

    pkg = ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    # Fetch the persisted snapshot
    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).first()
    assert snap is not None

    raw_content = "HIGHLY_IDENTIFIABLE_SECRET_XYZ"

    # compiled text must not contain raw personal memory content
    assert raw_content not in (snap.compiled_prefix_text or ""), (
        "compiled_prefix_text must not contain personal memory raw content"
    )
    assert raw_content not in (snap.compiled_tail_text or ""), (
        "compiled_tail_text must not contain personal memory raw content"
    )

    # source_refs_json must not contain the personal memory ID
    source_refs_str = str(snap.source_refs_json or [])
    assert private.id not in source_refs_str, (
        "source_refs_json must not contain personal memory IDs"
    )
    assert raw_content not in source_refs_str, (
        "source_refs_json must not contain personal memory raw content"
    )

    # personal context block must not be in persisted fields
    assert pkg.personal_context_block not in (snap.compiled_prefix_text or "")
    assert pkg.personal_context_block not in (snap.compiled_tail_text or "")

    # Safe grant metadata SHOULD be in source_refs
    grant_refs = [
        r for r in (snap.source_refs_json or [])
        if r.get("source_type") == "personal_memory_grant"
    ]
    assert len(grant_refs) == 1, "Exactly one personal_memory_grant source_ref should be present"
    ref = grant_refs[0]
    assert ref["raw_memory_included"] is False
    assert ref["personal_summary_persisted"] is False
    assert ref["access_mode"] == "summary_only"
    assert ref["memory_count"] >= 1


def test_run_marks_one_time_grant_used_after_context_build(db):
    """Runtime context: grant transitions active→consuming→used atomically; used grant cannot be reused.

    After successful resolution, the grant is used and a second resolution attempt
    returns no personal context.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
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

    # First resolution: should succeed
    result1 = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()
    assert result1.has_personal_context, "First resolution should produce personal context"

    db.refresh(grant)
    assert grant.status == "used"
    assert grant.used_at is not None

    # Second resolution: grant is used; should return no personal context
    result2 = resolve_personal_memory_context_for_run(db, run=run)
    assert not result2.has_personal_context, (
        "Second resolution must return no personal context — grant is already used"
    )


# ---------------------------------------------------------------------------
# Egress guard
# ---------------------------------------------------------------------------


def test_personal_memory_summary_does_not_create_team_memory(db):
    """Egress guard: grant-derived run cannot materialize a memory proposal into team space.

    The Egress Guard blocks RunOutputMaterializer from creating a memory proposal
    for a run that has personal grant context targeting a non-personal space.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="personal pref A")
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    # Build context snapshot — this sets run.has_personal_grant_context = True
    from app.models import AgentVersion
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    db.refresh(run)
    assert run.has_personal_grant_context is True, "Run must be marked as grant-derived"

    # Attempt to materialize a team memory from this grant-derived run
    from app.runs.run_output_materialization import RunOutputMaterializer
    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Grant-derived team knowledge",
                "payload": {
                    "proposed_content": "inferred from personal context",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )

    assert len(_mat_result.errors) > 0, "Materialization must fail for grant-derived run targeting team space"
    assert any("egress" in e.lower() or "personal" in e.lower() or "grant" in e.lower() for e in _mat_result.errors), (
        f"Error must mention egress or grant context; got: {_mat_result.errors}"
    )

    # Only egress_review proposals may exist (no memory proposals)
    all_proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    memory_proposals = [p for p in all_proposals if p.proposal_type != "egress_review"]
    assert len(memory_proposals) == 0, (
        f"No memory proposals must be created from grant-derived run in team space: {[p.proposal_type for p in memory_proposals]}"
    )


def test_run_output_requires_proposal_before_persisting_private_personal_context(db):
    """Egress approval: persisting grant-derived output into shared space requires proposal + granting-user approval.

    The ProposalApplyService must verify a proposal_approvals row with approval_type=egress_granting_user
    before allowing any grant-derived output to be applied to a shared space.
    """
    from app.memory.apply_service import ProposalApplyError, ProposalApplyService
    from app.proposals.approvals import record_egress_granting_user_approval

    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="PRIVATE_PHASE_E")
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    grant.egress_review_expires_at = datetime.now(UTC) + timedelta(hours=2)
    db.commit()

    from app.models import AgentVersion
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()
    db.refresh(run)
    db.refresh(grant)
    assert run.has_personal_grant_context is True
    assert grant.status == "used"

    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        created_by_run_id=run.id,
        proposal_type="memory_create",
        status="pending",
        risk_level="high",
        urgency="normal",
        title="Sanitized memory",
        payload_json={
            "operation": "create",
            "proposed_content": "sanitized output only",
            "memory_type": "semantic",
            "target_scope": "space",
            "target_namespace": "space.knowledge",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
            "source_run_id": run.id,
            "grant_id": grant.id,
            "personal_context_derived": True,
            "egress_guard_required": True,
            "raw_private_memory_included": False,
            "personal_summary_persisted": False,
        },
        created_by_user_id=user.id,
        review_deadline=datetime.now(UTC) + timedelta(hours=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()

    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")

    record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user.id,
    )
    result = ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")
    assert result.memory is not None
    assert result.memory.content == "sanitized output only"
    assert result.memory.space_id == team_id
