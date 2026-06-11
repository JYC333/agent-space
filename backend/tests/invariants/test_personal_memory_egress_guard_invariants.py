"""PersonalMemoryGrant egress guard invariants.

Verifies that grant-derived run output cannot be directly persisted into shared
artifacts, team memory, SourcePointer content, or public targets.
"""

from __future__ import annotations
import uuid

import pytest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models import (
    AgentVersion,
    ContextSnapshot,
    MemoryEntry,
    PersonalMemoryGrant,
    PersonalMemoryGrantEvent,
    Proposal,
    SourcePointer,
    SpaceMembership,
)
from app.personal_memory_grants.egress_guard import (
    EgressDecision,
    PersonalMemoryEgressError,
    check_personal_memory_egress,
    check_source_pointer_metadata_egress,
)
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from app.runs.run_output_materialization import RunOutputMaterializer
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


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
    db, *, space_id: str, owner_user_id: str, content: str = "private-content"
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


def _build_grant_derived_run(db, *, personal_id: str, team_id: str, user):
    """Create a run with has_personal_grant_context=True by going through ContextSnapshotPopulator."""
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
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

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    db.refresh(run)
    assert run.has_personal_grant_context is True, "Fixture: run must be grant-derived"
    return run


# ---------------------------------------------------------------------------
# A. Artifact persistence guard
# ---------------------------------------------------------------------------


def test_grant_derived_run_cannot_materialize_shared_artifact_directly(db):
    """Grant-derived run cannot create artifacts in a non-personal (team) space.

    RunOutputMaterializer blocks direct artifact creation and creates
    a sanitized egress_review proposal for the granting user to review.
    """
    from tests.support.assertions import assert_egress_review_proposal_is_content_free

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "artifacts": [{
                "artifact_type": "report",
                "title": "Sensitive Report",
                "content": "content derived from personal context",
            }]
        },
        adapter_type="test",
    )

    # Direct persistence must still be blocked
    assert len(_mat_result.errors) > 0, "Egress guard must block grant-derived artifact creation"
    assert any("egress" in e.lower() or "grant" in e.lower() or "personal" in e.lower() for e in _mat_result.errors)

    # No artifact must exist in team space
    from app.models import Artifact
    team_artifacts = db.query(Artifact).filter(Artifact.space_id == team_id).all()
    assert len(team_artifacts) == 0, "No artifacts must be created in team space for grant-derived run"

    # A sanitized egress_review proposal must have been created
    db.commit()
    egress_proposals = (
        db.query(Proposal)
        .filter(Proposal.space_id == team_id, Proposal.proposal_type == "egress_review")
        .all()
    )
    assert len(egress_proposals) >= 1, "An egress_review proposal must be created for blocked grant-derived artifact"
    assert_egress_review_proposal_is_content_free(egress_proposals[0])


def test_non_grant_run_shared_artifact_behavior_unchanged(db):
    """Non-grant-derived run can still create artifacts in team space.

    Egress guard must not affect runs without has_personal_grant_context=True.
    """
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    # Normal run — no grant, no personal context
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

    assert len(_mat_result.errors) == 0, f"Non-grant run must be able to create artifacts; errors: {_mat_result.errors}"

    from app.models import Artifact
    team_artifacts = db.query(Artifact).filter(Artifact.space_id == team_id).all()
    assert len(team_artifacts) == 1, "Non-grant run must create artifact in team space"


# ---------------------------------------------------------------------------
# B. Memory persistence guard
# ---------------------------------------------------------------------------


def test_grant_derived_run_cannot_create_shared_memory_directly(db):
    """Grant-derived run cannot create memory proposals in a non-personal (team) space.

    RunOutputMaterializer blocks direct memory proposal creation and
    creates a sanitized egress_review proposal for the granting user to review.
    """
    from tests.support.assertions import assert_egress_review_proposal_is_content_free

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Team knowledge from personal context",
                "payload": {
                    "proposed_content": "distilled from personal preferences",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )

    # Direct persistence must still be blocked
    assert len(_mat_result.errors) > 0, "Egress guard must block grant-derived memory proposal creation"

    db.commit()
    all_proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    # No memory proposals may exist; only egress_review proposals are allowed
    memory_proposals = [p for p in all_proposals if p.proposal_type != "egress_review"]
    assert len(memory_proposals) == 0, (
        "No memory proposals must be created in team space for grant-derived run"
    )

    # A sanitized egress_review proposal must have been created
    egress_proposals = [p for p in all_proposals if p.proposal_type == "egress_review"]
    assert len(egress_proposals) >= 1, (
        "An egress_review proposal must be created for blocked grant-derived memory proposal"
    )
    assert_egress_review_proposal_is_content_free(egress_proposals[0])


