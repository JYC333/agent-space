"""Workflow tests for PersonalMemoryGrant egress review proposal creation.

Verifies:
- Blocked grant-derived artifact materialization creates a sanitized egress_review proposal.
- Blocked grant-derived memory proposal creation creates a sanitized egress_review proposal.
- Egress_review proposal payloads are content-free (no output text, raw memory,
  personal_context_block, generated summary, memory IDs, artifact content).
- Egress_review proposals still require granting-user approval before apply.
- Space admin still cannot approve on granting user's behalf.
- Revoked grant blocks egress_review apply.
- Non-grant-derived output does not create egress_review proposals.
- Personal-space targets do not create egress_review proposals.
- SourcePointer grant-derived metadata remains hard-blocked without auto-proposal.
"""

from __future__ import annotations
import uuid

import pytest
from datetime import UTC, datetime, timedelta

from app.models import (
    AgentVersion,
    Artifact,
    MemoryEntry,
    PersonalMemoryGrant,
    PersonalMemoryGrantEvent,
    Proposal,
    SpaceMembership,
)
from app.proposals.approvals import (
    PersonalMemoryEgressApprovalError,
    record_egress_granting_user_approval,
)
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from app.runs.run_output_materialization import RunOutputMaterializer
from tests.support import factories
from tests.support.assertions import (
    assert_egress_review_proposal_is_content_free,
    assert_no_personal_content_fields,
)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _personal_space(db, *, name: str = "Personal"):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name=name, space_type="personal")
    user = factories.create_test_user(db, space_id=sid, display_name=f"{name} User")
    db.commit()
    return sid, user


def _team_space(db, *, name: str = "Team"):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name=name, space_type="team")
    user = factories.create_test_user(db, space_id=sid, display_name=f"{name} User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str, role: str = "member") -> None:
    db.add(SpaceMembership(id=_new_id(), space_id=space_id, user_id=user_id, role=role, status="active"))
    db.flush()


def _private_memory(db, *, space_id: str, owner_user_id: str, content: str = "PRIVATE_EGRESS_SENTINEL") -> MemoryEntry:
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
        sensitivity_level="normal",
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


def _build_grant_derived_run(db, *, personal_id: str, team_id: str, user, raw_memory_content: str = "PRIVATE_EGRESS_SENTINEL"):
    """Create a run with has_personal_grant_context=True via ContextSnapshotPopulator."""
    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content=raw_memory_content)
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

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    db.refresh(run)
    db.refresh(grant)
    assert run.has_personal_grant_context is True, "Fixture: run must be grant-derived"
    return run, grant


