"""Workflow: Activity-sourced proposals close provenance on accepted memory."""

from __future__ import annotations

from sqlalchemy import func

from app.models import MemoryEntry, ProvenanceLink, Proposal
from tests.support.assertions import assert_proposal_not_applied


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_activity_proposal_accept_writes_provenance_links(api_client, db, cross_space_pair):
    db.commit()
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    act_id = api_client.post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={"source_type": "user_input", "content": "evidence body", "title": "ev-title"},
    ).json()["id"]

    pid = api_client.post(
        f"/api/v1/activity/{act_id}/consolidate",
        params=_params(a, ua.id),
    ).json()[0]["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == pid).one()
    entries = prop.payload_json.get("provenance_entries") or []
    assert any(e.get("source_type") == "activity" and e.get("source_id") == act_id for e in entries)
    assert_proposal_not_applied(db, proposal_id=pid, space_id=a)

    r_acc = api_client.post(f"/api/v1/proposals/{pid}/accept", params=_params(a, ua.id))
    assert r_acc.status_code == 200
    mem_id = r_acc.json().get("result", {}).get("memory", {}).get("id")
    assert mem_id

    db.commit()
    db.expire_all()
    links = (
        db.query(func.count(ProvenanceLink.id))
        .filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_type == "memory",
            ProvenanceLink.target_id == mem_id,
        )
        .scalar()
    )
    assert links >= 2

    src_types = {
        row[0]
        for row in db.query(ProvenanceLink.source_type).filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_id == mem_id,
        )
    }
    assert "activity" in src_types
    assert "proposal" in src_types

    mem = db.query(MemoryEntry).filter(MemoryEntry.id == mem_id).one()
    assert mem.created_from_proposal_id == pid