def test_non_grant_run_shared_memory_behavior_unchanged(db):
    """Non-grant-derived run can still create memory proposals in team space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    assert run.has_personal_grant_context is False

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "memory_update",
                "summary": "Normal team knowledge",
                "payload": {
                    "proposed_content": "knowledge from regular run",
                    "memory_type": "semantic",
                    "target_scope": "space",
                    "target_namespace": "space.knowledge",
                    "target_visibility": "space_shared",
                },
            }]
        },
        adapter_type="test",
    )

    assert len(_mat_result.errors) == 0, f"Non-grant run must be able to create memory proposals; errors: {_mat_result.errors}"

    proposals = db.query(Proposal).filter(Proposal.space_id == team_id).all()
    assert len(proposals) == 1, "Non-grant run must create a memory proposal in team space"


# ---------------------------------------------------------------------------
# C. SourcePointer metadata guard
# ---------------------------------------------------------------------------


def test_grant_derived_source_pointer_metadata_to_shared_space_is_rejected(db):
    """SourcePointer with grant-derived indicator keys cannot be created for non-personal owner_space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    from app.source_pointers.service import GrantDerivedSourcePointerError, create_source_pointer

    personal_id2 = _new_id()
    factories.create_test_space(db, space_id=personal_id2, name="PersonalSrc", space_type="personal")
    db.commit()

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


def test_regular_source_pointer_metadata_still_works(db):
    """SourcePointer with regular provenance metadata can be created for any owner_space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    personal_id2 = _new_id()
    factories.create_test_space(db, space_id=personal_id2, name="PersonalSrc2", space_type="personal")
    db.commit()

    from app.source_pointers.service import create_source_pointer

    sp = create_source_pointer(
        db,
        owner_space_id=team_id,
        source_space_id=personal_id2,
        source_object_type="memory",
        source_object_id=_new_id(),
        access_mode="read",
        granted_by_user_id=user.id,
        metadata_json={
            "note": "regular provenance pointer",
            "source_type": "user_memory",
        },
    )
    db.flush()
    assert sp.id is not None, "Regular SourcePointer must be created successfully"


def test_source_pointer_with_personal_memory_grant_ids_to_shared_space_is_rejected(db):
    """SourcePointer with personal_memory_grant_ids must not be created for non-personal owner_space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    personal_id2 = _new_id()
    factories.create_test_space(db, space_id=personal_id2, name="PersonalSrc3", space_type="personal")
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
            metadata_json={"personal_memory_grant_ids": ["grant-123"]},
        )


# ---------------------------------------------------------------------------
# D. Public target block
# ---------------------------------------------------------------------------


def test_grant_derived_public_target_is_blocked(db):
    """Grant-derived output targeting public visibility is always blocked."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    result = check_personal_memory_egress(
        db,
        run=run,
        target_space_id=team_id,
        target_object_type="artifact",
        target_visibility="public",
        operation="test_public_block",
    )

    assert result.decision == EgressDecision.BLOCK, "Public target must be blocked for grant-derived output"
    assert "public" in result.reason.lower()


# ---------------------------------------------------------------------------
# E. Audit event integrity
# ---------------------------------------------------------------------------


def test_egress_denied_event_contains_no_private_content(db):
    """Egress denied event metadata must not contain private content or personal summary."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)
    grant_id = run.personal_grant_context_json.get("grant_id") if run.personal_grant_context_json else None

    # Trigger an egress check that will block and write a denied event
    result = check_personal_memory_egress(
        db,
        run=run,
        target_space_id=team_id,
        target_object_type="artifact",
        operation="test_denied_event",
    )
    assert result.decision == EgressDecision.BLOCK
    db.commit()

    # Fetch denied events for this grant
    if grant_id:
        events = (
            db.query(PersonalMemoryGrantEvent)
            .filter(
                PersonalMemoryGrantEvent.grant_id == grant_id,
                PersonalMemoryGrantEvent.event_type == "denied",
            )
            .all()
        )
        assert len(events) >= 1, "At least one denied event must be written"

        for event in events:
            meta = event.metadata_json or {}
            # Events must not contain private content
            raw = str(meta)
            assert "private-content" not in raw, "Denied event must not contain raw memory text"
            assert "personal_memory_text" not in raw
            assert "generated_summary" not in raw
            # Must have required safe fields
            assert "reason" in meta
            assert "operation" in meta
            assert meta.get("raw_private_memory_included") is False


