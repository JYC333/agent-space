"""HTTP contract: board task list enforces task visibility.

Covers:
- GET /boards/{board_id}/tasks hides private tasks from same-space non-owners
- GET /boards/{board_id}/tasks hides restricted tasks from same-space non-owners
- GET /boards/{board_id}/tasks includes space_shared tasks for any space member
- GET /boards/{board_id}/tasks includes private tasks for their owner
- total reflects the filtered result set, not the unfiltered board count
"""

from __future__ import annotations

from ulid import ULID

from app.models import Board, Task


def _nid() -> str:
    return str(ULID())


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _make_board(db, *, space_id: str, user_id: str) -> Board:
    board = Board(
        id=_nid(),
        space_id=space_id,
        name="Test Board",
        board_type="kanban",
        status="active",
        created_by_user_id=user_id,
    )
    db.add(board)
    db.commit()
    return board


def _make_task(
    db,
    *,
    space_id: str,
    board_id: str,
    owner_user_id: str,
    title: str = "Task",
    visibility: str = "space_shared",
) -> Task:
    task = Task(
        id=_nid(),
        space_id=space_id,
        board_id=board_id,
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
# Private task hidden from non-owner
# ---------------------------------------------------------------------------

def test_board_tasks_hides_private_task_from_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    board = _make_board(db, space_id=space, user_id=ua.id)
    private_task = _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_b"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["items"]]
    assert private_task.id not in ids


# ---------------------------------------------------------------------------
# Restricted task hidden from non-owner
# ---------------------------------------------------------------------------

def test_board_tasks_hides_restricted_task_from_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    board = _make_board(db, space_id=space, user_id=ua.id)
    restricted_task = _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="restricted")

    r = same_space_pair["client_b"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["items"]]
    assert restricted_task.id not in ids


# ---------------------------------------------------------------------------
# space_shared task visible to all space members
# ---------------------------------------------------------------------------

def test_board_tasks_shows_space_shared_task_to_non_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    board = _make_board(db, space_id=space, user_id=ua.id)
    shared_task = _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="space_shared")

    r = same_space_pair["client_b"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["items"]]
    assert shared_task.id in ids


# ---------------------------------------------------------------------------
# Owner can see their own private task on the board
# ---------------------------------------------------------------------------

def test_board_tasks_shows_private_task_to_owner(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    board = _make_board(db, space_id=space, user_id=ua.id)
    private_task = _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="private")

    r = same_space_pair["client_a"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["items"]]
    assert private_task.id in ids


# ---------------------------------------------------------------------------
# total reflects the filtered count for the requesting user
# ---------------------------------------------------------------------------

def test_board_tasks_total_reflects_filtered_count(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    board = _make_board(db, space_id=space, user_id=ua.id)
    _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="space_shared", title="Shared")
    _make_task(db, space_id=space, board_id=board.id, owner_user_id=ua.id, visibility="private", title="Private")

    # client_b (non-owner) sees only the shared task
    r = same_space_pair["client_b"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1

    # client_a (owner) sees both tasks
    r_owner = same_space_pair["client_a"].get(
        f"/api/v1/boards/{board.id}/tasks",
        params=_params(space),
    )
    assert r_owner.status_code == 200
    assert r_owner.json()["total"] == 2
