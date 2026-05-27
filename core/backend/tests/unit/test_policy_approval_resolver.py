"""Unit tests for the policy approval resolver (app/policy/approval.py)."""
from __future__ import annotations

import pytest
from ulid import ULID

from app.policy.actions import UnknownPolicyActionError
from app.policy.approval import can_approve_policy_action, get_space_role
from app.policy.decisions import RiskLevel
from tests.support import factories


def _uid() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# get_space_role
# ---------------------------------------------------------------------------

def test_get_space_role_returns_none_for_no_membership(db):
    sid = _uid()
    uid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    assert get_space_role(db, uid, sid) is None


def test_get_space_role_returns_role_for_active_member(db):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    user = factories.create_test_user(db, space_id=sid)
    # create_test_user adds an owner SpaceMembership
    assert get_space_role(db, user.id, sid) == "owner"


def test_get_space_role_returns_none_for_different_space(db):
    sid_a = _uid()
    sid_b = _uid()
    factories.create_test_space(db, space_id=sid_a, space_type="team")
    factories.create_test_space(db, space_id=sid_b, space_type="team")
    user = factories.create_test_user(db, space_id=sid_a)
    assert get_space_role(db, user.id, sid_b) is None


# ---------------------------------------------------------------------------
# Owner can approve all current proposal types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proposal_type", [
    "memory_create",
    "memory_update",
    "memory_archive",
    "follow_up_task",
    "code_patch",
    "policy_change",
    "egress_review",
])
def test_owner_can_approve_all_supported_proposal_types(db, proposal_type):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    user = factories.create_test_user(db, space_id=sid)
    # create_test_user gives role=owner
    assert can_approve_policy_action(
        db,
        user_id=user.id,
        space_id=sid,
        action="proposal.apply",
        proposal_type=proposal_type,
    )


def test_owner_can_approve_critical_action(db):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    user = factories.create_test_user(db, space_id=sid)
    assert can_approve_policy_action(
        db,
        user_id=user.id,
        space_id=sid,
        action="proposal.apply",
        risk_level=RiskLevel.CRITICAL,
    )


# ---------------------------------------------------------------------------
# Admin approval rules
# ---------------------------------------------------------------------------

def _make_admin(db, space_id: str):
    from app.models import SpaceMembership

    uid = _uid()
    from app.models import User
    user = User(id=uid, display_name="admin", email=f"{uid}@test.invalid")
    db.add(user)
    db.add(SpaceMembership(
        id=_uid(),
        space_id=space_id,
        user_id=uid,
        role="admin",
        status="active",
    ))
    db.flush()
    return user


@pytest.mark.parametrize("risk_level", [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH])
def test_admin_can_approve_low_medium_high(db, risk_level):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    admin = _make_admin(db, sid)
    assert can_approve_policy_action(
        db,
        user_id=admin.id,
        space_id=sid,
        action="proposal.apply",
        risk_level=risk_level,
    )


def test_admin_cannot_approve_critical(db):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    admin = _make_admin(db, sid)
    assert not can_approve_policy_action(
        db,
        user_id=admin.id,
        space_id=sid,
        action="proposal.apply",
        risk_level=RiskLevel.CRITICAL,
    )


# ---------------------------------------------------------------------------
# Member / guest cannot approve
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Reviewer approval rules
# ---------------------------------------------------------------------------

def _make_reviewer(db, space_id: str):
    from app.models import SpaceMembership, User

    uid = _uid()
    user = User(id=uid, display_name="reviewer", email=f"{uid}@test.invalid")
    db.add(user)
    db.add(SpaceMembership(
        id=_uid(),
        space_id=space_id,
        user_id=uid,
        role="reviewer",
        status="active",
    ))
    db.flush()
    return user


@pytest.mark.parametrize("risk_level", [RiskLevel.LOW, RiskLevel.MEDIUM])
def test_reviewer_can_approve_low_and_medium(db, risk_level):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    reviewer = _make_reviewer(db, sid)
    assert can_approve_policy_action(
        db,
        user_id=reviewer.id,
        space_id=sid,
        action="proposal.apply",
        risk_level=risk_level,
    )


