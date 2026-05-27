"""Invariants for the proposal.apply policy gate.

Policy denial must happen *before* any durable write (ProposalApplyService.apply,
MemoryEntry, Policy, Task, code patch) is attempted.

Owner and admin actors get through the gate; member/guest and users
with no space membership are denied.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func
from ulid import ULID

from app.memory.proposals import ProposalService
from app.models import MemoryEntry, Policy, PolicyDecisionRecord, Proposal, Task
from app.policy.audit import write_blocked_gate_audit
from app.policy.exceptions import PolicyGateBlocked
from tests.support import factories


def _uid() -> str:
    return str(ULID())


def _make_space_user(db, space_id: str, role: str):
    """Create a user with the given role in space_id."""
    from app.models import SpaceMembership, User

    uid = _uid()
    user = User(id=uid, display_name=role, email=f"{uid}@test.invalid")
    db.add(user)
    db.add(SpaceMembership(
        id=_uid(),
        space_id=space_id,
        user_id=uid,
        role=role,
        status="active",
    ))
    db.flush()
    return user


# ---------------------------------------------------------------------------
# Owner can accept and apply — existing behavior preserved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proposal_type", [
    "memory_create",
    "memory_update",
    "memory_archive",
    "policy_change",
    "follow_up_task",
])
def test_owner_can_accept_supported_proposal_types(db, cross_space_pair_db, proposal_type):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]  # role=owner

    if proposal_type == "memory_update":
        target = factories.create_test_memory_entry(
            db, space_id=a, content="old", scope_type="agent", namespace="ns.gate",
            owner_user_id=ua.id, commit=False,
        )
        target.visibility = "space_shared"
        db.flush()
        payload_extra = {"target_memory_id": target.id}
    elif proposal_type == "memory_archive":
        target = factories.create_test_memory_entry(
            db, space_id=a, content="old", scope_type="agent", namespace="ns.gate2",
            owner_user_id=ua.id, commit=False,
        )
        target.visibility = "space_shared"
        db.flush()
        payload_extra = {"target_memory_id": target.id}
    elif proposal_type == "follow_up_task":
        payload_extra = {"task": {"title": "Gate test task"}}
    elif proposal_type == "policy_change":
        payload_extra = {
            "domain": "memory.private_placement",
            "rule_json": {"effect": "allow_with_log"},
        }
    else:
        payload_extra = None

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type=proposal_type,
        payload_json=payload_extra,
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    db.refresh(prop)
    assert prop.status == "accepted"


# ---------------------------------------------------------------------------
# Admin can accept — low/medium/high proposal types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proposal_type,risk", [
    ("memory_create", "medium"),
    ("memory_update", "medium"),
    ("policy_change", "high"),
    ("code_patch", "high"),
])
def test_admin_can_accept_supported_proposal_types(db, cross_space_pair_db, proposal_type, risk):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]  # original creator (owner)
    admin = _make_space_user(db, a, "admin")

    if proposal_type == "memory_update":
        target = factories.create_test_memory_entry(
            db, space_id=a, content="orig", scope_type="agent", namespace="ns.admin",
            owner_user_id=ua.id, commit=False,
        )
        target.visibility = "space_shared"
        db.flush()
        payload = {"target_memory_id": target.id}
    elif proposal_type == "code_patch":
        ws = factories.create_test_workspace(
            db, space_id=a, created_by_user_id=ua.id,
            allow_external_root=True,
        )
        db.flush()
        # A code_patch proposal that will fail at apply (empty operations) — but the
        # GATE must pass before apply is attempted. The key invariant is: no
        # PolicyGateBlocked is raised (gate passes for admin).
        payload = {"patch": {"files": []}}
        prop = factories.create_test_proposal(
            db, space_id=a, created_by_user_id=ua.id,
            proposal_type=proposal_type, workspace_id=ws.id,
            payload_json=payload, commit=True,
        )
        from fastapi import HTTPException
        from app.memory.apply_service import ProposalApplyError
        from app.memory.code_patch_apply import CodePatchApplyError
        try:
            ProposalService(db).accept(prop.id, space_id=a, user_id=admin.id)
        except (HTTPException, ProposalApplyError, CodePatchApplyError):
            pass  # gate passed; apply may fail due to empty patch — that's OK
        # If PolicyGateBlocked were raised the test would already have failed.
        return
    elif proposal_type == "policy_change":
        payload = {
            "domain": "memory.private_placement",
            "rule_json": {"effect": "allow_with_log"},
        }
    else:
        payload = None

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type=proposal_type,
        payload_json=payload,
        commit=True,
    )
    result = ProposalService(db).accept(prop.id, space_id=a, user_id=admin.id)
    assert result is not None
    db.refresh(prop)
    assert prop.status == "accepted"


# ---------------------------------------------------------------------------
# Member cannot accept — policy gate must deny before any apply
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proposal_type", [
    "memory_create",
    "memory_update",
    "memory_archive",
    "policy_change",
    "code_patch",
    "follow_up_task",
])
def test_member_cannot_accept_any_proposal_type(db, cross_space_pair_db, proposal_type):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    if proposal_type == "memory_update":
        target = factories.create_test_memory_entry(
            db, space_id=a, content="orig", scope_type="agent", namespace="ns.m",
            owner_user_id=ua.id, commit=False,
        )
        target.visibility = "space_shared"
        db.flush()
        payload = {"target_memory_id": target.id}
    elif proposal_type == "memory_archive":
        target = factories.create_test_memory_entry(
            db, space_id=a, content="orig", scope_type="agent", namespace="ns.ma",
            owner_user_id=ua.id, commit=False,
        )
        target.visibility = "space_shared"
        db.flush()
        payload = {"target_memory_id": target.id}
    elif proposal_type == "follow_up_task":
        payload = {"task": {"title": "Member gate task"}}
    else:
        payload = None

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type=proposal_type,
        payload_json=payload,
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    assert exc_info.value.decision.proposal_type == proposal_type
    db.refresh(prop)
    assert prop.status == "pending"


@pytest.mark.parametrize("role", ["guest", "member"])
def test_unprivileged_cannot_accept_proposal(db, cross_space_pair_db, role):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    unprivileged = _make_space_user(db, a, role)

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )
    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=unprivileged.id)

    db.refresh(prop)
    assert prop.status == "pending"


# ---------------------------------------------------------------------------
# Policy denial guarantees no durable side effects
# ---------------------------------------------------------------------------

def test_denied_apply_does_not_create_memory_entry(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a)
        .scalar()
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a)
        .scalar()
    )
    assert after == before
    db.refresh(prop)
    assert prop.status == "pending"


def test_denied_apply_does_not_create_policy(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="policy_change",
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "policy_key": "gate_test_deny",
            "rule_json": {"effect": "allow_with_log"},
        },
        commit=True,
    )

    before = (
        db.query(func.count(Policy.id))
        .filter(Policy.space_id == a)
        .scalar()
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    after = (
        db.query(func.count(Policy.id))
        .filter(Policy.space_id == a)
        .scalar()
    )
    assert after == before
    db.refresh(prop)
    assert prop.status == "pending"


def test_policy_change_accept_is_controlled_by_enforce_proposal_apply(db, cross_space_pair_db):
    """policy_change must pass through enforce_proposal_apply before any policy write."""
    from unittest.mock import patch
    from app.policy.decisions import Decision, PolicyDecision, RiskLevel

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "policy_key": "gate_controls_policy_change",
            "rule_json": {"effect": "allow_with_log"},
        },
        commit=True,
    )

    before = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()
    blocked = PolicyGateBlocked(
        decision=PolicyDecision(
            decision=Decision.DENY,
            message="blocked by proposal apply gate",
            risk_level=RiskLevel.HIGH,
            reason_code="insufficient_role",
            policy_rule_id="proposal_apply_insufficient_role",
            audit_code="insufficient_role",
            proposal_type="policy_change",
        ),
        action="proposal.apply",
        actor_type="user",
        actor_id=ua.id,
        actor_ref=None,
        space_id=a,
        resource_type="proposal",
        resource_id=prop.id,
        run_id=None,
        proposal_id=prop.id,
        metadata_json={"proposal_type": "policy_change"},
    )

    with patch(
        "app.memory.proposals.PolicyGateway.enforce_proposal_apply",
        side_effect=blocked,
    ) as enforce:
        with patch("app.memory.apply_service.ProposalApplyService.apply") as apply:
            with pytest.raises(PolicyGateBlocked):
                ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    enforce.assert_called_once()
    apply.assert_not_called()
    after = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()
    assert after == before
    db.refresh(prop)
    assert prop.status == "pending"


def test_denied_apply_does_not_create_task(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="follow_up_task",
        payload_json={"task": {"title": "Should not be created"}},
        commit=True,
    )

    before = (
        db.query(func.count(Task.id))
        .filter(Task.space_id == a)
        .scalar()
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    after = (
        db.query(func.count(Task.id))
        .filter(Task.space_id == a)
        .scalar()
    )
    assert after == before


# ---------------------------------------------------------------------------
# User with no space membership is denied
# ---------------------------------------------------------------------------

def test_user_with_no_membership_cannot_accept(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    outsider_id = _uid()

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=outsider_id)

    db.refresh(prop)
    assert prop.status == "pending"


# ---------------------------------------------------------------------------
# Unsupported proposal type — denied at the policy gate, never reaches apply
# ---------------------------------------------------------------------------

def test_unsupported_proposal_type_denied_at_policy_gate(db, cross_space_pair_db):
    """Unsupported proposal types are denied by the policy gate with PolicyGateBlocked."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="workspace_profile_update",
        payload_json={},
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    err = exc_info.value
    assert err.decision.audit_code == "unsupported_proposal_type"
    assert err.decision.decision.value == "deny"
    assert err.decision.proposal_type == "workspace_profile_update"
    db.refresh(prop)
    assert prop.status == "pending"


