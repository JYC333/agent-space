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

from app.memory.internal_writer import MemoryInternalWriter
from app.memory.apply_service import (
    MemoryProposalApplier,
    PolicyProposalApplier,
    ProposalApplyError,
    ProposalApplyService,
)
from app.memory.proposals import ProposalService, UnsupportedProposalTypeError
from app.models import MemoryEntry, Policy, Proposal
from app.schemas import MemoryCreate, MemoryUpdate
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


def _direct_memory_create(space_id: str, owner_user_id: str, *, content: str = "direct") -> MemoryCreate:
    return MemoryCreate(
        title="direct memory",
        content=content,
        type="semantic",
        scope="agent",
        namespace="agent.direct",
        space_id=space_id,
        visibility="space_shared",
        owner_user_id=owner_user_id,
    )


def _memory_write_policy_payload(effect: str = "deny") -> dict:
    return {
        "operation": "create",
        "domain": "memory",
        "policy_key": "memory.write_direct.guard",
        "enforcement_mode": effect,
        "rule_json": {
            "policy_type": "memory_write",
            "action": "memory.write_direct",
            "resource_type": "memory",
            "effect": effect,
            "reason": "Direct memory writes must use proposal review",
        },
    }


def test_accepted_memory_write_direct_policy_blocks_direct_internal_write(db, test_space, test_user):
    a = test_space.id
    ua = test_user
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Require proposal review for direct memory writes",
        payload_json=_memory_write_policy_payload("deny"),
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.policy is not None
    assert result.policy.status == "active"
    assert result.policy.created_from_proposal_id == prop.id

    with pytest.raises(PermissionError) as exc:
        MemoryInternalWriter(db).create(
            _direct_memory_create(a, ua.id),
            acting_user_id=ua.id,
        )
    assert "memory.write_direct.guard" in str(exc.value)


def test_memory_write_direct_require_approval_policy_blocks_direct_internal_write(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key="memory.write_direct.guard",
        enforcement_mode="require_approval",
        rule_json=_memory_write_policy_payload("require_approval")["rule_json"],
    )

    with pytest.raises(PermissionError) as exc:
        MemoryInternalWriter(db).create(
            _direct_memory_create(a, ua.id),
            acting_user_id=ua.id,
        )
    assert "require_approval" in str(exc.value).lower()


def test_proposal_approved_memory_write_bypasses_direct_write_policy(db, test_space, test_user):
    a = test_space.id
    ua = test_user
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key="memory.write_direct.guard",
        enforcement_mode="deny",
        rule_json=_memory_write_policy_payload("deny")["rule_json"],
    )
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


def test_direct_memory_mutations_are_blocked_by_active_direct_write_policy(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = MemoryInternalWriter(db).create(
        _direct_memory_create(a, ua.id, content="before policy"),
        acting_user_id=ua.id,
    )
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key="memory.write_direct.guard",
        enforcement_mode="deny",
        rule_json=_memory_write_policy_payload("deny")["rule_json"],
    )

    writer = MemoryInternalWriter(db)
    with pytest.raises(PermissionError):
        writer.update(
            mem.id,
            a,
            MemoryUpdate(content="blocked update"),
            acting_user_id=ua.id,
        )
    with pytest.raises(PermissionError):
        writer.mark_status(mem.id, a, "archived", acting_user_id=ua.id)
    with pytest.raises(PermissionError):
        writer.delete(mem.id, a, acting_user_id=ua.id)


def test_proposal_approved_archive_bypasses_direct_write_policy(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = MemoryInternalWriter(db).create(
        _direct_memory_create(a, ua.id, content="archive target"),
        acting_user_id=ua.id,
    )
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key="memory.write_direct.guard",
        enforcement_mode="deny",
        rule_json=_memory_write_policy_payload("deny")["rule_json"],
    )
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


def test_inactive_rejected_and_unrelated_policies_do_not_block_direct_write(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    rejected = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Rejected policy",
        payload_json=_memory_write_policy_payload("deny"),
        commit=True,
    )
    assert ProposalService(db).reject(rejected.id, space_id=a, user_id=ua.id) is not None
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        status="disabled",
        policy_key="memory.write_direct.disabled",
        enforcement_mode="deny",
        rule_json=_memory_write_policy_payload("deny")["rule_json"],
    )
    factories.create_test_policy(
        db,
        space_id=a,
        domain="runtime",
        policy_key="runtime.execute.deny",
        enforcement_mode="deny",
        rule_json={
            "policy_type": "runtime_execution",
            "action": "runtime.execute",
            "resource_type": "run",
            "effect": "deny",
        },
    )
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key="symbolic.only",
        enforcement_mode="deny",
        policy_json={"effect": "deny", "reason": "missing M5 selector"},
    )

    mem = MemoryInternalWriter(db).create(
        _direct_memory_create(a, ua.id, content="allowed direct write"),
        acting_user_id=ua.id,
    )

    assert mem.content == "allowed direct write"


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
    # Apply directly through ProposalApplyService (the allowed internal boundary).
    svc = ProposalApplyService(db)
    result = svc.apply(prop, user_id=ua.id)
    assert result.memory is not None
    assert result.memory.created_from_proposal_id == prop.id
    assert result.memory.source_proposal_id == prop.id
