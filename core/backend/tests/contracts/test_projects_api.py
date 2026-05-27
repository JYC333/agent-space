"""HTTP contract: project endpoints require authentication and are space-scoped."""

from __future__ import annotations

from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# Unauthenticated requests
# ---------------------------------------------------------------------------


def test_list_projects_requires_auth(api_client):
    r = api_client.get("/api/v1/projects", params=_params(PERSONAL_SPACE_ID))
    assert r.status_code == 401


def test_create_project_requires_auth(api_client):
    r = api_client.post(
        "/api/v1/projects",
        params=_params(PERSONAL_SPACE_ID),
        json={"name": "x"},
    )
    assert r.status_code == 401


def test_get_project_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.get(f"/api/v1/projects/{proj.id}", params=_params(a))
    assert r.status_code == 401


def test_patch_project_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.patch(f"/api/v1/projects/{proj.id}", params=_params(a), json={"name": "x"})
    assert r.status_code == 401


def test_archive_project_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.post(f"/api/v1/projects/{proj.id}/archive", params=_params(a))
    assert r.status_code == 401


def test_get_project_summary_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.get(f"/api/v1/projects/{proj.id}/summary", params=_params(a))
    assert r.status_code == 401


def test_list_project_workspaces_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.get(f"/api/v1/projects/{proj.id}/workspaces", params=_params(a))
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# CRUD — authenticated (client_a in space_a)
# ---------------------------------------------------------------------------


def test_create_project_returns_201(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    client_a = cross_space_pair["client_a"]
    r = client_a.post(
        "/api/v1/projects",
        params=_params(a),
        json={"name": "My Project", "description": "desc"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "My Project"
    assert body["status"] == "active"
    assert body["space_id"] == a


def test_list_projects_returns_created_project(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="P-listed", commit=True)
    r = client_a.get("/api/v1/projects", params=_params(a))
    assert r.status_code == 200
    body = r.json()
    names = [p["name"] for p in body["items"]]
    assert "P-listed" in names


def test_get_project_returns_row(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="P-get", commit=True)
    r = client_a.get(f"/api/v1/projects/{proj.id}", params=_params(a))
    assert r.status_code == 200
    assert r.json()["id"] == proj.id


def test_patch_project_updates_name(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="Old", commit=True)
    r = client_a.patch(
        f"/api/v1/projects/{proj.id}",
        params=_params(a),
        json={"name": "New"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_archive_project_sets_status(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="To-archive", commit=True)
    r = client_a.post(f"/api/v1/projects/{proj.id}/archive", params=_params(a))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "archived"
    assert body["archived_at"] is not None


def test_get_project_summary_returns_zero_counts(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="Summary", commit=True)
    r = client_a.get(f"/api/v1/projects/{proj.id}/summary", params=_params(a))
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == proj.id
    assert body["workspace_count"] == 0
    assert body["activity_count"] == 0


def test_create_duplicate_project_name_returns_409(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="Taken", commit=True)
    r = client_a.post("/api/v1/projects", params=_params(a), json={"name": "Taken"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Cross-space isolation
# ---------------------------------------------------------------------------


def test_get_project_cross_space_returns_404(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="A-proj", commit=True)
    r = cross_space_pair["client_b"].get(f"/api/v1/projects/{proj.id}", params=_params(b))
    assert r.status_code == 404


def test_list_projects_cross_space_isolation(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="A-only", commit=True)
    r = cross_space_pair["client_b"].get("/api/v1/projects", params=_params(b))
    assert r.status_code == 200
    names = [p["name"] for p in r.json()["items"]]
    assert "A-only" not in names


def test_patch_project_cross_space_returns_404(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, name="A-patch", commit=True)
    r = cross_space_pair["client_b"].patch(
        f"/api/v1/projects/{proj.id}",
        params=_params(b),
        json={"name": "hacked"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Workspace linking
# ---------------------------------------------------------------------------


def test_link_and_list_workspace(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    r = client_a.post(
        f"/api/v1/projects/{proj.id}/workspaces",
        params=_params(a),
        json={"workspace_id": ws.id, "role": "docs"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["workspace_id"] == ws.id
    assert body["role"] == "docs"

    r2 = client_a.get(f"/api/v1/projects/{proj.id}/workspaces", params=_params(a))
    assert r2.status_code == 200
    wids = [w["workspace_id"] for w in r2.json()]
    assert ws.id in wids


def test_link_cross_space_workspace_returns_404(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    ws_b = factories.create_test_workspace(db, space_id=b, created_by_user_id=ub.id, commit=True)
    r = client_a.post(
        f"/api/v1/projects/{proj.id}/workspaces",
        params=_params(a),
        json={"workspace_id": ws_b.id},
    )
    assert r.status_code == 404


def test_unlink_workspace_returns_204(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    factories.create_test_project_workspace_link(db, project=proj, workspace=ws, commit=True)
    r = client_a.delete(
        f"/api/v1/projects/{proj.id}/workspaces/{ws.id}",
        params=_params(a),
    )
    assert r.status_code == 204


def test_unlink_missing_workspace_link_returns_404(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client_a = cross_space_pair["client_a"]
    proj = factories.create_test_project(db, space_id=a, owner_user_id=ua.id, commit=True)
    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    r = client_a.delete(
        f"/api/v1/projects/{proj.id}/workspaces/{ws.id}",
        params=_params(a),
    )
    assert r.status_code == 404