# ---------------------------------------------------------------------------
# A. Blocked materialization creates egress_review proposal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_object_type,adapter_output",
    [
        (
            "artifact",
            {
                "artifacts": [{
                    "artifact_type": "report",
                    "title": "Blocked Report",
                    "content": "agent output derived from personal context",
                }]
            },
        ),
        (
            "memory_proposal",
            {
                "proposed_changes": [{
                    "proposal_type": "memory_update",
                    "summary": "Team knowledge update from personal context",
                    "payload": {
                        "proposed_content": "inferred from personal preferences",
                        "memory_type": "semantic",
                        "target_scope": "space",
                        "target_namespace": "space.knowledge",
                        "target_visibility": "space_shared",
                    },
                }]
            },
        ),
    ],
)
def test_grant_derived_shared_output_block_creates_sanitized_egress_review_proposal(
    db, target_object_type, adapter_output
):
    """Blocked grant-derived artifact and memory output create sanitized egress_review proposals."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output=adapter_output,
        adapter_type="test",
    )
    db.commit()

    # Direct persistence blocked
    assert len(_mat_result.errors) > 0
    assert any("egress" in e.lower() for e in _mat_result.errors)

    all_proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()

    if target_object_type == "artifact":
        assert db.query(Artifact).filter(Artifact.space_id == team_id).count() == 0
    else:
        memory_proposals = [p for p in all_proposals if p.proposal_type != "egress_review"]
        assert len(memory_proposals) == 0

    # egress_review proposal created
    egress_proposals = [p for p in all_proposals if p.proposal_type == "egress_review"]
    assert len(egress_proposals) >= 1, "egress_review proposal must be created for blocked output"

    proposal = egress_proposals[0]
    assert_egress_review_proposal_is_content_free(proposal)

    payload = proposal.payload_json
    assert payload["target_object_type"] == target_object_type
    assert payload["source_run_id"] == run.id
    assert payload["grant_id"] == grant.id
    assert payload["granting_user_id"] == user.id


# ---------------------------------------------------------------------------
# B. Payload content safety
# ---------------------------------------------------------------------------


def test_egress_review_proposal_payload_contains_no_output_text_or_personal_context(db):
    """egress_review proposal payload must contain no output text, raw memory, or personal context.

    This is the core egress safety assertion: nothing from the adapter output,
    raw personal memory, or personal_context_block may appear in the proposal payload.
    """
    RAW_MEMORY_TEXT = "SECRET_PERSONAL_DATA_EGRESS_WORKFLOW"
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(
        db,
        personal_id=personal_id,
        team_id=team_id,
        user=user,
        raw_memory_content=RAW_MEMORY_TEXT,
    )

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Report from grant-derived run",
                "content": f"output derived from {RAW_MEMORY_TEXT}",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) >= 1

    proposal = proposals[0]
    assert_egress_review_proposal_is_content_free(
        proposal,
        known_raw_text=RAW_MEMORY_TEXT,
        known_summary_text="output derived from",
    )


# ---------------------------------------------------------------------------
# C. Approval gate still required after egress proposal creation
# ---------------------------------------------------------------------------


def test_egress_review_proposal_requires_granting_user_approval_before_apply(db):
    """Applying an egress_review proposal created by the egress guard still requires granting-user approval.
    """
    from app.memory.apply_service import ProposalApplyError, ProposalApplyService

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked Report",
                "content": "agent output from personal context",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) >= 1
    proposal = proposals[0]

    # Attempting to apply without approval must fail
    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")

    # After granting-user approval, apply must succeed
    record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user.id,
    )
    result = ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")
    assert result.egress_review is True


def test_space_admin_still_cannot_apply_egress_review_without_granting_user_approval(db):
    """Space admin approval cannot substitute for the granting-user approval on egress_review proposals."""
    from app.memory.apply_service import ProposalApplyError, ProposalApplyService

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    # Create an admin user in team space
    admin_user = factories.create_test_user(db, space_id=team_id, display_name="Admin User", commit=False)
    existing_membership = (
        db.query(SpaceMembership)
        .filter(SpaceMembership.space_id == team_id, SpaceMembership.user_id == admin_user.id)
        .one()
    )
    existing_membership.role = "owner"
    db.flush()

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked Report",
                "content": "agent output from personal context",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) >= 1
    proposal = proposals[0]

    # Admin cannot approve (wrong user)
    with pytest.raises(PersonalMemoryEgressApprovalError):
        record_egress_granting_user_approval(
            db,
            proposal_id=proposal.id,
            grant_id=grant.id,
            approver_user_id=admin_user.id,
        )

    # Admin cannot apply either
    with pytest.raises(ProposalApplyError, match="GrantingUserApprovalRequired"):
        ProposalApplyService(db).apply(proposal, user_id=admin_user.id, accept_context="explicit_user_accept")


def test_revoked_grant_blocks_egress_review_apply(db):
    """Revoking the grant blocks apply of an egress_review proposal even after granting-user approval."""
    from app.memory.apply_service import ProposalApplyError, ProposalApplyService

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked Report",
                "content": "agent output from personal context",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) >= 1
    proposal = proposals[0]

    # Grant approval first
    record_egress_granting_user_approval(
        db,
        proposal_id=proposal.id,
        grant_id=grant.id,
        approver_user_id=user.id,
    )

    # Revoke the grant
    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    db.flush()

    # Apply must be blocked due to revoked grant
    with pytest.raises(ProposalApplyError, match="revoked"):
        ProposalApplyService(db).apply(proposal, user_id=user.id, accept_context="explicit_user_accept")


# ---------------------------------------------------------------------------
# D. Non-grant output and personal target — no egress_review created
# ---------------------------------------------------------------------------


def test_no_grant_output_does_not_create_egress_review_proposal(db):
    """Non-grant-derived runs must NOT create egress_review proposals."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    assert run.has_personal_grant_context is False

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Normal Report",
                "content": "regular output content",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    # Should succeed with no errors
    assert len(_mat_result.errors) == 0

    # No egress_review proposals should exist
    egress_proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(egress_proposals) == 0, "Non-grant run must not create egress_review proposals"