def test_unsupported_proposal_type_records_policy_decision_record(db, cross_space_pair_db):
    """Gate denial for unsupported types is persisted as a PolicyDecisionRecord."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="publish_content",
        payload_json={},
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    write_blocked_gate_audit(exc_info.value)

    rec = (
        db.query(PolicyDecisionRecord)
        .filter(
            PolicyDecisionRecord.action == "proposal.apply",
            PolicyDecisionRecord.proposal_id == prop.id,
        )
        .first()
    )
    assert rec is not None
    assert rec.decision == "deny"
    assert rec.audit_code == "unsupported_proposal_type"


def test_unsupported_proposal_type_does_not_create_memory(db, cross_space_pair_db):
    """Unsupported type gate denial must not trigger any durable write."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="workspace_profile_update",
        payload_json={"proposed_content": "should not be written"},
        commit=True,
    )

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a)
        .scalar()
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)

    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a)
        .scalar()
    )
    assert after == before
    db.refresh(prop)
    assert prop.status == "pending"


# ---------------------------------------------------------------------------
# Reviewer role — approves low/medium proposals via ProposalService.accept()
# ---------------------------------------------------------------------------

def test_reviewer_can_accept_medium_risk_memory_proposal(db, cross_space_pair_db):
    """Reviewer can accept a medium-risk memory_create proposal."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer = _make_space_user(db, a, "reviewer")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=reviewer.id)
    assert result is not None
    db.refresh(prop)
    assert prop.status == "accepted"


def test_reviewer_cannot_accept_high_risk_code_patch(db, cross_space_pair_db):
    """Reviewer cannot accept a high-risk code_patch proposal; gate must deny before any apply."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer = _make_space_user(db, a, "reviewer")

    ws = factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id,
        allow_external_root=True,
    )
    db.flush()

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="code_patch", workspace_id=ws.id,
        payload_json={"patch": {"files": []}},
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=reviewer.id)

    assert exc_info.value.decision.audit_code == "insufficient_role"
    db.refresh(prop)
    assert prop.status == "pending"