# ---------------------------------------------------------------------------
# F. Runtime personal context remains non-persistent
# ---------------------------------------------------------------------------


def test_personal_context_block_remains_out_of_persisted_snapshot_fields(db):
    """Runtime injection preserves runtime context persistence boundaries.

    The ContextSnapshot compiled fields must not contain the personal_context_block
    even when a valid run-scoped grant produces one.
    """
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="PHASE_D_RUNTIME_BLOCK_SENTINEL_99",
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

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None

    pkg = ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    # pkg has personal_context_block (ephemeral, in-memory only)
    assert pkg.personal_context_block, "pkg must have personal_context_block in memory"

    # ContextSnapshot must NOT contain the personal_context_block or raw memory
    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).first()
    assert snap is not None

    sentinel = "PHASE_D_RUNTIME_BLOCK_SENTINEL_99"
    assert sentinel not in (snap.compiled_prefix_text or ""), (
        "compiled_prefix_text must not contain personal memory raw content"
    )
    assert sentinel not in (snap.compiled_tail_text or ""), (
        "compiled_tail_text must not contain personal memory raw content"
    )
    assert pkg.personal_context_block not in (snap.compiled_prefix_text or ""), (
        "compiled_prefix_text must not contain personal_context_block"
    )
    assert pkg.personal_context_block not in (snap.compiled_tail_text or ""), (
        "compiled_tail_text must not contain personal_context_block"
    )

    # Run marker must be set
    db.refresh(run)
    assert run.has_personal_grant_context is True
    assert run.personal_grant_context_json is not None
    assert run.personal_grant_context_json.get("raw_memory_included") is False
    assert run.personal_grant_context_json.get("personal_summary_persisted") is False


# ---------------------------------------------------------------------------
# G. Egress guard service unit tests
# ---------------------------------------------------------------------------


def test_check_personal_memory_egress_allows_non_grant_run(db):
    """check_personal_memory_egress returns ALLOW for runs without personal grant context."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    assert run.has_personal_grant_context is False

    result = check_personal_memory_egress(
        db,
        run=run,
        target_space_id=team_id,
        target_object_type="artifact",
        operation="unit_test",
    )

    assert result.decision == EgressDecision.ALLOW
    assert result.grant_id is None


def test_check_personal_memory_egress_blocks_grant_derived_non_personal_target(db):
    """check_personal_memory_egress returns BLOCK for grant-derived run targeting non-personal space."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    result = check_personal_memory_egress(
        db,
        run=run,
        target_space_id=team_id,
        target_object_type="artifact",
        operation="unit_test",
    )

    assert result.decision == EgressDecision.BLOCK
    assert result.grant_id is not None
    assert "egress_review_required" in result.reason or "non_personal" in result.reason or "egress_review_required" in result.reason.lower()


def test_check_personal_memory_egress_allows_personal_target(db):
    """check_personal_memory_egress returns ALLOW for grant-derived run targeting personal space."""
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    result = check_personal_memory_egress(
        db,
        run=run,
        target_space_id=personal_id,
        target_object_type="artifact",
        operation="unit_test",
    )

    assert result.decision == EgressDecision.ALLOW


def test_check_source_pointer_metadata_egress_blocks_indicator_keys_in_shared_space(db):
    """check_source_pointer_metadata_egress returns BLOCK for grant-derived keys in non-personal space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    db.commit()

    result = check_source_pointer_metadata_egress(
        db,
        owner_space_id=team_id,
        metadata_json={"derived_from_personal_memory": True},
    )
    assert result.decision == EgressDecision.BLOCK


def test_check_source_pointer_metadata_egress_allows_safe_metadata_in_shared_space(db):
    """check_source_pointer_metadata_egress returns ALLOW for safe metadata in non-personal space."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    db.commit()

    result = check_source_pointer_metadata_egress(
        db,
        owner_space_id=team_id,
        metadata_json={"note": "regular pointer", "source_version": "1.0"},
    )
    assert result.decision == EgressDecision.ALLOW


def test_check_source_pointer_metadata_egress_allows_indicator_keys_in_personal_space(db):
    """check_source_pointer_metadata_egress returns ALLOW for indicator keys in personal space."""
    personal_id, user = _personal_space(db)
    db.commit()

    result = check_source_pointer_metadata_egress(
        db,
        owner_space_id=personal_id,
        metadata_json={"derived_from_personal_memory": True},
    )
    assert result.decision == EgressDecision.ALLOW


