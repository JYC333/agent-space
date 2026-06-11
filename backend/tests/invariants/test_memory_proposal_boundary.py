"""Invariant: agent/activity paths do not create active MemoryEntry without approved proposal."""

from __future__ import annotations

from sqlalchemy import func

from app.activity.service import ActivityService
from app.memory.consolidation.service import ActivityConsolidationService
from app.proposals import ProposalService
from app.models import MemoryEntry, Proposal
from tests.support import factories
from tests.support.assertions import assert_memory_unchanged, assert_proposal_not_applied


def test_activity_create_does_not_add_active_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    baseline = frozenset(
        r[0]
        for r in db.query(MemoryEntry.id).filter(MemoryEntry.space_id == a, MemoryEntry.status == "active").all()
    )
    ActivityService(db).create(
        space_id=a,
        source_type="user_input",
        content="hello",
        user_id=ua.id,
        title="t",
    )
    assert_memory_unchanged(db, space_id=a, baseline_ids=baseline, status="active")


def test_activity_proposals_from_does_not_activate_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    baseline = frozenset(
        r[0]
        for r in db.query(MemoryEntry.id).filter(MemoryEntry.space_id == a, MemoryEntry.status == "active").all()
    )
    act = ActivityService(db).create(
        space_id=a,
        source_type="agent_run",
        content="needs memory",
        user_id=ua.id,
        source_run_id=None,
    )
    proposals = ActivityConsolidationService(db).run_for_activity_ids(
        a,
        [act.id],
        acting_user_id=ua.id,
    )
    assert len(proposals) == 1
    assert proposals[0].proposal_type == "memory_create"
    assert proposals[0].status == "pending"
    entries = (proposals[0].payload_json or {}).get("provenance_entries") or []
    assert any(
        e.get("source_type") == "activity" and e.get("source_id") == act.id for e in entries
    )
    assert_memory_unchanged(db, space_id=a, baseline_ids=baseline, status="active")
    assert_proposal_not_applied(db, proposal_id=proposals[0].id, space_id=a)


def test_pending_proposal_factory_row_does_not_create_active_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    baseline = frozenset(
        r[0]
        for r in db.query(MemoryEntry.id).filter(MemoryEntry.space_id == a, MemoryEntry.status == "active").all()
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        status="pending",
        commit=False,
    )
    db.flush()
    assert_memory_unchanged(db, space_id=a, baseline_ids=baseline, status="active")
    assert_proposal_not_applied(db, proposal_id=prop.id, space_id=a)


def test_accept_is_only_service_path_that_adds_active_memory_for_proposal(db, cross_space_pair_db):
    """After ProposalService.accept, active memory exists and links to proposal."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None
    mem = out.memory
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before + 1
    assert mem.source_proposal_id == prop.id
    db.refresh(prop)
    assert prop.status == "accepted"
    assert prop.resulting_memory_id == mem.id
