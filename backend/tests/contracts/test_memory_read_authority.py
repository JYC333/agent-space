"""Stage 6 slices 5-6: Python public memory routes fail closed under TS authority.

When ``CONTROL_PLANE_MEMORY_AUTHORITY=ts`` the TS control plane owns the memory
read routes plus public memory proposal creation. Python returns 410 for moved
routes so the fallback proxy cannot keep a second authority alive.
"""

from __future__ import annotations

from tests.support import factories


def test_memory_read_routes_fail_closed_under_ts_authority(
    api_client, db, monkeypatch, cross_space_pair
):
    monkeypatch.setenv("CONTROL_PLANE_MEMORY_AUTHORITY", "ts")
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="hidden under ts",
        scope_type="agent",
        namespace="ns.authority",
        owner_user_id=ua.id,
        commit=True,
    )
    params = {"space_id": a}

    assert client.get("/api/v1/memory", params=params).status_code == 410
    assert client.get(f"/api/v1/memory/{mem.id}", params=params).status_code == 410
    search = client.post(
        "/api/v1/memory/search", params=params, json={"query": "hidden"}
    )
    assert search.status_code == 410
    # The hidden content never leaks through the closed read path.
    assert "hidden under ts" not in search.text


def test_memory_proposal_create_routes_fail_closed_under_ts_authority(
    api_client, db, monkeypatch, cross_space_pair
):
    monkeypatch.setenv("CONTROL_PLANE_MEMORY_AUTHORITY", "ts")
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="proposal target",
        scope_type="agent",
        namespace="ns.write-authority",
        owner_user_id=ua.id,
        commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    create = client.post(
        "/api/v1/memory",
        params={"space_id": a},
        json={"title": "t", "content": "c", "type": "fact"},
    )
    patch = client.patch(
        f"/api/v1/memory/{mem.id}",
        params={"space_id": a},
        json={"content": "proposed"},
    )
    delete = client.delete(f"/api/v1/memory/{mem.id}", params={"space_id": a})

    assert create.status_code == 410
    assert patch.status_code == 410
    assert delete.status_code == 410
