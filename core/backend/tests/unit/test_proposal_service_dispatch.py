"""ProposalService dispatches memory_create / memory_update / memory_archive / policy_change / code_patch;
unsupported types are denied at the policy gate with audit_code="unsupported_proposal_type".
"""

from __future__ import annotations

import pytest

from app.memory.proposals import ProposalService
from app.policy.exceptions import PolicyGateBlocked
from tests.support import factories


def test_unsupported_proposal_type_denied_at_policy_gate(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="unknown_dispatch_type",
        commit=True,
    )
    with pytest.raises(PolicyGateBlocked) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.decision.proposal_type == "unknown_dispatch_type"
    assert ei.value.decision.audit_code == "unsupported_proposal_type"


def test_memory_create_accept_creates_memory_entry(db, cross_space_pair_db):
    """memory_create proposals create a new MemoryEntry on acceptance."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    # Factory default is now memory_create.
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    assert prop.proposal_type == "memory_create"
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None and out.updated_paths is None and out.policy is None
    assert out.proposal.status == "accepted"


def test_memory_update_accept_creates_versioned_entry(db, cross_space_pair_db):
    """memory_update proposals create a new versioned MemoryEntry and mark old as superseded."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    # Create an active memory entry to update.
    original = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="original content",
        scope_type="agent",
        namespace="ns.update",
        owner_user_id=ua.id,
        commit=True,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={
            "operation": "update",
            "target_memory_id": original.id,
            "proposed_content": "updated content",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns.update",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None
    assert out.memory.content == "updated content"
    assert out.memory.supersedes_memory_id == original.id

    db.expire_all()
    from app.models import MemoryEntry
    old_row = db.query(MemoryEntry).filter(MemoryEntry.id == original.id).first()
    assert old_row.status == "superseded"


def test_memory_archive_accept_marks_status_archived(db, cross_space_pair_db):
    """memory_archive proposals mark the target MemoryEntry status='archived'."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    target = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="to be archived",
        scope_type="agent",
        namespace="ns.archive",
        owner_user_id=ua.id,
        commit=True,
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
            "target_namespace": "ns.archive",
            "proposed_content": target.content,
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None

    db.expire_all()
    from app.models import MemoryEntry
    row = db.query(MemoryEntry).filter(MemoryEntry.id == target.id).first()
    assert row.status == "archived"
    assert row.deleted_at is None


def test_policy_change_accept_creates_policy(db, cross_space_pair_db):
    """policy_change proposals create a new Policy version on acceptance."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Log agent reads",
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "policy_key": "agent_read_log",
            "rule_json": {"effect": "allow_with_log", "scope": "agent"},
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.policy is not None
    assert out.policy.created_from_proposal_id == prop.id
    assert out.policy.space_id == a


def test_code_patch_accept_uses_code_patch_applier_path(db, cross_space_pair_db, tmp_path, monkeypatch):
    from app.config import settings

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    import hashlib

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    original = b"0"
    (disk / "c.txt").write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="cp",
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "c.txt",
                        "content": "1",
                        "preimage_exists": True,
                        "preimage_sha256": hashlib.sha256(original).hexdigest(),
                    }
                ]
            },
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is None and out.updated_paths == ["c.txt"]
    assert out.proposal.status == "accepted"
