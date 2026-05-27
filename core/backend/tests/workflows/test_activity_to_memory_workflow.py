"""Activity → proposal → approval → memory (no active memory before accept)."""

from __future__ import annotations

from sqlalchemy import func

from app.models import ActivityRecord, MemoryEntry, Proposal
from tests.support.assertions import assert_proposal_not_applied


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_activity_to_memory_happy_path_provenance_and_idempotent_accept(
    db, workflow_http_pair
):
    cross_space_pair = workflow_http_pair
    db.commit()
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before_mem = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    db.commit()

    r_act = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={
            "source_type": "user_input",
            "content": "workflow evidence",
            "title": "wf-title",
        },
    )
    assert r_act.status_code == 200
    act_id = r_act.json()["id"]
    db.expire_all()
    row_act = db.query(ActivityRecord).filter(ActivityRecord.id == act_id).one()
    assert row_act.space_id == a
    assert row_act.status == "raw"

    r_prop = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{act_id}/consolidate",
        params=_params(a, ua.id),
    )
    assert r_prop.status_code == 200
    created = r_prop.json()
    assert len(created) >= 1
    pid = created[0]["id"]
    assert created[0].get("source_activity_id") == act_id
    assert created[0]["status"] == "pending"

    db.commit()
    db.expire_all()
    assert (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
        == before_mem
    )

    prop_orm = db.query(Proposal).filter(Proposal.id == pid).one()
    assert prop_orm.proposal_type == "memory_create"
    pc = prop_orm.payload_json.get("proposed_content") or ""
    assert "workflow evidence" not in pc
    entries = prop_orm.payload_json.get("provenance_entries") or []
    assert any(e.get("source_type") == "activity" and e.get("source_id") == act_id for e in entries)
    assert_proposal_not_applied(db, proposal_id=pid, space_id=a)
    db.commit()

    r_acc = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{pid}/accept",
        params=_params(a, ua.id),
    )
    assert r_acc.status_code == 200
    mem_id = r_acc.json().get("result", {}).get("memory", {}).get("id")
    assert mem_id

    db.commit()
    db.expire_all()
    mem = db.query(MemoryEntry).filter(MemoryEntry.id == mem_id).one()
    assert mem.space_id == a
    assert mem.status == "active"
    assert mem.source_proposal_id == pid
    assert act_id in (mem.content or "")

    prop_done = db.query(Proposal).filter(Proposal.id == pid).one()
    assert prop_done.status == "accepted"

    db.commit()
    r_dup = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{pid}/accept",
        params=_params(a, ua.id),
    )
    assert r_dup.status_code == 404
    n_linked = (
        db.query(func.count(MemoryEntry.id))
        .filter(
            MemoryEntry.space_id == a,
            MemoryEntry.source_proposal_id == pid,
            MemoryEntry.status == "active",
        )
        .scalar()
    )
    assert n_linked == 1


def test_activity_memory_workflow_blocked_for_other_space(
    db, workflow_http_pair
):
    cross_space_pair = workflow_http_pair
    db.commit()
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]

    act = (
        cross_space_pair["client_a"].post(
            "/api/v1/activity",
            params=_params(a, ua.id),
            json={"source_type": "web_capture", "content": "secret-a", "title": "t"},
        )
        .json()["id"]
    )
    pid = (
        cross_space_pair["client_a"].post(
            f"/api/v1/activity/{act}/consolidate",
            params=_params(a, ua.id),
        )
        .json()[0]["id"]
    )

    assert (
        cross_space_pair["client_b"].patch(
            f"/api/v1/activity/{act}/process",
            params=_params(b, ub.id),
        ).status_code
        == 404
    )
    assert (
        cross_space_pair["client_b"].post(
            f"/api/v1/activity/{act}/consolidate",
            params=_params(b, ub.id),
        ).status_code
        == 404
    )
    assert (
        cross_space_pair["client_b"].post(
            f"/api/v1/proposals/{pid}/accept",
            params=_params(b, ub.id),
        ).status_code
        == 404
    )

    db.expire_all()
    assert db.query(Proposal).filter(Proposal.id == pid).one().status == "pending"
    assert (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == b, MemoryEntry.status == "active")
        .scalar()
        == 0
    )
