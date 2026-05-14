"""End-to-end workflow: public write → Proposal created → accepted → durable memory/policy write.

Four end-to-end paths:
- POST /memory → pending memory_create proposal → accept → active MemoryEntry exists
- PATCH /memory/{id} → pending memory_update proposal → accept → new versioned row, old=superseded
- DELETE /memory/{id} → pending memory_archive proposal → accept → status=archived, no hard delete
- policy_change proposal created directly → accept → active Policy linked to proposal
"""

from __future__ import annotations

import pytest

from app.memory.proposals import ProposalService
from app.models import MemoryEntry, Policy, Proposal
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


# ---------------------------------------------------------------------------
# memory_create end-to-end
# ---------------------------------------------------------------------------


def test_create_memory_proposal_workflow(api_client, db, cross_space_pair):
    """POST /memory → 202 pending proposal → accept → active MemoryEntry."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # Step 1: public write creates a pending proposal, NOT a MemoryEntry
    r = api_client.post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "Workflow test memory",
            "content": "I like dark mode",
            "type": "preference",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_create"
    assert body["status"] == "pending"
    proposal_id = body["id"]

    # No MemoryEntry should exist yet
    active_count = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).count()
    assert active_count == 0

    # Step 2: accept the proposal
    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop is not None

    result = ProposalService(db).accept(proposal_id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.memory is not None
    assert result.memory.space_id == a
    assert result.memory.content == "I like dark mode"
    assert result.memory.status == "active"
    assert result.memory.created_from_proposal_id == proposal_id
    assert result.proposal.status == "accepted"

    # MemoryEntry is now in the DB
    db.expire_all()
    mem = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).first()
    assert mem is not None
    assert mem.content == "I like dark mode"


# ---------------------------------------------------------------------------
# memory_update end-to-end
# ---------------------------------------------------------------------------


def test_update_memory_proposal_workflow(api_client, db, cross_space_pair):
    """PATCH /memory/{id} → 202 pending proposal → accept → new versioned row; old=superseded."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # Seed an existing active MemoryEntry
    original = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="original content",
        scope_type="agent",
        namespace="ns.wf",
        owner_user_id=ua.id,
        commit=False,
    )
    original.visibility = "space_shared"
    db.commit()
    original_id = original.id

    # Step 1: PATCH creates a pending memory_update proposal, does not mutate in place
    r = api_client.patch(
        f"/api/v1/memory/{original_id}",
        params=_params(a, ua.id),
        json={"content": "updated content"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_update"
    assert body["status"] == "pending"
    proposal_id = body["id"]

    # Original MemoryEntry must be untouched
    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == original_id).first()
    assert mem_now.content == "original content"
    assert mem_now.status == "active"

    # Step 2: accept → new versioned row created; old marked superseded
    result = ProposalService(db).accept(proposal_id, space_id=a, user_id=ua.id)
    assert result is not None
    new_mem = result.memory
    assert new_mem is not None
    assert new_mem.id != original_id
    assert new_mem.content == "updated content"
    assert new_mem.supersedes_memory_id == original_id
    assert new_mem.root_memory_id == original_id
    assert new_mem.status == "active"

    db.expire_all()
    old_row = db.query(MemoryEntry).filter(MemoryEntry.id == original_id).first()
    assert old_row.status == "superseded"
    assert old_row.deleted_at is None  # append-only; no hard delete


# ---------------------------------------------------------------------------
# memory_archive end-to-end
# ---------------------------------------------------------------------------


def test_archive_memory_proposal_workflow(api_client, db, cross_space_pair):
    """DELETE /memory/{id} → 202 pending proposal → accept → status=archived, no hard delete."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    target = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="to be archived",
        scope_type="agent",
        namespace="ns.wf.arc",
        owner_user_id=ua.id,
        commit=False,
    )
    target.visibility = "space_shared"
    db.commit()
    target_id = target.id

    # Step 1: DELETE creates a pending memory_archive proposal; MemoryEntry stays active
    r = api_client.delete(
        f"/api/v1/memory/{target_id}",
        params=_params(a, ua.id),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_archive"
    assert body["status"] == "pending"
    proposal_id = body["id"]

    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == target_id).first()
    assert mem_now.status == "active"

    # Step 2: accept → archived; row still exists; no hard delete
    result = ProposalService(db).accept(proposal_id, space_id=a, user_id=ua.id)
    assert result is not None

    db.expire_all()
    row = db.query(MemoryEntry).filter(MemoryEntry.id == target_id).first()
    assert row is not None
    assert row.status == "archived"
    assert row.deleted_at is None


# ---------------------------------------------------------------------------
# policy_change end-to-end
# ---------------------------------------------------------------------------


def test_policy_change_proposal_workflow(db, cross_space_pair):
    """policy_change proposal → accept → active Policy linked to proposal."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Allow agent reads workflow",
        payload_json={
            "operation": "create",
            "domain": "memory",
            "policy_key": "agent_read_allow_wf",
            "rule_json": {"effect": "allow", "scope": "agent"},
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.policy is not None
    assert result.policy.space_id == a
    assert result.policy.status == "active"
    assert result.policy.created_from_proposal_id == prop.id
    assert result.proposal.status == "accepted"

    db.expire_all()
    policy = db.query(Policy).filter(Policy.id == result.policy.id).first()
    assert policy is not None
    assert policy.status == "active"
    assert policy.created_from_proposal_id == prop.id
