"""Workflows: activity consolidation status, idempotency, episodic accept."""

from __future__ import annotations

import json

from app.models import ActivityRecord, Proposal
from app.memory.consolidation.service import ActivityConsolidationService
from app.memory.proposals import ProposalService
from tests.support import factories


def test_pending_activity_becomes_processed_with_episodic_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        title="hello",
        content="secret raw body " * 20,
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert res.proposals_created
    db.refresh(act)
    assert act.consolidation_status == "processed"
    prop = db.query(Proposal).filter(Proposal.id == res.proposals_created[0]).one()
    pc = prop.payload_json.get("proposed_content") or ""
    assert "secret raw body" not in pc
    body = json.loads(pc)
    assert body.get("summary") == "hello"


def test_consolidation_skipped_when_no_reviewable_candidates(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="consolidation.no_candidate",
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert res.proposals_created == []
    db.refresh(act)
    assert act.consolidation_status == "skipped"


def test_accept_episodic_proposal_creates_memory_via_apply(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="chat_message",
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    pid = res.proposals_created[0]
    out = ProposalService(db).accept(pid, space_id=a, user_id=ua.id)
    assert out.memory is not None


def test_semantic_lane_produces_memory_create_or_update_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        payload_json={"consolidation": {"lane": "semantic"}},
        source_trust="user_confirmed",
        commit=True,
    )
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert res.proposals_created
    prop = db.query(Proposal).filter(Proposal.id == res.proposals_created[0]).one()
    assert prop.proposal_type == "memory_create"
    assert (prop.payload_json or {}).get("memory_type") == "semantic"


def test_repeated_consolidation_idempotent(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    svc = ActivityConsolidationService(db)
    r1 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    n1 = len(r1.proposals_created)
    row = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).one()
    row.consolidation_status = "pending"
    row.processed_at = None
    db.commit()
    r2 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert len(r2.proposals_created) == 0
    assert n1 >= 1


def test_accepted_proposal_blocks_duplicate_dedupe(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(db, space_id=a, actor_user_id=ua.id, commit=True)
    svc = ActivityConsolidationService(db)
    r1 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    pid = r1.proposals_created[0]
    ProposalService(db).accept(pid, space_id=a, user_id=ua.id)
    row = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).one()
    row.consolidation_status = "pending"
    row.processed_at = None
    db.commit()
    r2 = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert r2.proposals_created == []


def test_http_consolidate_then_memory_batch_same_dedupe(api_client, db, cross_space_pair):
    """Single-activity HTTP path and batch path share ActivityConsolidationService dedupe."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    aid = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params={"space_id": a},
        json={"source_type": "chat_message", "content": "c", "title": "t"},
    ).json()["id"]
    r1 = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{aid}/consolidate",
        params={"space_id": a},
    )
    assert r1.status_code == 200
    assert r1.json()
    row = db.query(ActivityRecord).filter(ActivityRecord.id == aid).one()
    row.consolidation_status = "pending"
    row.processed_at = None
    db.commit()
    r2 = cross_space_pair["client_a"].post(
        "/api/v1/memory/consolidation/run",
        params={"space_id": a},
        json={"batch_limit": 20, "activity_ids": [aid]},
    )
    assert r2.status_code == 200
    assert r2.json().get("proposals_created") == []


def test_activity_consolidate_ignores_json_body_proposal_fields(api_client, db, cross_space_pair):
    """Unknown JSON keys are ignored; proposal content comes only from the consolidation pipeline."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    aid = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params={"space_id": a},
        json={"source_type": "user_input", "content": "x", "title": "real-title"},
    ).json()["id"]
    r = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{aid}/consolidate",
        params={"space_id": a},
        json={"proposed_title": "injected", "proposed_content": "injected-body"},
    )
    assert r.status_code == 200
    props = r.json()
    assert props
    for p in props:
        assert p.get("proposed_title") != "injected"
        assert "injected-body" not in (p.get("proposed_content") or "")


def test_consolidation_does_not_create_active_memory(db, test_user):
    from app.models import MemoryEntry

    a = test_user.space_id
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=test_user.id,
        activity_type="user_input",
        source_trust="user_confirmed",
        commit=True,
    )
    before = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a,
        MemoryEntry.status == "active",
    ).count()

    res = ActivityConsolidationService(db).run_pending(
        space_id=a,
        acting_user_id=test_user.id,
        activity_ids=[act.id],
    )

    assert res.proposals_created
    assert db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a,
        MemoryEntry.status == "active",
    ).count() == before


def test_consolidation_proposal_preserves_activity_provenance(db, test_user):
    a = test_user.space_id
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=test_user.id,
        activity_type="user_input",
        source_trust="user_confirmed",
        commit=True,
    )

    res = ActivityConsolidationService(db).run_pending(
        space_id=a,
        acting_user_id=test_user.id,
        activity_ids=[act.id],
    )

    prop = db.query(Proposal).filter(Proposal.id == res.proposals_created[0]).one()
    entries = (prop.payload_json or {}).get("provenance_entries") or []
    assert any(
        e.get("source_type") == "activity" and e.get("source_id") == act.id
        for e in entries
    )


def test_consolidation_classifier_runs_without_open_transaction(db, test_user):
    observed: list[bool] = []

    class ObservingClassifier:
        def classify(self, record, *, compiler_version: str):
            observed.append(db.in_transaction())
            return []

    act = factories.create_test_activity(
        db,
        space_id=test_user.space_id,
        actor_user_id=test_user.id,
        activity_type="consolidation.no_candidate",
        commit=True,
    )

    ActivityConsolidationService(db, classifier=ObservingClassifier()).run_pending(
        space_id=test_user.space_id,
        acting_user_id=test_user.id,
        activity_ids=[act.id],
    )

    assert observed == [False]


def test_consolidation_proposal_failure_rolls_back_partial_proposal(db, test_user, monkeypatch):
    from app.memory.consolidation import proposal_producer
    from app.models import MemoryEntry
    from ulid import ULID

    a = test_user.space_id
    ua = test_user
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        source_trust="user_confirmed",
        commit=True,
    )
    before_memory = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a,
        MemoryEntry.status == "active",
    ).count()

    def add_then_fail(self, candidate, **kwargs):
        db.add(
            Proposal(
                id=str(ULID()),
                space_id=a,
                proposal_type="memory_create",
                status="pending",
                title="partial",
                payload_json={"provenance_entries": candidate.provenance_entries},
                created_by_user_id=ua.id,
            )
        )
        db.flush()
        raise RuntimeError("proposal side effect failed")

    monkeypatch.setattr(
        proposal_producer.MemoryProposalProducer,
        "create_from_candidate",
        add_then_fail,
    )

    res = ActivityConsolidationService(db).run_pending(
        space_id=a,
        acting_user_id=ua.id,
        activity_ids=[act.id],
    )

    assert res.activities_failed == [act.id]
    assert db.query(Proposal).filter(Proposal.space_id == a, Proposal.title == "partial").count() == 0
    assert db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a,
        MemoryEntry.status == "active",
    ).count() == before_memory
    db.refresh(act)
    assert act.consolidation_status == "failed"
