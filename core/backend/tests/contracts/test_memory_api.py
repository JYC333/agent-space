"""HTTP contract: memory routes are space-scoped; write routes create proposals."""

from __future__ import annotations

from app.models import MemoryEntry, Proposal
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# Cross-space isolation — unchanged
# ---------------------------------------------------------------------------


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

    r = cross_space_pair["client_b"].get(
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

    r = cross_space_pair["client_b"].patch(
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

    r = cross_space_pair["client_b"].delete(
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

    r = cross_space_pair["client_a"].get("/api/v1/memory", params=_params(a, ua.id))
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"items", "total", "limit", "offset"}
    ids_a = {it["id"] for it in data["items"]}
    assert m_a.id in ids_a
    assert m_b.id not in ids_a
    contents = {it.get("content") or it.get("summary") for it in data["items"]}
    assert "only-b" not in contents


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

    r = cross_space_pair["client_a"].get(f"/api/v1/memory/{mem.id}", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == mem.id
    assert out["space_id"] == a
    assert "content" in out or "summary" in out


# ---------------------------------------------------------------------------
# Write endpoints return proposals (202), not direct MemoryEntry mutations
# ---------------------------------------------------------------------------


def test_post_memory_returns_202_and_proposal(api_client, db, cross_space_pair):
    """POST /memory no longer creates a MemoryEntry — it creates a pending Proposal."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before_mem_count = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).count()

    r = cross_space_pair["client_a"].post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "My preference",
            "content": "I prefer dark mode",
            "type": "preference",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_create"
    assert body["status"] == "pending"

    after_mem_count = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).count()
    assert after_mem_count == before_mem_count, "POST /memory must not create MemoryEntry directly"

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == body["id"]).first()
    assert prop is not None
    assert prop.proposal_type == "memory_create"
    assert prop.status == "pending"


def test_patch_memory_returns_202_and_proposal(api_client, db, cross_space_pair):
    """PATCH /memory/{id} creates a memory_update proposal instead of mutating in place."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="original content",
        scope_type="agent",
        namespace="ns.patch",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()
    original_content = mem.content

    r = cross_space_pair["client_a"].patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
        json={"content": "updated content"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_update"
    assert body["status"] == "pending"

    db.expire_all()
    mem_after = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_after is not None
    assert mem_after.content == original_content, "PATCH /memory must not mutate MemoryEntry directly"
    assert mem_after.status == "active"


def test_delete_memory_returns_202_and_proposal(api_client, db, cross_space_pair):
    """DELETE /memory/{id} creates a memory_archive proposal; MemoryEntry stays active."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="to-archive",
        scope_type="agent",
        namespace="ns.del",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = cross_space_pair["client_a"].delete(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_archive"
    assert body["status"] == "pending"

    db.expire_all()
    mem_after = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_after is not None
    assert mem_after.status == "active", "DELETE /memory must not archive MemoryEntry directly"
    assert mem_after.deleted_at is None