def test_admin_can_accept_high_risk_code_patch(db, cross_space_pair_db):
    """Admin can accept high-risk code_patch; policy gate must not deny."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin = _make_space_user(db, a, "admin")

    ws = factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id,
        allow_external_root=True,
    )
    db.flush()

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="code_patch", workspace_id=ws.id,
        payload_json={"patch": {"files": []}},
        commit=True,
    )

    # Gate must pass; apply may fail on empty patch — that is OK.
    from fastapi import HTTPException
    from app.memory.apply_service import ProposalApplyError
    from app.memory.code_patch_apply import CodePatchApplyError
    try:
        ProposalService(db).accept(prop.id, space_id=a, user_id=admin.id)
    except (HTTPException, ProposalApplyError, CodePatchApplyError):
        pass  # gate passed; apply-level failure is acceptable here


def test_admin_cannot_accept_critical_proposal(db, cross_space_pair_db):
    """Admin cannot accept a critical-risk proposal; gate must deny."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin = _make_space_user(db, a, "admin")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={},
        commit=False,
    )
    prop.risk_level = "critical"
    db.flush()

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=admin.id)

    assert exc_info.value.decision.risk_level.value == "critical"
    db.refresh(prop)
    assert prop.status == "pending"


def test_owner_can_accept_critical_proposal(db, cross_space_pair_db):
    """Owner can accept a critical-risk proposal."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    target = factories.create_test_memory_entry(
        db, space_id=a, content="old", scope_type="agent", namespace="ns.critgate",
        owner_user_id=ua.id, commit=False,
    )
    target.visibility = "space_shared"
    db.flush()

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={"target_memory_id": target.id},
        commit=False,
    )
    prop.risk_level = "critical"
    db.commit()

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    db.refresh(prop)
    assert prop.status == "accepted"


# ---------------------------------------------------------------------------
# Regression: existing approval boundary tests still hold
# ---------------------------------------------------------------------------

def test_pending_proposal_reject_does_not_create_memory_regression(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, commit=False,
    )
    db.flush()
    rej = ProposalService(db).reject(prop.id, space_id=a, user_id=ua.id)
    assert rej is not None
    assert prop.status == "rejected"
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_accept_applies_once_second_accept_is_noop_regression(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, commit=False,
    )
    db.commit()
    first = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert first is not None
    second = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert second is None


def test_cross_space_user_cannot_accept_regardless_of_role(db, cross_space_pair_db):
    """A user who is owner in their own space cannot accept proposals in a different space."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]  # owner in space_b, has no membership in space_a

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, commit=True,
    )

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ub.id)

    db.refresh(prop)
    assert prop.status == "pending"


