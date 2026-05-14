"""HTTP contract: memory routes are space-scoped; no cross-tenant reads or mutations."""

from __future__ import annotations

from app.models import MemoryEntry
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_get_memory_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="SECRET_A_CONTENT",
        scope_type="agent",
        namespace="ns.contract",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.get(
        f"/api/v1/memory/{mem.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    body = r.json()
    assert body.get("error") == "not_found"
    assert "SECRET_A_CONTENT" not in r.text


def test_patch_memory_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="orig",
        scope_type="agent",
        namespace="ns.contract",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(b, ub.id),
        json={"title": "hijack"},
    )
    assert r.status_code == 404


def test_delete_memory_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="keep",
        scope_type="agent",
        namespace="ns.contract",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.delete(
        f"/api/v1/memory/{mem.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    db.expire_all()
    row = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert row is not None and row.deleted_at is None


def test_list_memory_only_current_space(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    m_a = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="only-a",
        scope_type="agent",
        namespace="ns.a",
        owner_user_id=ua.id,
        commit=False,
    )
    m_b = factories.create_test_memory_entry(
        db,
        space_id=b,
        content="only-b",
        scope_type="agent",
        namespace="ns.b",
        owner_user_id=ub.id,
        commit=False,
    )
    m_b.visibility = "space_shared"
    m_a.visibility = "space_shared"
    db.commit()

    r = api_client.get("/api/v1/memory", params=_params(a, ua.id))
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"items", "total", "limit", "offset"}
    ids_a = {it["id"] for it in data["items"]}
    assert m_a.id in ids_a
    assert m_b.id not in ids_a
    contents = {it.get("content") or it.get("summary") for it in data["items"]}
    assert "only-b" not in contents


def test_deleted_memory_not_listed_active(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="to-delete",
        scope_type="agent",
        namespace="ns.del",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    del_r = api_client.delete(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
    )
    assert del_r.status_code == 204

    r = api_client.get("/api/v1/memory", params={**_params(a, ua.id), "status": "active"})
    assert r.status_code == 200
    ids = {it["id"] for it in r.json()["items"]}
    assert mem.id not in ids


def test_memory_get_success_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="hello",
        scope_type="agent",
        namespace="ns.get",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = api_client.get(f"/api/v1/memory/{mem.id}", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == mem.id
    assert out["space_id"] == a
    assert "content" in out or "summary" in out
