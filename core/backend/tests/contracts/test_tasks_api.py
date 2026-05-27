"""HTTP contract: task mutation and sub-resource endpoints enforce authentication and visibility.

Covers:
- PATCH /tasks/{task_id} requires authentication
- Cross-space PATCH returns 404 and does not mutate DB state
- Owner can PATCH their own private task
- Same-space non-owner cannot PATCH another user's private task (→ 404, no mutation)
- Same-space non-owner cannot PATCH a restricted task (→ 404, no mutation)
- Any space member can PATCH a space_shared task
- Non-owner cannot POST /tasks/{task_id}/runs for a private task
- Non-owner cannot GET sub-resources (runs/artifacts/proposals) of a private/restricted task
- Owner can GET sub-resources of their own private task
- space_shared task sub-resources are visible to all space members
"""

from __future__ import annotations

from ulid import ULID

from app.models import Task
from tests.support import factories


def _nid() -> str:
    return str(ULID())


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _make_task(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    title: str = "Test task",
    visibility: str = "space_shared",
) -> Task:
    task = Task(
        id=_nid(),
        space_id=space_id,
        title=title,
        status="inbox",
        priority="normal",
        visibility=visibility,
        created_by_user_id=owner_user_id,
    )
    db.add(task)
    db.commit()
    return task


# ---------------------------------------------------------------------------
# Authentication required
# ---------------------------------------------------------------------------

def test_patch_task_requires_auth(api_client, db, cross_space_pair_db):
    space = cross_space_pair_db["space_a_id"]
    owner = cross_space_pair_db["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=owner.id)
    r = api_client.patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "hacked"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cross-space: authenticated user from another space cannot mutate
# ---------------------------------------------------------------------------

def test_patch_task_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    task = _make_task(db, space_id=a, owner_user_id=ua.id, title="original")

    r = cross_space_pair["client_b"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(b),
        json={"title": "hacked"},
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"

    # DB state must be unchanged
    db.expire_all()
    task_after = db.query(Task).filter(Task.id == task.id).first()
    assert task_after.title == "original"


# ---------------------------------------------------------------------------
# Private task — intra-space visibility
# ---------------------------------------------------------------------------

def test_patch_own_private_task_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private", title="mine")

    r = same_space_pair["client_a"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "updated by owner"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "updated by owner"


def test_patch_private_task_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private", title="private")

    task = db.query(Task).filter(Task.created_by_user_id == ua.id, Task.space_id == space).first()

    r = same_space_pair["client_b"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "hacked"},
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


def test_patch_private_task_non_owner_db_unchanged(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private", title="original private")

    same_space_pair["client_b"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "hacked"},
    )

    db.expire_all()
    task_after = db.query(Task).filter(Task.id == task.id).first()
    assert task_after.title == "original private"


# ---------------------------------------------------------------------------
# Restricted task — intra-space visibility
# ---------------------------------------------------------------------------

def test_patch_restricted_task_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="restricted", title="restricted")

    r = same_space_pair["client_b"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "hacked"},
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"

    db.expire_all()
    task_after = db.query(Task).filter(Task.id == task.id).first()
    assert task_after.title == "restricted"


# ---------------------------------------------------------------------------
# space_shared task — any member can mutate (preserved behavior)
# ---------------------------------------------------------------------------

def test_patch_space_shared_task_by_non_owner_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="space_shared", title="shared")

    r = same_space_pair["client_b"].patch(
        f"/api/v1/tasks/{task.id}",
        params=_params(space),
        json={"title": "updated by member"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "updated by member"


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/runs — non-owner cannot start a run on a private task
# ---------------------------------------------------------------------------

def test_create_run_for_private_task_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")
    agent = factories.create_test_agent(db, space_id=space, owner_user_id=ua.id, commit=True)

    r = same_space_pair["client_b"].post(
        f"/api/v1/tasks/{task.id}/runs",
        params=_params(space),
        json={
            "agent_id": agent.id,
            "mode": "live",
            "run_type": "agent",
            "trigger_origin": "manual",
        },
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/runs — sub-resource visibility
# ---------------------------------------------------------------------------

def test_list_task_runs_private_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/runs",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_runs_restricted_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="restricted")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/runs",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_runs_owner_can_access_private_task(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_a"].get(
        f"/api/v1/tasks/{task.id}/runs",
        params=_params(space),
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_list_task_runs_space_shared_visible_to_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="space_shared")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/runs",
        params=_params(space),
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/artifacts — sub-resource visibility
# ---------------------------------------------------------------------------

def test_list_task_artifacts_private_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/artifacts",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_artifacts_restricted_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="restricted")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/artifacts",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_artifacts_owner_can_access_private_task(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_a"].get(
        f"/api/v1/tasks/{task.id}/artifacts",
        params=_params(space),
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_list_task_artifacts_space_shared_visible_to_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="space_shared")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/artifacts",
        params=_params(space),
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/proposals — sub-resource visibility
# ---------------------------------------------------------------------------

def test_list_task_proposals_private_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/proposals",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_proposals_restricted_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="restricted")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/proposals",
        params=_params(space),
    )
    assert r.status_code == 404


def test_list_task_proposals_owner_can_access_private_task(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_a"].get(
        f"/api/v1/tasks/{task.id}/proposals",
        params=_params(space),
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_list_task_proposals_space_shared_visible_to_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    task = _make_task(db, space_id=space, owner_user_id=ua.id, visibility="space_shared")

    r = same_space_pair["client_b"].get(
        f"/api/v1/tasks/{task.id}/proposals",
        params=_params(space),
    )
    assert r.status_code == 200
