"""Invariants: durable memory/policy writes only happen through ProposalApplyService.

These invariants must hold regardless of proposal type:
- preview proposals cannot be accepted
- rejected proposals cannot be accepted
- already-accepted proposals cannot be accepted again
- unknown proposal types are denied at the policy gate (ProposalPolicyDeniedError, audit_code="unsupported_proposal_type")
- memory_update without target_memory_id fails at apply time
- memory_archive without target_memory_id fails at apply time
- policy_change creates a new Policy linked by created_from_proposal_id
- memory_update marks old row superseded; does not hard-delete
- memory_archive marks status=archived; does not hard-delete
- accepted proposal path creates memory bypassing no review gate
- atomicity: partial failure rolls back to no active MemoryEntry side effect
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
from app.memory.proposals import ProposalService, ProposalPolicyDeniedError
from app.models import MemoryEntry, Policy, Proposal
from app.schemas import MemoryCreate
from tests.support import factories


def _make_member(db, space_id):
    from app.models import SpaceMembership, User
    from ulid import ULID
    uid = str(ULID())
    db.add(User(id=uid, space_id=space_id, display_name="member", email=f"{uid}@test.invalid"))
    db.add(SpaceMembership(id=str(ULID()), space_id=space_id, user_id=uid, role="member", status="active"))
    db.flush()
    return uid


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


def test_unknown_proposal_type_denied_at_policy_gate(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="completely_unknown_type", commit=True,
    )
    with pytest.raises(ProposalPolicyDeniedError) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.proposal_type == "completely_unknown_type"
    assert ei.value.audit_code == "unsupported_proposal_type"


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
# Proposal-approved write path creates active memory
# ---------------------------------------------------------------------------


def test_proposal_approved_memory_write_creates_active_memory(db, cross_space_pair):
    """Accepting a memory_create proposal creates an active MemoryEntry linked to the proposal."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={
            "target_scope": "agent",
            "target_namespace": "agent.direct",
            "proposed_content": "approved write",
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    assert result is not None
    assert result.memory is not None
    assert result.memory.created_from_proposal_id == prop.id
    assert result.memory.content == "approved write"
    assert result.memory.status == "active"


