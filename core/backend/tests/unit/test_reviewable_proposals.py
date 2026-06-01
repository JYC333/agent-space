"""Unit tests for reviewable proposal list/count alignment with approval authority.

Covers Scope D: owner/admin/reviewer/member/no-membership reviewability rules and
cross-space exclusion.
"""
from __future__ import annotations
import uuid

import pytest

from app.memory.proposals import ProposalService
from tests.support import factories


def _uid() -> str:
    return str(uuid.uuid4())


def _make_space_user(db, space_id: str, role: str) -> str:
    from app.models import SpaceMembership, User

    uid = _uid()
    db.add(User(id=uid, display_name=role, email=f"{uid}@test.invalid"))
    db.add(SpaceMembership(id=_uid(), space_id=space_id, user_id=uid, role=role, status="active"))
    db.flush()
    return uid


def _make_pending_proposal(db, space_id: str, user_id: str, proposal_type: str = "memory_create",
                            risk_level: str | None = None, visibility: str = "space_shared"):
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=user_id,
        proposal_type=proposal_type, commit=False,
    )
    if risk_level is not None:
        prop.risk_level = risk_level
    prop.visibility = visibility
    db.flush()
    return prop




# ---------------------------------------------------------------------------
# Owner — sees all space-visible pending proposals
# ---------------------------------------------------------------------------

def test_owner_sees_all_space_shared_pending_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member_id = _make_space_user(db, a, "member")

    prop = _make_pending_proposal(db, a, member_id)
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, ua.id)}
    assert prop.id in ids
    assert svc.count_reviewable_proposals(a, ua.id) >= 1


def test_owner_can_see_critical_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, ua.id)}
    assert prop.id in ids


def test_owner_sees_private_proposal_they_created(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = _make_pending_proposal(db, a, ua.id, visibility="private")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, ua.id)}
    assert prop.id in ids
    assert svc.count_reviewable_proposals(a, ua.id) >= 1


# ---------------------------------------------------------------------------
# Admin — sees non-critical space-shared pending proposals
# ---------------------------------------------------------------------------

def test_admin_sees_low_medium_high_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin_id = _make_space_user(db, a, "admin")

    for proposal_type in ["memory_create", "memory_update", "code_patch", "policy_change"]:
        _make_pending_proposal(db, a, ua.id, proposal_type=proposal_type)
    db.commit()

    svc = ProposalService(db)
    results = svc.list_reviewable_proposals(a, admin_id)
    assert len(results) >= 4


def test_admin_does_not_see_critical_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin_id = _make_space_user(db, a, "admin")

    critical_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, admin_id)}
    assert critical_prop.id not in ids


def test_admin_sees_private_proposal_they_created_if_non_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    admin_id = _make_space_user(db, a, "admin")

    private_prop = _make_pending_proposal(db, a, admin_id, risk_level="medium", visibility="private")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, admin_id)}
    assert private_prop.id in ids


def test_admin_does_not_see_private_critical_proposal(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    admin_id = _make_space_user(db, a, "admin")

    critical_private = _make_pending_proposal(db, a, admin_id, risk_level="critical", visibility="private")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, admin_id)}
    assert critical_private.id not in ids


def test_admin_count_excludes_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin_id = _make_space_user(db, a, "admin")

    normal_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create")
    critical_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    db.commit()

    svc = ProposalService(db)
    admin_ids = {p.id for p in svc.list_reviewable_proposals(a, admin_id)}
    assert normal_prop.id in admin_ids
    assert critical_prop.id not in admin_ids


# ---------------------------------------------------------------------------
# Reviewer — sees space-shared low/medium risk proposals; not high or critical
# ---------------------------------------------------------------------------

def test_reviewer_sees_space_shared_low_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    low_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert low_prop.id in ids


def test_reviewer_sees_space_shared_medium_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    medium_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="medium")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert medium_prop.id in ids
    assert svc.count_reviewable_proposals(a, reviewer_id) >= 1


def test_reviewer_does_not_see_high_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    high_prop = _make_pending_proposal(db, a, ua.id, proposal_type="code_patch", risk_level="high")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert high_prop.id not in ids


def test_reviewer_does_not_see_critical_risk_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    critical_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert critical_prop.id not in ids


def test_reviewer_sees_low_risk_memory_create(db, cross_space_pair_db):
    """memory_create with declared low (type default MEDIUM, effective MEDIUM) appears in reviewer inbox."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert prop.id in ids


def test_reviewer_does_not_see_low_risk_code_patch(db, cross_space_pair_db):
    """code_patch with declared low has effective HIGH (type default) — excluded from reviewer inbox."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    patch_low = _make_pending_proposal(db, a, ua.id, proposal_type="code_patch", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert patch_low.id not in ids


def test_reviewer_does_not_see_low_risk_policy_change(db, cross_space_pair_db):
    """policy_change with declared low has effective HIGH (type default) — excluded from reviewer inbox."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    policy_low = _make_pending_proposal(db, a, ua.id, proposal_type="policy_change", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert policy_low.id not in ids


def test_admin_sees_low_risk_code_patch(db, cross_space_pair_db):
    """code_patch with declared low (effective HIGH) is visible in admin inbox; admin approves HIGH."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    admin_id = _make_space_user(db, a, "admin")

    patch_low = _make_pending_proposal(db, a, ua.id, proposal_type="code_patch", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, admin_id)}
    assert patch_low.id in ids


def test_owner_sees_all_visible_proposals(db, cross_space_pair_db):
    """Owner inbox includes space-shared proposals of every type and risk level."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    low_patch = _make_pending_proposal(db, a, ua.id, proposal_type="code_patch", risk_level="low")
    critical_mem = _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    low_mem = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create", risk_level="low")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, ua.id)}
    assert low_patch.id in ids
    assert critical_mem.id in ids
    assert low_mem.id in ids


def test_reviewer_count_excludes_high_and_critical(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    reviewer_id = _make_space_user(db, a, "reviewer")

    low_prop = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create", risk_level="low")
    _make_pending_proposal(db, a, ua.id, proposal_type="code_patch", risk_level="high")
    _make_pending_proposal(db, a, ua.id, proposal_type="memory_update", risk_level="critical")
    db.commit()

    svc = ProposalService(db)
    reviewer_ids = {p.id for p in svc.list_reviewable_proposals(a, reviewer_id)}
    assert low_prop.id in reviewer_ids
    # Neither high nor critical should appear
    for p in svc.list_reviewable_proposals(a, reviewer_id):
        assert p.risk_level not in ("high", "critical")


# ---------------------------------------------------------------------------
# Member — only sees proposals they created or instructed
# ---------------------------------------------------------------------------

def test_member_does_not_see_others_proposals_as_reviewable(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    member_id = _make_space_user(db, a, "member")

    prop_by_owner = _make_pending_proposal(db, a, ua.id, proposal_type="memory_create")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, member_id)}
    assert prop_by_owner.id not in ids


def test_member_sees_their_own_proposals(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    member_id = _make_space_user(db, a, "member")

    my_prop = _make_pending_proposal(db, a, member_id, proposal_type="memory_create")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, member_id)}
    assert my_prop.id in ids


# ---------------------------------------------------------------------------
# Cross-space proposals are never visible
# ---------------------------------------------------------------------------

def test_cross_space_proposals_are_excluded(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    # Proposal in space B, queried with space A context
    prop_b = _make_pending_proposal(db, b, ub.id, proposal_type="memory_create")
    db.commit()

    svc = ProposalService(db)
    ids = {p.id for p in svc.list_reviewable_proposals(a, ua.id)}
    assert prop_b.id not in ids