@pytest.mark.parametrize("risk_level", [RiskLevel.HIGH, RiskLevel.CRITICAL])
def test_reviewer_cannot_approve_high_or_critical(db, risk_level):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    reviewer = _make_reviewer(db, sid)
    assert not can_approve_policy_action(
        db,
        user_id=reviewer.id,
        space_id=sid,
        action="proposal.apply",
        risk_level=risk_level,
    )


@pytest.mark.parametrize("role", ["member", "guest"])
def test_non_privileged_role_cannot_approve(db, role):
    from app.models import SpaceMembership, User

    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    uid = _uid()
    user = User(id=uid, display_name=role, email=f"{uid}@test.invalid")
    db.add(user)
    db.add(SpaceMembership(
        id=_uid(),
        space_id=sid,
        user_id=uid,
        role=role,
        status="active",
    ))
    db.flush()
    assert not can_approve_policy_action(
        db,
        user_id=uid,
        space_id=sid,
        action="proposal.apply",
        proposal_type="memory_update",
    )


@pytest.mark.parametrize("proposal_type", [
    "memory_update",
    "policy_change",
    "code_patch",
    "egress_review",
    "follow_up_task",
])
def test_member_cannot_approve_any_proposal_type(db, proposal_type):
    from app.models import SpaceMembership, User

    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    uid = _uid()
    user = User(id=uid, display_name="member", email=f"{uid}@test.invalid")
    db.add(user)
    db.add(SpaceMembership(
        id=_uid(),
        space_id=sid,
        user_id=uid,
        role="member",
        status="active",
    ))
    db.flush()
    assert not can_approve_policy_action(
        db,
        user_id=uid,
        space_id=sid,
        action="proposal.apply",
        proposal_type=proposal_type,
    )


def test_user_with_no_membership_cannot_approve(db):
    sid = _uid()
    uid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    assert not can_approve_policy_action(
        db,
        user_id=uid,
        space_id=sid,
        action="proposal.apply",
    )


# ---------------------------------------------------------------------------
# Unknown action fail-closed
# ---------------------------------------------------------------------------

def test_unknown_action_raises_for_owner(db):
    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    user = factories.create_test_user(db, space_id=sid)  # role=owner
    with pytest.raises(UnknownPolicyActionError) as exc_info:
        can_approve_policy_action(db, user_id=user.id, space_id=sid, action="agent.delegate")
    assert exc_info.value.action == "agent.delegate"


def test_unknown_action_raises_for_admin(db):
    from app.models import SpaceMembership, User

    sid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    uid = _uid()
    db.add(User(id=uid, display_name="admin", email=f"{uid}@test.invalid"))
    db.add(SpaceMembership(id=_uid(), space_id=sid, user_id=uid, role="admin", status="active"))
    db.flush()
    with pytest.raises(UnknownPolicyActionError):
        can_approve_policy_action(db, user_id=uid, space_id=sid, action="memory.write")


def test_unknown_action_raises_even_with_no_membership(db):
    sid = _uid()
    uid = _uid()
    factories.create_test_space(db, space_id=sid, space_type="team")
    with pytest.raises(UnknownPolicyActionError):
        can_approve_policy_action(db, user_id=uid, space_id=sid, action="tool.execute")


def test_active_action_strings_are_all_registered():
    from app.policy.actions import is_known_action

    active_actions = [
        "runtime.execute",
        "runtime.use_credential",
        "context.inject_memory",
        "context.render_for_runtime",
        "workspace.write_patch",
        "artifact.persist",
        "proposal.create",
        "proposal.apply",
        "memory.create",
        "memory.update",
        "memory.archive",
        "policy.change",
    ]
    for action in active_actions:
        assert is_known_action(action), f"Active action {action!r} is not registered"


def test_unsupported_action_strings_are_not_registered():
    from app.policy.actions import is_known_action

    for action in ["memory.write", "memory.propose", "tool.execute", "agent.run", "agent.delegate"]:
        assert not is_known_action(action), f"Unsupported action {action!r} must not be registered"