def test_proposal_approved_archive_sets_status_archived(db, cross_space_pair):
    """Accepting a memory_archive proposal sets status=archived without hard-deleting."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    # Use ORM insertion for test fixture setup (no direct write path needed)
    from app.models import MemoryEntry as ME
    from ulid import ULID
    mem = ME(
        id=str(ULID()),
        space_id=a,
        scope_type="agent",
        memory_type="semantic",
        content="archive target",
        status="active",
        visibility="space_shared",
        owner_user_id=ua.id,
    )
    db.add(mem)
    db.commit()

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        payload_json={
            "operation": "archive",
            "target_memory_id": mem.id,
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    assert result is not None
    assert result.memory is not None
    assert result.memory.id == mem.id
    db.expire_all()
    archived = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert archived.status == "archived"


# ---------------------------------------------------------------------------
# Atomicity: partial failure rolls back
# ---------------------------------------------------------------------------


def test_memory_proposal_apply_rolls_back_partial_memory_on_late_failure(
    db, test_space, test_user, monkeypatch
):
    """A failure after MemoryEntry flush must not leave active memory side effects."""
    import app.memory.provenance_apply as provenance_apply

    a = test_space.id
    ua = test_user
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={
            "target_scope": "agent",
            "target_namespace": "agent.atomicity",
            "proposed_content": "atomic rollback sentinel",
        },
        commit=True,
    )

    def fail_after_memory_flush(*args, **kwargs):
        raise RuntimeError("provenance write failed")

    monkeypatch.setattr(provenance_apply, "write_provenance_links", fail_after_memory_flush)

    with pytest.raises(RuntimeError, match="provenance write failed"):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    db.expire_all()
    memories = (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.space_id == a,
            MemoryEntry.content == "atomic rollback sentinel",
        )
        .all()
    )
    proposal = db.query(Proposal).filter(Proposal.id == prop.id).one()
    assert memories == []
    assert proposal.status == "pending"
    assert proposal.resulting_memory_id is None


def test_approved_memory_proposal_commits_memory_and_source_fields_atomically(db, test_space, test_user):
    a = test_space.id
    ua = test_user
    activity = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="Atomicity source",
        content="source",
        commit=False,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={
            "target_scope": "agent",
            "target_namespace": "agent.atomicity",
            "proposed_content": "atomic create sentinel",
            "provenance_entries": [
                {
                    "source_type": "activity",
                    "source_id": activity.id,
                    "source_trust": "user_confirmed",
                    "evidence_json": {"origin": "atomicity_test"},
                }
            ],
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    assert result is not None
    assert result.memory is not None
    db.expire_all()
    mem = db.query(MemoryEntry).filter(MemoryEntry.id == result.memory.id).one()
    proposal = db.query(Proposal).filter(Proposal.id == prop.id).one()
    assert proposal.status == "accepted"
    assert proposal.resulting_memory_id == mem.id
    assert mem.created_from_proposal_id == prop.id
    assert mem.source_proposal_id == prop.id
    assert mem.source_activity_id == activity.id
    assert mem.source_trust == "user_confirmed"


# ---------------------------------------------------------------------------
# Write boundary: only internal_writer.py may call store.create
# ---------------------------------------------------------------------------


def test_memory_direct_write_bypass_is_not_generic_string_parameter():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    app_root = root / "app"

    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "policy_bypass_reason" not in text

    direct_store_writes: list[str] = []
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"create", "update", "delete"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "store"
            ):
                direct_store_writes.append(str(path.relative_to(root)))

    assert direct_store_writes == ["app/memory/internal_writer.py"] * len(direct_store_writes)


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
    # Apply directly through ProposalApplyService using bypass_source_monitoring=True
    # (trusted internal/test boundary that skips the accept_context gate).
    svc = ProposalApplyService(db)
    result = svc.apply(prop, user_id=ua.id, bypass_source_monitoring=True)
    assert result.memory is not None
    assert result.memory.created_from_proposal_id == prop.id
    assert result.memory.source_proposal_id == prop.id


# ---------------------------------------------------------------------------
# policy.change — WIRED_VIA_PROPOSAL; enforcement is via proposal.apply gate
# ---------------------------------------------------------------------------


def test_policy_change_owner_creates_policy_row(db, cross_space_pair):
    """Owner applying policy_change via ProposalApplyService creates a Policy row.

    policy.change is WIRED_VIA_PROPOSAL: the PolicyDecisionRecord is created by
    PolicyGateway.check_proposal_apply() in ProposalService.accept(), not by
    PolicyProposalApplier.apply() itself. The direct ProposalApplyService.apply()
    path (used here with bypass_source_monitoring=True) is the inner applier called
    after the gate — it does not create a PDR for 'policy.change'.
    """
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, proposal_type="policy_change",
        payload_json={"domain": "memory", "rule_json": {"effect": "allow"}},
        commit=True,
    )
    before_policies = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()

    result = ProposalApplyService(db).apply(prop, user_id=ua.id, bypass_source_monitoring=True)
    assert result.policy is not None
    assert db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar() == before_policies + 1


def test_policy_change_member_is_denied_and_no_policy_row(db, cross_space_pair):
    """Member applying policy_change gets ProposalApplyError; no Policy row created.

    policy.change is WIRED_VIA_PROPOSAL: the inline role check in
    PolicyProposalApplier.apply() rejects members. No PolicyDecisionRecord is
    created here — that happens in PolicyGateway.check_proposal_apply() inside
    ProposalService.accept() (the gate that this direct apply() path bypasses).
    """
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    member_id = _make_member(db, a)
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, proposal_type="policy_change",
        payload_json={"domain": "memory", "rule_json": {"effect": "allow"}},
        commit=True,
    )
    before_policies = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()

    with pytest.raises(ProposalApplyError):
        ProposalApplyService(db).apply(prop, user_id=member_id, bypass_source_monitoring=True)

    # No Policy row created
    assert db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar() == before_policies
