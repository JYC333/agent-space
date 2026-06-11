"""
Invariant tests for ContextDigestService.

Tests verify:
- Digest generation creates active digest rows for each type.
- Only active Memory/Policy sources are included.
- Versioning: same source_hash → no new version; changed sources → new version.
- Old digest becomes superseded when new version is created.
- Content hash is stable for same content.
- Digest generation never creates MemoryEntry or Proposal.
- Dirty tracking marks correct digests dirty after accepted proposals.
"""

from __future__ import annotations
import uuid

import pytest

from app.memory.digest_service import ContextDigestService
from app.models import ContextDigest, MemoryEntry, Policy, Proposal
from tests.support import factories


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _active_memory(db, *, space_id, scope_type="workspace", workspace_id=None, agent_id=None, content="test content") -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type=scope_type,
        memory_type="semantic",
        content=content,
        status="active",
        visibility="space_shared",
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    db.add(m)
    db.flush()
    return m


def _active_policy(db, *, space_id, name="test-pol") -> Policy:
    p = Policy(
        id=_new_id(),
        space_id=space_id,
        name=name,
        domain="memory",
        policy_json={"allow": "all"},
        enabled=True,
        status="active",
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# Digest generation — creates active digest
# ---------------------------------------------------------------------------


def test_policy_bundle_digest_generation_creates_active_digest(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    assert digest is not None
    assert digest.digest_type == "policy_bundle"
    assert digest.status == "active"
    assert digest.version == 1
    assert digest.space_id == space_id
    assert digest.content is not None


def test_workspace_digest_generation_creates_active_digest(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id)
    svc = ContextDigestService(db)
    digest = svc.generate_workspace_digest(space_id, ws.id)
    assert digest is not None
    assert digest.digest_type == "workspace"
    assert digest.status == "active"
    assert digest.version == 1
    assert digest.scope_id == ws.id


def test_agent_digest_generation_creates_active_digest(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    _active_memory(db, space_id=space_id, scope_type="agent", agent_id=agent.id)
    svc = ContextDigestService(db)
    digest = svc.generate_agent_digest(space_id, agent.id)
    assert digest is not None
    assert digest.digest_type == "agent"
    assert digest.status == "active"
    assert digest.version == 1
    assert digest.scope_id == agent.id


# ---------------------------------------------------------------------------
# Digest uses only active Memory/Policy
# ---------------------------------------------------------------------------


def test_digest_excludes_archived_memory(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    active_m = _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id, content="active")
    archived_m = _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id, content="archived")
    archived_m.status = "archived"
    db.flush()
    svc = ContextDigestService(db)
    digest = svc.generate_workspace_digest(space_id, ws.id)
    assert active_m.id in (digest.source_memory_ids_json or [])
    assert archived_m.id not in (digest.source_memory_ids_json or [])


def test_digest_excludes_superseded_memory(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    sup_m = _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id, content="superseded")
    sup_m.status = "superseded"
    db.flush()
    svc = ContextDigestService(db)
    digest = svc.generate_workspace_digest(space_id, ws.id)
    assert sup_m.id not in (digest.source_memory_ids_json or [])


def test_digest_excludes_proposed_memory(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    prop_m = _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id, content="proposed")
    prop_m.status = "proposed"
    db.flush()
    svc = ContextDigestService(db)
    digest = svc.generate_workspace_digest(space_id, ws.id)
    assert prop_m.id not in (digest.source_memory_ids_json or [])


def test_digest_excludes_disabled_policy(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    disabled_p = _active_policy(db, space_id=space_id, name="disabled-pol")
    disabled_p.enabled = False
    db.flush()
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    assert disabled_p.id not in (digest.source_policy_ids_json or [])


def test_digest_excludes_superseded_policy(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    sup_p = _active_policy(db, space_id=space_id, name="superseded-pol")
    sup_p.status = "superseded"
    db.flush()
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    assert sup_p.id not in (digest.source_policy_ids_json or [])


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def test_same_source_hash_does_not_create_new_version(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    d1 = svc.generate_policy_bundle_digest(space_id)
    d2 = svc.generate_policy_bundle_digest(space_id)
    assert d1.id == d2.id, "Same source_hash must return existing digest"
    assert d2.version == 1

    count = db.query(ContextDigest).filter(
        ContextDigest.space_id == space_id,
        ContextDigest.digest_type == "policy_bundle",
    ).count()
    assert count == 1, "No duplicate digest rows for same source_hash"


def test_changed_source_memory_creates_new_version(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    svc = ContextDigestService(db)
    d1 = svc.generate_workspace_digest(space_id, ws.id)
    assert d1.version == 1

    # Add a new memory — source changes.
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id)
    d2 = svc.generate_workspace_digest(space_id, ws.id)
    assert d2.version == 2, "New memory source must bump version"
    assert d2.id != d1.id, "New digest row created"


def test_old_digest_becomes_superseded_on_new_version(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    svc = ContextDigestService(db)
    d1 = svc.generate_workspace_digest(space_id, ws.id)
    old_id = d1.id
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id)
    svc.generate_workspace_digest(space_id, ws.id)
    db.expire_all()
    old_row = db.query(ContextDigest).filter(ContextDigest.id == old_id).one()
    assert old_row.status == "superseded", "Previous active digest must become superseded"


def test_content_hash_stable_for_same_content(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    _active_policy(db, space_id=space_id, name="stable-pol")
    svc = ContextDigestService(db)
    d1 = svc.generate_policy_bundle_digest(space_id)
    d2 = svc.generate_policy_bundle_digest(space_id)
    assert d1.content_hash == d2.content_hash, "Same content must produce same content_hash"


# ---------------------------------------------------------------------------
# No new truth
# ---------------------------------------------------------------------------


def test_digest_generation_does_not_create_memory_entry(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    before = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    svc.generate_policy_bundle_digest(space_id)
    after = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    assert after == before, "Digest generation must not create MemoryEntry rows"


def test_digest_generation_does_not_create_proposal(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    before = db.query(Proposal).filter(Proposal.space_id == space_id).count()
    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    svc.generate_policy_bundle_digest(space_id)
    after = db.query(Proposal).filter(Proposal.space_id == space_id).count()
    assert after == before, "Digest generation must not create Proposal rows"


# ---------------------------------------------------------------------------
# Dirty tracking
# ---------------------------------------------------------------------------


def test_accepted_workspace_memory_marks_workspace_digest_dirty(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id, content="existing")
    # Generate digest so it exists.
    svc = ContextDigestService(db)
    digest = svc.generate_workspace_digest(space_id, ws.id)
    assert digest.status == "active"

    # Accept a memory_create proposal for the same workspace.
    from app.proposals import ProposalApplyService
    prop = Proposal(
        id=_new_id(),
        space_id=space_id,
        workspace_id=ws.id,
        proposal_type="memory_create",
        status="pending",
        title="new workspace memory",
        payload_json={
            "target_scope": "workspace",
            "proposed_content": "new knowledge",
            "visibility": "space_shared",
            "provenance_entries": [
                {"source_type": "user_confirmed", "source_id": ua.id, "source_trust": "user_confirmed"}
            ],
        },
    )
    db.add(prop)
    db.flush()
    ProposalApplyService(db).apply(
        prop, user_id=ua.id, bypass_source_monitoring=True
    )
    db.flush()

    db.expire_all()
    digest = svc.get_active_digest(space_id, "workspace", ws.id, "workspace")
    assert digest is not None
    assert digest.status == "dirty", "Workspace digest must be dirty after workspace memory change"
    assert digest.dirty_since is not None


def test_accepted_policy_change_marks_policy_bundle_dirty(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    assert digest.status == "active"

    from app.proposals import ProposalApplyService
    prop = Proposal(
        id=_new_id(),
        space_id=space_id,
        proposal_type="policy_change",
        status="pending",
        title="new policy",
        payload_json={
            "domain": "memory.private_placement",
            "rule_json": {"effect": "deny"},
            "provenance_entries": [
                {"source_type": "user_confirmed", "source_id": ua.id, "source_trust": "user_confirmed"}
            ],
        },
    )
    db.add(prop)
    db.flush()
    ProposalApplyService(db).apply(
        prop, user_id=ua.id, bypass_source_monitoring=True
    )
    db.flush()
    db.expire_all()

    digest = svc.get_active_digest(space_id, "space", None, "policy_bundle")
    assert digest is not None
    assert digest.status == "dirty", "Policy bundle digest must be dirty after policy_change"
    assert digest.dirty_since is not None


def test_mark_digest_dirty_noop_when_no_active_digest(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    # No digest generated — mark_digest_dirty should not raise.
    svc = ContextDigestService(db)
    svc.mark_digest_dirty(space_id, "space", None, "policy_bundle", reason="test")
    # No exception → pass. Also no digest row created.
    count = db.query(ContextDigest).filter(
        ContextDigest.space_id == space_id,
        ContextDigest.digest_type == "policy_bundle",
    ).count()
    assert count == 0
