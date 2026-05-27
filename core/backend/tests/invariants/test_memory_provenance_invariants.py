"""Invariants: table-level provenance closure for memory and policy apply paths."""

from __future__ import annotations

from sqlalchemy import func

from app.memory.proposals import ProposalService
from app.models import ProvenanceLink
from tests.support import factories


def test_memory_update_keeps_prior_provenance_and_adds_proposal(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    first = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    out1 = ProposalService(db).accept(first.id, space_id=a, user_id=ua.id)
    assert out1.memory is not None
    mid = out1.memory.id
    db.expire_all()
    n0 = (
        db.query(func.count(ProvenanceLink.id))
        .filter(ProvenanceLink.space_id == a, ProvenanceLink.target_id == mid)
        .scalar()
    )
    assert n0 >= 1

    upd = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        title="v2",
        payload_json={
            "operation": "update",
            "target_memory_id": mid,
            "proposed_content": "v2 body",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "agent.test",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
        },
        commit=True,
    )
    out2 = ProposalService(db).accept(upd.id, space_id=a, user_id=ua.id)
    new_id = out2.memory.id
    assert new_id != mid

    db.expire_all()
    n_new = (
        db.query(func.count(ProvenanceLink.id))
        .filter(ProvenanceLink.space_id == a, ProvenanceLink.target_id == new_id)
        .scalar()
    )
    assert n_new >= n0 + 1
    assert (
        db.query(func.count(ProvenanceLink.id))
        .filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_id == new_id,
            ProvenanceLink.source_type == "proposal",
        )
        .scalar()
        >= 1
    )


def test_memory_archive_writes_provenance(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, scope_type="agent", namespace="ns.arc2", owner_user_id=ua.id, commit=True
    )
    arc = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        title="archive",
        payload_json={
            "operation": "archive",
            "target_memory_id": mem.id,
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns.arc2",
            "proposed_content": mem.content,
        },
        commit=True,
    )
    ProposalService(db).accept(arc.id, space_id=a, user_id=ua.id)
    db.expire_all()
    assert (
        db.query(func.count(ProvenanceLink.id))
        .filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_id == mem.id,
            ProvenanceLink.source_type == "proposal",
        )
        .scalar()
        >= 1
    )


def test_policy_change_writes_provenance_links(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="pol",
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "policy_key": "k1",
            "rule_json": {"effect": "allow_with_log"},
        },
        commit=True,
    )
    res = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    pid = res.policy.id
    db.expire_all()
    n = (
        db.query(func.count(ProvenanceLink.id))
        .filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_type == "policy",
            ProvenanceLink.target_id == pid,
        )
        .scalar()
    )
    assert n >= 1
