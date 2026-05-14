"""Contract: public memory write routes create Proposals, never direct MemoryEntry mutations.

- POST   /memory          → 202 + memory_create Proposal
- PATCH  /memory/{id}     → 202 + memory_update Proposal
- DELETE /memory/{id}     → 202 + memory_archive Proposal
"""

from __future__ import annotations

from sqlalchemy import func

from app.models import MemoryEntry, Proposal
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


# ---------------------------------------------------------------------------
# POST /memory — memory_create proposal
# ---------------------------------------------------------------------------


def test_post_memory_creates_proposal_not_memory_entry(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()

    r = api_client.post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "Governance test",
            "content": "No direct write allowed",
            "type": "semantic",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_create"
    assert body["status"] == "pending"

    after = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()
    assert after == before, "POST /memory must not create active MemoryEntry"


def test_post_memory_proposal_has_correct_payload(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    r = api_client.post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "Payload check",
            "content": "content body",
            "type": "preference",
            "scope": "user",
            "namespace": "user.prefs",
            "visibility": "private",
            "sensitivity_level": "normal",
        },
    )
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop is not None
    assert prop.proposal_type == "memory_create"
    payload = prop.payload_json
    assert payload["operation"] == "create"
    assert payload["proposed_content"] == "content body"
    assert payload["target_scope"] == "user"
    assert payload["memory_type"] == "preference"
    entries = payload.get("provenance_entries") or []
    assert any(e.get("source_type") == "user_confirmation" for e in entries)


# ---------------------------------------------------------------------------
# PATCH /memory/{id} — memory_update proposal
# ---------------------------------------------------------------------------


def test_patch_memory_creates_proposal_not_mutation(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="unchanged", scope_type="agent", namespace="ns.c",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
        json={"content": "proposed new content"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_update"
    assert body["status"] == "pending"

    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_now.content == "unchanged", "PATCH /memory must not mutate MemoryEntry"


def test_patch_memory_proposal_contains_target_id(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="x", scope_type="agent", namespace="ns.tid",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
        json={"content": "y"},
    )
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop.payload_json["target_memory_id"] == mem.id
    assert prop.payload_json["operation"] == "update"


# ---------------------------------------------------------------------------
# DELETE /memory/{id} — memory_archive proposal
# ---------------------------------------------------------------------------


def test_delete_memory_creates_archive_proposal_not_deletion(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="survives", scope_type="agent", namespace="ns.del",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.delete(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_archive"
    assert body["status"] == "pending"

    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_now is not None, "DELETE /memory must not hard-delete MemoryEntry"
    assert mem_now.status == "active", "DELETE /memory must not archive MemoryEntry directly"
    assert mem_now.deleted_at is None


def test_delete_memory_proposal_contains_target_id(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="x", scope_type="agent", namespace="ns.arc",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.delete(f"/api/v1/memory/{mem.id}", params=_params(a, ua.id))
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop.payload_json["target_memory_id"] == mem.id
    assert prop.payload_json["operation"] == "archive"