def test_personal_target_does_not_create_egress_review_proposal(db):
    """Grant-derived runs targeting their own personal space must NOT create egress_review proposals."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, _ = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    # Verify: egress_review builder returns None for personal targets
    from app.personal_memory_grants.egress_guard import EgressCheckResult, EgressDecision
    from app.personal_memory_grants.egress_review import create_egress_review_proposal

    fake_egress = EgressCheckResult(
        decision=EgressDecision.BLOCK,
        reason="non_personal_blocked",
        requires_proposal=True,
    )
    result = create_egress_review_proposal(
        db,
        source_run=run,
        target_space_id=personal_id,  # personal target
        target_object_type="artifact",
        operation="artifact_materialization",
        egress_result=fake_egress,
    )
    assert result is None, "egress_review proposal must NOT be created for personal-space target"


# ---------------------------------------------------------------------------
# E. SourcePointer remains hard-blocked without auto-proposal
# ---------------------------------------------------------------------------


def test_source_pointer_grant_derived_metadata_remains_blocked_not_auto_proposed(db):
    """The egress guard does not create egress_review proposals for SourcePointer grant-derived metadata.

    SourcePointer with grant-derived indicator keys targeting non-personal spaces
    must still be hard-rejected. Egress review creation only covers artifact and memory-proposal paths.
    """
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    personal_id2 = _new_id()
    factories.create_test_space(db, space_id=personal_id2, name="PersonalSrc", space_type="personal")
    db.commit()

    from app.source_pointers.service import GrantDerivedSourcePointerError, create_source_pointer

    with pytest.raises((GrantDerivedSourcePointerError, ValueError)):
        create_source_pointer(
            db,
            owner_space_id=team_id,
            source_space_id=personal_id2,
            source_object_type="memory",
            source_object_id=_new_id(),
            access_mode="read",
            granted_by_user_id=user.id,
            metadata_json={
                "derived_from_personal_memory": True,
                "provenance": "grant_context",
            },
        )

    # No egress_review proposal created for SourcePointer rejection
    egress_proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(egress_proposals) == 0, (
        "SourcePointer rejection must NOT auto-create egress_review proposals for SourcePointer rejection"
    )


# ---------------------------------------------------------------------------
# F. Proposal payload required fields safety
# ---------------------------------------------------------------------------


def test_egress_review_proposal_has_all_required_safe_metadata_fields(db):
    """egress_review proposal payload must include all required safe metadata fields."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked",
                "content": "blocked content",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) >= 1
    payload = proposals[0].payload_json

    # Required safe fields must be present
    required_fields = [
        "source_run_id",
        "target_space_id",
        "target_object_type",
        "operation",
        "grant_id",
        "granting_user_id",
        "raw_private_memory_included",
        "personal_summary_persisted",
        "derived_from_personal_memory",
        "egress_guard_required",
        "requires_approval_type",
        "required_approver_user_id",
        "review_status",
        "semantic_review_status",
        "content_attached",
    ]
    for field in required_fields:
        assert field in payload, f"Required field {field!r} missing from egress_review payload"

    assert payload["raw_private_memory_included"] is False
    assert payload["personal_summary_persisted"] is False
    assert payload["derived_from_personal_memory"] is True
    assert payload["egress_guard_required"] is True
    assert payload["requires_approval_type"] == "egress_granting_user"
    assert payload["required_approver_user_id"] == user.id
    assert payload["review_status"] == "manual_required"
    assert payload["semantic_review_status"] == "not_performed"
    assert payload["content_attached"] is False

    # No forbidden content keys
    assert_no_personal_content_fields(payload)