def test_policy_denial_happens_before_apply_side_effects(db, cross_space_pair_db):
    """ProposalApplyService.apply must NOT be called when gate denies."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    prop = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id,
        proposal_type="memory_create", commit=True,
    )

    # Verify the proposal is still pending and no memory was created
    before_memories = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.source_proposal_id == prop.id)
        .scalar()
    )
    assert before_memories == 0

    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    db.refresh(prop)
    assert prop.status == "pending"
    assert prop.resulting_memory_id is None

    after_memories = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.source_proposal_id == prop.id)
        .scalar()
    )
    assert after_memories == 0


# ---------------------------------------------------------------------------
# Payload approval flags cannot authorize proposal.apply
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [
    "approved_by_user",
    "approved_by_granting_user",
    "is_approved",
    "auto_approved",
    "pre_approved",
])
def test_payload_approval_flag_cannot_authorize_accept(db, cross_space_pair_db, flag):
    """Payload flags claiming approval must be rejected by HardInvariantGuard before role checks."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member = _make_space_user(db, a, "member")

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={flag: True, "proposed_content": "test"},
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=member.id)

    db.refresh(prop)
    assert prop.status == "pending"
    assert exc_info.value.decision.audit_code == "payload_flag_as_approval_proof"


def test_payload_approval_flag_denial_creates_policy_decision_record(db, cross_space_pair_db):
    """Hard invariant denial for payload flags must be persisted as a PolicyDecisionRecord."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={"auto_approved": True, "proposed_content": "test"},
        commit=True,
    )

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    write_blocked_gate_audit(exc_info.value)

    rec = (
        db.query(PolicyDecisionRecord)
        .filter(
            PolicyDecisionRecord.action == "proposal.apply",
            PolicyDecisionRecord.proposal_id == prop.id,
        )
        .first()
    )
    assert rec is not None
    assert rec.decision == "deny"
    assert rec.audit_code == "payload_flag_as_approval_proof"
