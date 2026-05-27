"""Invariant: pending/rejected proposals never apply durable memory; accepted applies once."""

from __future__ import annotations

import pytest
from sqlalchemy import func

from app.memory.proposals import ProposalService
from app.models import MemoryEntry, Proposal
from app.policy.exceptions import PolicyGateBlocked
from tests.support import factories


def test_pending_proposal_reject_does_not_create_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=False)
    db.flush()
    rej = ProposalService(db).reject(prop.id, space_id=a, user_id=ua.id)
    assert rej is not None
    db.refresh(prop)
    assert prop.status == "rejected"
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_rejected_proposal_cannot_be_accepted(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=False)
    db.flush()
    ProposalService(db).reject(prop.id, space_id=a, user_id=ua.id)
    assert ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id) is None


def test_accept_applies_once_second_accept_is_noop(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=False)
    db.commit()
    first = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert first is not None
    second = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert second is None
    n = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.source_proposal_id == prop.id, MemoryEntry.status == "active")
        .scalar()
    )
    assert n == 1


def test_wrong_reviewer_cannot_reject_or_accept(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]  # owner in space_b, no membership in space_a
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    # Reject still uses the original creator check; ub is not the creator so None is returned.
    assert ProposalService(db).reject(prop.id, space_id=a, user_id=ub.id) is None
    # Accept now uses the policy gate; ub has no membership in space_a → policy denied.
    with pytest.raises(PolicyGateBlocked):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ub.id)
    db.refresh(prop)
    assert prop.status == "pending"


def test_preview_memory_update_cannot_be_accepted(db, cross_space_pair_db):
    """Dry-run / preview proposals must not materialize active memory."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        preview=True,
        commit=False,
    )
    db.flush()
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id) is None
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before
    db.refresh(prop)
    assert prop.status == "pending"


def test_accepted_proposal_retains_run_provenance_when_set(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=False)
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        run_id=run.id,
        created_by_user_id=ua.id,
        commit=False,
    )
    db.commit()
    ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    db.refresh(prop)
    row = db.query(Proposal).filter(Proposal.id == prop.id).one()
    assert row.created_by_run_id == run.id
    assert row.resulting_memory_id is not None


def test_preview_proposal_reject_does_not_create_memory_accept_stays_blocked(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        preview=True,
        commit=False,
    )
    db.flush()
    rej = ProposalService(db).reject(prop.id, space_id=a, user_id=ua.id)
    assert rej is not None
    db.refresh(prop)
    assert prop.status == "rejected"
    assert (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
        == before
    )
    assert ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id) is None
