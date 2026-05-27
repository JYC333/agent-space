"""Contracts: activity consolidation HTTP + job handler registration."""

from __future__ import annotations

from datetime import UTC, datetime
from ulid import ULID

from app.jobs.handlers import get_handler, list_registered
from app.models import ActivityRecord, Proposal


def test_memory_consolidation_handler_registered():
    assert "memory_consolidation" in list_registered()
    assert get_handler("memory_consolidation") is not None


def test_post_memory_consolidation_run_returns_run_summary(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params={"space_id": a},
        json={"source_type": "chat_message", "content": "hello consolidation", "title": "t"},
    )
    r = cross_space_pair["client_a"].post(
        "/api/v1/memory/consolidation/run",
        params={"space_id": a},
        json={"batch_limit": 20},
    )
    assert r.status_code == 200
    data = r.json()
    assert "consolidation_run_id" in data
    assert isinstance(data.get("proposals_created"), list)
    assert data["proposals_created"]


def test_post_activity_consolidate_returns_proposal_list(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    aid = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params={"space_id": a},
        json={"source_type": "user_input", "content": "x", "title": "y"},
    ).json()["id"]
    r = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{aid}/consolidate",
        params={"space_id": a},
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and data[0].get("id")



def test_consolidation_proposal_payload_has_dedupe_and_provenance(db, cross_space_pair_db):
    from app.memory.consolidation.service import ActivityConsolidationService

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    act = ActivityRecord(
        id=str(ULID()),
        space_id=a,
        user_id=ua.id,
        activity_type="chat_message",
        title="t",
        content="body",
        payload_json={},
        occurred_at=datetime.now(UTC),
        status="raw",
        consolidation_status="pending",
    )
    db.add(act)
    db.commit()
    svc = ActivityConsolidationService(db)
    res = svc.run_pending(space_id=a, acting_user_id=ua.id, activity_ids=[act.id])
    assert res.proposals_created
    prop = db.query(Proposal).filter(Proposal.id == res.proposals_created[0]).one()
    p = prop.payload_json or {}
    assert p.get("proposal_dedupe_key")
    assert p.get("memory_candidate_hash")
    assert p.get("compiler_version")
    assert p.get("provenance_entries")