# ---------------------------------------------------------------------------
# H. apply_update defense-in-depth guard
# ---------------------------------------------------------------------------


def _create_team_memory(db, *, space_id: str, user_id: str) -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="space",
        memory_type="semantic",
        content="original team memory content",
        status="active",
        visibility="space_shared",
        owner_user_id=user_id,
        subject_user_id=user_id,
        sensitivity_level="normal",
    )
    db.add(m)
    db.flush()
    return m


def test_grant_derived_run_cannot_apply_memory_update_to_shared_space(db):
    """MemoryProposalApplier.apply_update() blocks grant-derived proposals.

    Defense-in-depth: even if a memory_update proposal for a team space arrives at
    apply_update(), it must be blocked when created_by_run_id points to a
    grant-derived run.
    """
    from app.proposals import MemoryProposalApplier
    from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    # Create a target memory entry in the team space (would be the update target)
    target_mem = _create_team_memory(db, space_id=team_id, user_id=user.id)
    db.commit()

    # Construct a memory_update proposal in team space, sourced from the grant-derived run
    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        proposal_type="memory_update",
        status="pending",
        title="Update from grant-derived run",
        payload_json={
            "target_memory_id": target_mem.id,
            "proposed_content": "updated content from personal context",
            "memory_type": "semantic",
            "target_scope": "space",
            "target_namespace": "space.default",
            "source_run_id": run.id,
        },
        created_by_run_id=run.id,
        created_by_user_id=user.id,
        risk_level="low",
        urgency="normal",
    )
    db.add(proposal)
    db.commit()

    with pytest.raises(PersonalMemoryEgressError):
        MemoryProposalApplier(db).apply_update(proposal, user_id=user.id)

    # No new version of the memory must have been created
    from app.models import MemoryEntry
    versions = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.space_id == team_id)
        .all()
    )
    # Only the original target_mem should exist; no superseding version
    assert all(m.id == target_mem.id or m.status != "active" for m in versions), (
        "apply_update must not create a new memory version for grant-derived proposals"
    )


def test_non_grant_memory_update_apply_update_unchanged(db):
    """apply_update() still works normally for non-grant-derived proposals."""
    from app.proposals import MemoryProposalApplier

    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    # Normal run — no grant context
    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    assert run.has_personal_grant_context is False

    target_mem = _create_team_memory(db, space_id=team_id, user_id=user.id)
    db.commit()

    proposal = Proposal(
        id=_new_id(),
        space_id=team_id,
        proposal_type="memory_update",
        status="pending",
        title="Normal update",
        payload_json={
            "target_memory_id": target_mem.id,
            "proposed_content": "updated content from regular run",
            "memory_type": "semantic",
            "target_scope": "space",
            "target_namespace": "space.default",
            "source_run_id": run.id,
        },
        created_by_run_id=run.id,
        created_by_user_id=user.id,
        risk_level="low",
        urgency="normal",
    )
    db.add(proposal)
    db.commit()

    result = MemoryProposalApplier(db).apply_update(proposal, user_id=user.id)

    assert result.memory is not None, "Non-grant update must succeed"
    assert result.superseded_memory_id == target_mem.id, "Original memory must be superseded"


def test_grant_derived_update_to_personal_space_is_allowed(db):
    """apply_update() allows grant-derived proposals targeting personal spaces.

    Egress guard ALLOWs personal-space targets for grant-derived runs.
    """
    from app.proposals import MemoryProposalApplier

    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    # Target memory lives in the personal space (not team space)
    personal_target_mem = _create_team_memory(db, space_id=personal_id, user_id=user.id)
    db.commit()

    proposal = Proposal(
        id=_new_id(),
        space_id=personal_id,   # proposal targets personal space
        proposal_type="memory_update",
        status="pending",
        title="Update personal memory from grant-derived run",
        payload_json={
            "target_memory_id": personal_target_mem.id,
            "proposed_content": "updated personal memory content",
            "memory_type": "semantic",
            "target_scope": "user",
            "target_namespace": "user.default",
            "source_run_id": run.id,
        },
        created_by_run_id=run.id,
        created_by_user_id=user.id,
        risk_level="low",
        urgency="normal",
    )
    db.add(proposal)
    db.commit()

    result = MemoryProposalApplier(db).apply_update(proposal, user_id=user.id)
    assert result.memory is not None, "Grant-derived update to personal space must be allowed"
    assert result.superseded_memory_id == personal_target_mem.id


# ---------------------------------------------------------------------------
# I. Code patch proposal risk labeling
# ---------------------------------------------------------------------------


