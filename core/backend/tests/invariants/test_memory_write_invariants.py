"""Invariants: durable memory/policy writes only happen through ProposalApplyService.

These invariants must hold regardless of proposal type:
- preview proposals cannot be accepted
- rejected proposals cannot be accepted
- already-accepted proposals cannot be accepted again
- unknown proposal types raise UnsupportedProposalTypeError
- memory_update without target_memory_id fails at apply time
- memory_archive without target_memory_id fails at apply time
- policy_change creates a new Policy linked by created_from_proposal_id
- memory_update marks old row superseded; does not hard-delete
- memory_archive marks status=archived; does not hard-delete
"""

from __future__ import annotations

import pytest
from sqlalchemy import func

from app.memory.apply_service import (
    MemoryProposalApplier,
    PolicyProposalApplier,
    ProposalApplyError,
    ProposalApplyService,
)
from app.memory.proposals import ProposalService, UnsupportedProposalTypeError
from app.models import MemoryEntry, Policy, Proposal
from tests.support import factories


# ---------------------------------------------------------------------------
# Invalid-acceptance invariants (state-based)
# ---------------------------------------------------------------------------


def test_preview_proposal_cannot_be_accepted(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, preview=True, commit=False
    )
    db.flush()
    before = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is None
    db.refresh(prop)
    assert prop.status == "pending"
    after = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()
    assert after == before


def test_rejected_proposal_cannot_be_accepted(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=False)
    db.flush()
    ProposalService(db).reject(prop.id, space_id=a, user_id=ua.id)
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is None


def test_accepted_proposal_cannot_be_accepted_twice(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    first = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert first is not None
    second = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert second is None


def test_unknown_proposal_type_raises(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="completely_unknown_type", commit=True,
    )
    with pytest.raises(UnsupportedProposalTypeError) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.proposal_type == "completely_unknown_type"


# ---------------------------------------------------------------------------
# memory_update validation
# ---------------------------------------------------------------------------


def test_memory_update_without_target_id_raises(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={
            "operation": "update",
            # target_memory_id intentionally absent
            "proposed_content": "new content",
            "memory_type": "semantic",
            "target_scope": "user",
            "target_namespace": "user.default",
        },
        commit=False,
    )
    db.flush()
    with pytest.raises(Exception):
        # ProposalApplyService raises ProposalApplyError → ProposalService re-raises as HTTPException
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)


# ---------------------------------------------------------------------------
# memory_archive validation
# ---------------------------------------------------------------------------


def test_memory_archive_without_target_id_raises(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        payload_json={
            "operation": "archive",
            # target_memory_id intentionally absent
            "memory_type": "semantic",
            "target_scope": "user",
            "target_namespace": "user.default",
            "proposed_content": "",
        },
        commit=False,
    )
    db.flush()
    with pytest.raises(Exception):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)


# ---------------------------------------------------------------------------
# memory_update is append-only (no in-place mutation)
# ---------------------------------------------------------------------------


def test_memory_update_creates_new_row_and_supersedes_old(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    original = factories.create_test_memory_entry(
        db, space_id=a, content="v1 content", scope_type="agent",
        namespace="ns.chain", owner_user_id=ua.id, commit=True,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={
            "operation": "update",
            "target_memory_id": original.id,
            "proposed_content": "v2 content",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns.chain",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
        },
        commit=True,
    )
    svc = ProposalService(db)
    result = svc.accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    new_mem = result.memory
    assert new_mem is not None
    assert new_mem.id != original.id
    assert new_mem.content == "v2 content"
    assert new_mem.supersedes_memory_id == original.id
    assert new_mem.root_memory_id == original.id

    db.expire_all()
    old_row = db.query(MemoryEntry).filter(MemoryEntry.id == original.id).first()
    assert old_row.status == "superseded"
    assert old_row.deleted_at is None  # no hard delete


# ---------------------------------------------------------------------------
# memory_archive is status-based (no hard delete)
# ---------------------------------------------------------------------------


def test_memory_archive_sets_status_archived_no_delete(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    target = factories.create_test_memory_entry(
        db, space_id=a, content="archive me", scope_type="agent",
        namespace="ns.arc", owner_user_id=ua.id, commit=True,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        payload_json={
            "operation": "archive",
            "target_memory_id": target.id,
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns.arc",
            "proposed_content": target.content,
        },
        commit=True,
    )
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None

    db.expire_all()
    row = db.query(MemoryEntry).filter(MemoryEntry.id == target.id).first()
    assert row.status == "archived"
    assert row.deleted_at is None  # no hard delete


# ---------------------------------------------------------------------------
# policy_change — creates Policy linked to proposal
# ---------------------------------------------------------------------------


def test_policy_change_creates_policy_with_proposal_link(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Test policy",
        payload_json={
            "operation": "create",
            "domain": "memory",
            "policy_key": "test_key",
            "rule_json": {"effect": "allow"},
        },
        commit=True,
    )
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.policy is not None
    assert result.policy.created_from_proposal_id == prop.id
    assert result.policy.space_id == a
    assert result.policy.status == "active"


def test_policy_change_supersedes_old_policy(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    old_policy = factories.create_test_policy(
        db, space_id=a, name="old-policy", domain="memory", commit=True
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Policy v2",
        payload_json={
            "operation": "update",
            "target_policy_id": old_policy.id,
            "domain": "memory",
            "rule_json": {"effect": "deny"},
        },
        commit=True,
    )
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.policy is not None

    db.expire_all()
    old_row = db.query(Policy).filter(Policy.id == old_policy.id).first()
    assert old_row.status == "superseded"
    new_row = result.policy
    assert new_row.supersedes_policy_id == old_policy.id


# ---------------------------------------------------------------------------
# Runtime separation: direct MemoryStore.create is not called by public apply path
# ---------------------------------------------------------------------------


def test_proposal_apply_service_used_memory_internal_writer(db, cross_space_pair):
    """ProposalApplyService.apply creates memory via MemoryInternalWriter, not public API path."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, commit=True
    )
    # Apply directly through ProposalApplyService (the allowed internal boundary).
    svc = ProposalApplyService(db)
    result = svc.apply(prop, user_id=ua.id)
    assert result.memory is not None
    assert result.memory.created_from_proposal_id == prop.id
    assert result.memory.source_proposal_id == prop.id