def test_error_message_includes_egress_review_proposal_id(db):
    """Materialization error message for egress-blocked output must include egress_review_proposal_id."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, _ = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked",
                "content": "blocked output",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    assert len(_mat_result.errors) > 0
    combined = " ".join(_mat_result.errors)
    assert "egress_review_proposal_id=" in combined, (
        f"Error must include egress_review_proposal_id: {_mat_result.errors}"
    )


# ---------------------------------------------------------------------------
# G. Dedupe stability
# ---------------------------------------------------------------------------


def test_repeated_blocked_artifact_materialization_reuses_existing_egress_review_proposal(db):
    """Calling materialize twice for the same blocked artifact must reuse the same egress_review proposal.

    Dedupe is stable and uses only ORM column filters + Python dict matching.
    """
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, _ = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    artifact_spec = {
        "artifacts": [{
            "artifact_type": "report",
            "title": "Blocked Report",
            "content": "agent output from personal context",
        }]
    }

    materializer = RunOutputMaterializer(db)
    materializer.materialize(run=run, adapter_output=artifact_spec, adapter_type="test")
    db.commit()

    first_proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(first_proposals) >= 1
    first_id = first_proposals[0].id

    # Materialize again — same run, same artifact spec
    materializer.materialize(run=run, adapter_output=artifact_spec, adapter_type="test")
    db.commit()

    all_proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(all_proposals) == 1, (
        f"Expected exactly 1 egress_review proposal after two identical blocked materializations, "
        f"got {len(all_proposals)}: {[p.id for p in all_proposals]}"
    )
    assert all_proposals[0].id == first_id, "Dedupe must return the original proposal, not a new one"


def test_repeated_blocked_memory_materialization_reuses_existing_egress_review_proposal(db):
    """Calling materialize twice for the same blocked memory proposal must reuse the egress_review proposal."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, _ = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    memory_spec = {
        "proposed_changes": [{
            "proposal_type": "memory_update",
            "summary": "Team knowledge",
            "payload": {
                "proposed_content": "inferred from personal context",
                "memory_type": "semantic",
                "target_scope": "space",
                "target_namespace": "space.knowledge",
                "target_visibility": "space_shared",
            },
        }]
    }

    materializer = RunOutputMaterializer(db)
    materializer.materialize(run=run, adapter_output=memory_spec, adapter_type="test")
    db.commit()

    first_egress = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(first_egress) >= 1
    first_id = first_egress[0].id

    materializer.materialize(run=run, adapter_output=memory_spec, adapter_type="test")
    db.commit()

    all_egress = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(all_egress) == 1, (
        f"Expected 1 egress_review proposal after two identical blocked memory materializations, "
        f"got {len(all_egress)}"
    )
    assert all_egress[0].id == first_id


def test_dedupe_uses_orm_columns_and_python_matching(db):
    """Dedupe uses only stable ORM columns for the DB query and Python dict matching.

    Verifies that _find_existing_open_proposal does not rely on JSON path operators.
    After creating one egress_review proposal, a second materialize call must
    return the same proposal ID.
    """
    from app.personal_memory_grants.egress_review import _find_existing_open_proposal, _compute_dedupe_key

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{"artifact_type": "report", "title": "Blocked", "content": "blocked"}]
        },
        adapter_type="test",
    )
    db.commit()

    proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(proposals) == 1
    proposal = proposals[0]

    # Verify dedupe key is stored in payload
    payload = proposal.payload_json or {}
    assert "egress_review_dedupe_key" in payload, "Payload must contain egress_review_dedupe_key"

    # Verify _find_existing_open_proposal finds it using Python-side matching
    found = _find_existing_open_proposal(
        db,
        run_id=run.id,
        target_space_id=team_id,
        target_object_type="artifact",
        operation="artifact_materialization",
        grant_id=grant.id,
    )
    assert found is not None, "_find_existing_open_proposal must find the existing proposal"
    assert found.id == proposal.id

    # Verify the dedupe key matches what the builder would compute
    expected_key = _compute_dedupe_key(
        run_id=run.id,
        target_space_id=team_id,
        target_object_type="artifact",
        operation="artifact_materialization",
        grant_id=grant.id,
    )
    assert payload["egress_review_dedupe_key"] == expected_key