def test_grant_derived_code_patch_proposal_carries_risk_metadata(db):
    """code patch proposal from grant-derived run carries personal_context_derived metadata.

    RunOutputMaterializer._code_patch_proposal must add explicit risk markers
    and elevate risk_level to 'high' for grant-derived runs.
    """
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    workspace = factories.create_test_workspace(db, space_id=team_id, commit=True)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "code_patch",
                "workspace_id": workspace.id,
                "summary": "Code change from grant-derived run",
                "patch": {
                    "operations": [{
                        "op": "replace_file",
                        "path": "notes.txt",
                        "content": "updated content",
                    }]
                },
            }]
        },
        adapter_type="test",
    )

    assert len(_mat_result.errors) == 0, f"Code patch proposal creation must not error; got: {_mat_result.errors}"

    proposal = db.query(Proposal).filter(
        Proposal.space_id == team_id,
        Proposal.proposal_type == "code_patch",
    ).first()
    assert proposal is not None, "Code patch proposal must have been created"

    # Risk level must be elevated to 'high'
    assert proposal.risk_level == "high", (
        f"Grant-derived code patch must have risk_level='high'; got {proposal.risk_level!r}"
    )

    payload = proposal.payload_json or {}
    assert payload.get("personal_context_derived") is True
    assert payload.get("egress_guard_required") is True
    assert payload.get("requires_extra_review") is True
    assert payload.get("raw_private_memory_included") is False
    assert payload.get("personal_summary_persisted") is False
    assert "grant_id" in payload, "grant_id must be present in risk metadata"
    assert "granting_user_id" in payload, "granting_user_id must be present in risk metadata"


def test_non_grant_code_patch_proposal_risk_metadata_unchanged(db):
    """code patch proposal from non-grant run is unaffected by risk labeling logic."""
    _, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    assert run.has_personal_grant_context is False

    workspace = factories.create_test_workspace(db, space_id=team_id, commit=True)

    materializer = RunOutputMaterializer(db)
    _mat_result = materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "code_patch",
                "workspace_id": workspace.id,
                "summary": "Normal code change",
                "patch": {
                    "operations": [{
                        "op": "replace_file",
                        "path": "readme.txt",
                        "content": "updated readme",
                    }]
                },
            }]
        },
        adapter_type="test",
    )

    assert len(_mat_result.errors) == 0, f"Non-grant code patch proposal must succeed; errors: {_mat_result.errors}"

    proposal = db.query(Proposal).filter(
        Proposal.space_id == team_id,
        Proposal.proposal_type == "code_patch",
    ).first()
    assert proposal is not None

    assert proposal.risk_level == "low", (
        f"Non-grant code patch must retain risk_level='low'; got {proposal.risk_level!r}"
    )
    payload = proposal.payload_json or {}
    assert "personal_context_derived" not in payload
    assert "egress_guard_required" not in payload
    assert "grant_id" not in payload


def test_grant_derived_code_patch_payload_contains_no_raw_memory_or_summary(db):
    """grant-derived code patch payload contains no raw memory text or summary.

    The risk metadata added to payload_json must only contain safe fields —
    no personal memory content, no generated summary, no memory IDs.
    """
    personal_id, user = _personal_space(db)
    team_id, _ = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    _private_memory(db, space_id=personal_id, owner_user_id=user.id, content="SECRET_PERSONAL_DATA_XYZ")
    db.commit()

    run = _build_grant_derived_run(db, personal_id=personal_id, team_id=team_id, user=user)

    workspace = factories.create_test_workspace(db, space_id=team_id, commit=True)

    materializer = RunOutputMaterializer(db)
    materializer.materialize(
        run=run,
        adapter_output={
            "proposed_changes": [{
                "proposal_type": "code_patch",
                "workspace_id": workspace.id,
                "summary": "Code change from grant context",
                "patch": {
                    "operations": [{
                        "op": "replace_file",
                        "path": "output.txt",
                        "content": "safe output content",
                    }]
                },
            }]
        },
        adapter_type="test",
    )

    proposal = db.query(Proposal).filter(
        Proposal.space_id == team_id,
        Proposal.proposal_type == "code_patch",
    ).first()
    assert proposal is not None

    payload_str = str(proposal.payload_json or {})
    assert "SECRET_PERSONAL_DATA_XYZ" not in payload_str, (
        "Code patch payload must not contain raw personal memory text"
    )
    assert "personal_memory_text" not in payload_str
    assert "generated_summary" not in payload_str
