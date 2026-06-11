"""Invariants: classifier / validator / producer boundaries for activity consolidation."""

from __future__ import annotations
import uuid

import json
from datetime import UTC, datetime

from sqlalchemy import func

from app.memory.consolidation.classifier import DefaultRuleBasedMemoryCandidateClassifier
from app.memory.consolidation.service import ActivityConsolidationService
from app.memory.consolidation.validator import MemoryCandidateValidator
from app.models import ActivityRecord, MemoryEntry, Policy, Proposal
from tests.support import factories


def test_cross_space_candidate_rejected(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    c = clf.classify(act, compiler_version="test")[0]
    c.space_id = b
    v = MemoryCandidateValidator(space_id=a, acting_user_id=ua.id)
    assert v.validate(c).decision == "reject"


def test_classifier_output_alone_creates_no_memory_or_policy(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    before_m = db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar()
    before_p = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="chat_message",
        title="c",
        content="d",
        commit=True,
    )
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    clf.classify(act, compiler_version="test")
    db.commit()
    assert db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar() == before_m
    assert db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar() == before_p


def test_invalid_scope_candidate_rejected(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    cands = clf.classify(act, compiler_version="test")
    assert cands
    c = cands[0]
    c.scope_type = "invalid_scope"
    v = MemoryCandidateValidator(space_id=a, acting_user_id=ua.id)
    assert v.validate(c).decision == "reject"


def test_candidate_without_provenance_rejected(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    c = clf.classify(act, compiler_version="test")[0]
    c.provenance_entries = []
    v = MemoryCandidateValidator(space_id=a, acting_user_id=ua.id)
    assert v.validate(c).decision == "reject"


def test_agent_inferred_semantic_rejected_by_validator(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = ActivityRecord(
        id=str(uuid.uuid4()),
        space_id=a,
        user_id=ua.id,
        activity_type="note",
        title="t",
        content="c",
        payload_json={"consolidation": {"lane": "semantic"}},
        occurred_at=datetime.now(UTC),
        status="raw",
        source_trust="agent_inferred",
        consolidation_status="pending",
    )
    db.add(act)
    db.commit()
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    c = clf.classify(act, compiler_version="test")[0]
    v = MemoryCandidateValidator(space_id=a, acting_user_id=ua.id)
    assert v.validate(c).decision == "reject"


def test_untrusted_external_episodic_is_high_risk_reviewable(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="web_capture",
        title="ext",
        content="x",
        commit=True,
    )
    clf = DefaultRuleBasedMemoryCandidateClassifier()
    c = clf.classify(act, compiler_version="test")[0]
    assert c.risk_level == "high"
    v = MemoryCandidateValidator(space_id=a, acting_user_id=ua.id)
    assert v.validate(c).decision == "create_review_proposal"


def test_policy_candidate_produces_policy_change_proposal(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="policy.x",
        title="p",
        content="c",
        payload_json={"policy_candidate": True},
        source_trust="user_confirmed",
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    out = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert out.proposals_created
    prop = db.query(Proposal).filter(Proposal.id == out.proposals_created[0]).one()
    assert prop.proposal_type == "policy_change"
    assert prop.required_approver_role == "admin"


def test_policy_candidate_does_not_auto_apply(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="policy.x",
        payload_json={"policy_candidate": True},
        source_trust="user_confirmed",
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    out = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    pid = out.proposals_created[0]
    before = db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar()
    db.expire_all()
    assert db.query(Proposal).filter(Proposal.id == pid).one().status == "pending"
    assert db.query(func.count(Policy.id)).filter(Policy.space_id == a).scalar() == before


def test_proposal_dedupe_blocks_second_proposal(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    svc = ActivityConsolidationService(db)
    r1 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert len(r1.proposals_created) == 1
    act2 = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).one()
    act2.consolidation_status = "pending"
    act2.processed_at = None
    db.commit()
    r2 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert r2.proposals_created == []


def test_memory_evolver_does_not_directly_archive(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        scope_type="user",
        subject_user_id=ua.id,
        owner_user_id=ua.id,
        commit=True,
    )
    from app.memory.evolver import MemoryEvolver, _ARCHIVE_THRESHOLD

    ev = MemoryEvolver(db)
    scores = {mem.id: _ARCHIVE_THRESHOLD / 2}
    from unittest import mock

    with mock.patch.object(MemoryEvolver, "compute_fitness_scores", return_value=scores):
        out = ev.decay_and_archive(a, dry_run=False, acting_user_id=ua.id)
    assert out.get("archive_proposals")
    db.refresh(mem)
    assert mem.status == "active"
