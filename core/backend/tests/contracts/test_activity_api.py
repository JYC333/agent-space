"""HTTP contract: activity inbox uses get_identity; space-scoped; ingest does not create active memory."""

from __future__ import annotations

from sqlalchemy import func

from app.models import MemoryEntry
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_get_activity_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="web_capture",
        title="A note",
        commit=True,
    )
    r = cross_space_pair["client_b"].get(
        f"/api/v1/activity/{act.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_list_activity_excludes_other_space(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    act_a = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        title="A-only",
        commit=True,
    )
    factories.create_test_activity(
        db,
        space_id=b,
        actor_user_id=ub.id,
        activity_type="user_input",
        title="B-only",
        commit=True,
    )
    r = cross_space_pair["client_a"].get("/api/v1/activity", params=_params(a, ua.id))
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    ids = {x["id"] for x in rows}
    assert act_a.id in ids
    assert all(x.get("space_id") == a for x in rows)


def test_list_activity_for_user_id_must_match_identity(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    r = cross_space_pair["client_a"].get(
        "/api/v1/activity",
        params={**_params(a, ua.id), "for_user_id": ub.id},
    )
    assert r.status_code == 403


def test_post_activity_stable_shape_and_no_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    db.commit()
    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={
            "source_type": "web_capture",
            "content": "capture body",
            "title": "t",
        },
    )
    assert r.status_code == 200
    out = r.json()
    assert set(out.keys()) >= {"id", "space_id", "status", "source_type", "content"}
    assert out["space_id"] == a
    assert out["user_id"] == ua.id
    assert out["status"] == "raw"
    assert out["source_type"] == "web_capture"
    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_post_activity_accepts_canonical_source_types(api_client, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    for source_type in (
        "user_capture",
        "chat_message",
        "external_chat",
        "file_import",
        "web_capture",
        "run_event",
        "workspace_event",
        "system_event",
        "external_source",
    ):
        r = cross_space_pair["client_a"].post(
            "/api/v1/activity",
            params=_params(a, ua.id),
            json={"source_type": source_type, "content": "body", "title": source_type},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source_type"] == source_type


def test_post_activity_maps_legacy_user_input_to_user_capture(api_client, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={"source_type": "user_input", "content": "legacy", "title": "legacy"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["source_type"] == "user_capture"


def test_post_activity_rejects_body_user_id_impersonation(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={
            "source_type": "user_input",
            "content": "x",
            "user_id": ub.id,
        },
    )
    assert r.status_code == 403


def test_post_activity_consolidate_returns_proposals_without_active_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        title="src",
        content="evidence",
        commit=True,
    )
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    r = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    created = r.json()
    assert isinstance(created, list) and len(created) == 1
    p0 = created[0]
    assert set(p0.keys()) >= {"id", "space_id", "status", "proposed_title", "proposed_content"}
    assert p0["status"] == "pending"

    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_patch_process_does_not_create_active_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        title="to-process",
        commit=True,
    )
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    r = cross_space_pair["client_a"].patch(
        f"/api/v1/activity/{act.id}/process",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    assert r.json().get("status") == "processed"
    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_process_activity_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        commit=True,
    )
    r = cross_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/process",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_consolidate_activity_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        commit=True,
    )
    r = cross_space_pair["client_b"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