def test_dedupe_key_is_content_free(db):
    """The egress_review_dedupe_key must contain only IDs and operation-type labels — no content."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    SENTINEL = "VERY_SECRET_PERSONAL_DATA_DEDUPE_TEST"
    run, grant = _build_grant_derived_run(
        db, personal_id=personal_id, team_id=team_id, user=user,
        raw_memory_content=SENTINEL,
    )

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked Report",
                "content": f"output referencing {SENTINEL}",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    proposal = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .first()
    )
    assert proposal is not None
    payload = proposal.payload_json or {}
    dedupe_key = payload.get("egress_review_dedupe_key", "")

    assert SENTINEL not in dedupe_key, "Dedupe key must not contain raw personal memory content"
    assert "SENTINEL" not in dedupe_key
    assert "output" not in dedupe_key.lower()

    # Key should only contain recognizable IDs and labels separated by |
    parts = dedupe_key.split("|")
    assert len(parts) == 5, f"Dedupe key must have 5 pipe-separated parts, got: {dedupe_key!r}"
    assert parts[0] == run.id
    assert parts[1] == team_id
    assert parts[2] == "artifact"
    assert parts[3] == "artifact_materialization"
    assert parts[4] == grant.id


def test_distinct_target_object_type_gets_distinct_egress_review_proposal(db):
    """Different target_object_type values for the same run must produce separate egress_review proposals."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    # Block an artifact
    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{"artifact_type": "report", "title": "Blocked", "content": "blocked"}]
        },
        adapter_type="test",
    )
    db.commit()

    # Block a memory proposal on the same run
    materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Blocked memory",
                "payload": {
                    "proposed_content": "blocked memory content",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )
    db.commit()

    all_egress = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(all_egress) == 2, (
        f"Expected 2 distinct egress_review proposals (artifact + memory_proposal), got {len(all_egress)}"
    )

    types_in_proposals = {p.payload_json.get("target_object_type") for p in all_egress}
    assert "artifact" in types_in_proposals
    assert "memory_proposal" in types_in_proposals


# ---------------------------------------------------------------------------
# egress_proposal_created event audit
# ---------------------------------------------------------------------------


def test_egress_proposal_created_event_is_written_when_proposal_created(db):
    """Blocking a grant-derived artifact writes an egress_proposal_created audit event.

    The event must:
    - have event_type='egress_proposal_created'
    - reference the correct grant_id
    - store the new proposal's ID in metadata_json.proposal_id
    - contain no content-bearing keys
    """
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run, grant = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Blocked Report",
                "content": "PRIVATE_EGRESS_SENTINEL shared artifact",
            }]
        },
        adapter_type="test",
    )
    db.commit()

    # Verify the egress_review proposal was created
    proposal = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .first()
    )
    assert proposal is not None, "Expected egress_review proposal to be created"

    # Verify the egress_proposal_created event was written
    event = (
        db.query(PersonalMemoryGrantEvent)
        .filter(
            PersonalMemoryGrantEvent.grant_id == grant.id,
            PersonalMemoryGrantEvent.event_type == "egress_proposal_created",
        )
        .first()
    )
    assert event is not None, "Expected egress_proposal_created event to be written"
    assert event.target_space_id == team_id

    metadata = event.metadata_json or {}
    assert metadata.get("proposal_id") == proposal.id, "Event must reference the created proposal ID"
    assert metadata.get("raw_private_memory_included") is False
    assert metadata.get("personal_summary_persisted") is False

    # Event metadata must be content-free
    assert_no_personal_content_fields(metadata, msg="egress_proposal_created event metadata must be content-free")
