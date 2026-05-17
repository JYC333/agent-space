"""HTTP contract: /api/v1/me/* cross-space personal aggregation endpoints.

Tests verify:
  - /me/summary aggregates across all spaces where user is a member
  - /me/timeline returns participation records (pointer only, no raw content)
  - /me/tasks returns tasks assigned/created/claimed by user across spaces
  - /me/pending returns pending proposals across member spaces
  - Objects from non-member spaces are excluded
  - Private objects owned by another user are excluded
  - Private objects owned by current user are included
  - Response bodies are minimal (no raw content/payload fields)
"""

from __future__ import annotations

from ulid import ULID

import pytest
from app.auth.session import SESSION_COOKIE, UserSessionService
from app.main import app as _app
from app.models import ParticipationRecord, Proposal, Task
from starlette.testclient import TestClient
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _authed_client(db, user_id: str) -> TestClient:
    _, raw = UserSessionService(db).create(user_id)
    db.commit()
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /me/summary
# ---------------------------------------------------------------------------


def test_me_summary_empty_when_no_activity(api_client, db):
    """Empty summary for a user with no content in any space."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Empty Me", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    c = _authed_client(db, user.id)

    r = c.get("/api/v1/me/summary", params={"space_id": space_id})
    assert r.status_code == 200
    data = r.json()
    assert data["pending_proposals_count"] == 0
    assert data["assigned_tasks_count"] == 0
    assert data["recent_runs"] == []
    assert data["recent_participation"] == []
    assert data["accessible_spaces_count"] >= 1


def test_me_summary_aggregates_across_member_spaces(api_client, db):
    """Summary counts aggregate pending proposals and tasks across all member spaces."""
    space_a = _new_id()
    space_b = _new_id()
    factories.create_test_space(db, space_id=space_a, name="Space A", space_type="team", commit=False)
    factories.create_test_space(db, space_id=space_b, name="Space B", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=space_a, commit=False)

    from app.models import SpaceMembership
    db.add(SpaceMembership(id=_new_id(), space_id=space_b, user_id=user.id, role="member", status="active"))
    db.flush()

    # Add pending proposals in both spaces
    factories.create_test_proposal(db, space_id=space_a, created_by_user_id=user.id, status="pending", commit=False)
    factories.create_test_proposal(db, space_id=space_b, created_by_user_id=user.id, status="pending", commit=False)

    # Add a task assigned to the user in space_a
    task = Task(
        id=_new_id(),
        space_id=space_a,
        title="Test task",
        status="inbox",
        priority="normal",
        assigned_user_id=user.id,
        created_by_user_id=user.id,
    )
    db.add(task)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/summary", params={"space_id": space_a})
    assert r.status_code == 200
    data = r.json()
    assert data["pending_proposals_count"] >= 2
    assert data["assigned_tasks_count"] >= 1
    assert data["accessible_spaces_count"] >= 2


def test_me_summary_excludes_non_member_space_data(api_client, db):
    """Summary never includes data from spaces where user is not a member."""
    space_a = _new_id()
    space_other = _new_id()
    factories.create_test_space(db, space_id=space_a, name="My Space", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=space_other, name="Other Space", space_type="team", commit=False)
    user_a = factories.create_test_user(db, space_id=space_a, commit=False)
    user_other = factories.create_test_user(db, space_id=space_other, commit=False)

    factories.create_test_proposal(db, space_id=space_other, created_by_user_id=user_other.id, status="pending", commit=True)

    c = _authed_client(db, user_a.id)
    r = c.get("/api/v1/me/summary", params={"space_id": space_a})
    assert r.status_code == 200
    data = r.json()
    assert data["pending_proposals_count"] == 0


# ---------------------------------------------------------------------------
# /me/timeline
# ---------------------------------------------------------------------------


def test_me_timeline_returns_participation_records_only(api_client, db):
    """Timeline returns participation records without raw content fields."""
    space_id = _new_id()
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=space_id, name="Team", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=personal_id, commit=False)

    from app.models import SpaceMembership
    db.add(SpaceMembership(id=_new_id(), space_id=space_id, user_id=user.id, role="member", status="active"))
    db.flush()

    from datetime import UTC, datetime
    rec = ParticipationRecord(
        id=_new_id(),
        user_id=user.id,
        personal_space_id=personal_id,
        source_space_id=space_id,
        source_object_type="activity",
        source_object_id=_new_id(),
        role="created",
        occurred_at=datetime.now(UTC),
    )
    db.add(rec)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/timeline", params={"space_id": personal_id})
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    item = next((i for i in items if i["id"] == rec.id), None)
    assert item is not None
    assert item["entry_type"] == "participation"
    assert item["source_object_type"] == "activity"
    assert item["role"] == "created"
    # No raw content fields
    assert "content" not in item
    assert "payload" not in item


def test_me_timeline_only_returns_own_records(api_client, db):
    """Timeline only returns records for the authenticated user, not others'."""
    personal_a = _new_id()
    personal_b = _new_id()
    shared = _new_id()
    factories.create_test_space(db, space_id=personal_a, name="Personal A", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=personal_b, name="Personal B", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=shared, name="Shared", space_type="team", commit=False)
    user_a = factories.create_test_user(db, space_id=personal_a, commit=False)
    user_b = factories.create_test_user(db, space_id=personal_b, commit=False)

    from datetime import UTC, datetime
    rec_b = ParticipationRecord(
        id=_new_id(),
        user_id=user_b.id,
        personal_space_id=personal_b,
        source_space_id=shared,
        source_object_type="run",
        source_object_id=_new_id(),
        role="instructed",
        occurred_at=datetime.now(UTC),
    )
    db.add(rec_b)
    db.commit()

    c = _authed_client(db, user_a.id)
    r = c.get("/api/v1/me/timeline", params={"space_id": personal_a})
    assert r.status_code == 200
    items = r.json()
    ids = [i["id"] for i in items]
    assert rec_b.id not in ids


# ---------------------------------------------------------------------------
# /me/tasks
# ---------------------------------------------------------------------------


def test_me_tasks_returns_user_tasks_across_spaces(api_client, db):
    """Tasks assigned to or created by user in any member space are included."""
    space_a = _new_id()
    space_b = _new_id()
    factories.create_test_space(db, space_id=space_a, name="A", space_type="team", commit=False)
    factories.create_test_space(db, space_id=space_b, name="B", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=space_a, commit=False)

    from app.models import SpaceMembership
    db.add(SpaceMembership(id=_new_id(), space_id=space_b, user_id=user.id, role="member", status="active"))
    db.flush()

    task_a = Task(
        id=_new_id(), space_id=space_a, title="Task A", status="inbox",
        priority="normal", assigned_user_id=user.id
    )
    task_b = Task(
        id=_new_id(), space_id=space_b, title="Task B", status="inbox",
        priority="normal", created_by_user_id=user.id
    )
    db.add(task_a)
    db.add(task_b)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/tasks", params={"space_id": space_a})
    assert r.status_code == 200
    task_ids = {t["id"] for t in r.json()}
    assert task_a.id in task_ids
    assert task_b.id in task_ids


def test_me_tasks_excludes_other_user_private_tasks(api_client, db):
    """Private task owned by another user is not returned."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Shared", space_type="team", commit=False)
    user_me = factories.create_test_user(db, space_id=space_id, commit=False)
    user_other = factories.create_test_user(db, space_id=space_id, commit=False)

    private_task = Task(
        id=_new_id(), space_id=space_id, title="Private task", status="inbox",
        priority="normal", visibility="private",
        created_by_user_id=user_other.id, assigned_user_id=user_me.id
    )
    db.add(private_task)
    db.commit()

    c = _authed_client(db, user_me.id)
    r = c.get("/api/v1/me/tasks", params={"space_id": space_id})
    assert r.status_code == 200
    # The task is assigned to user_me but private-owned by user_other
    # visibility=private + owner=user_other → blocked for user_me
    task_ids = {t["id"] for t in r.json()}
    assert private_task.id not in task_ids


def test_me_tasks_includes_own_private_tasks(api_client, db):
    """Private task created by and assigned to the user themselves is included."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)

    my_private_task = Task(
        id=_new_id(), space_id=space_id, title="My private task", status="inbox",
        priority="normal", visibility="private",
        created_by_user_id=user.id, assigned_user_id=user.id
    )
    db.add(my_private_task)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/tasks", params={"space_id": space_id})
    assert r.status_code == 200
    task_ids = {t["id"] for t in r.json()}
    assert my_private_task.id in task_ids


def test_me_tasks_excludes_non_member_space_tasks(api_client, db):
    """Tasks from spaces where user is not a member are excluded."""
    space_mine = _new_id()
    space_other = _new_id()
    factories.create_test_space(db, space_id=space_mine, name="Mine", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=space_other, name="Other", space_type="team", commit=False)
    user_me = factories.create_test_user(db, space_id=space_mine, commit=False)
    user_other = factories.create_test_user(db, space_id=space_other, commit=False)

    foreign_task = Task(
        id=_new_id(), space_id=space_other, title="Not mine", status="inbox",
        priority="normal", assigned_user_id=user_me.id
    )
    db.add(foreign_task)
    db.commit()

    c = _authed_client(db, user_me.id)
    r = c.get("/api/v1/me/tasks", params={"space_id": space_mine})
    assert r.status_code == 200
    task_ids = {t["id"] for t in r.json()}
    assert foreign_task.id not in task_ids


def test_me_tasks_response_has_minimal_shape(api_client, db):
    """Task response omits raw description and other sensitive payload fields."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="T", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    task = Task(
        id=_new_id(), space_id=space_id, title="Minimal check", status="inbox",
        priority="normal", created_by_user_id=user.id
    )
    db.add(task)
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/tasks", params={"space_id": space_id})
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    item = next(i for i in items if i["id"] == task.id)
    # Required minimal fields
    for key in ("id", "space_id", "title", "status", "priority", "visibility", "created_at", "updated_at"):
        assert key in item, f"missing key: {key}"
    # Should NOT expose acceptance_criteria or full task payload
    assert "acceptance_criteria_json" not in item
    assert "policy_json" not in item


# ---------------------------------------------------------------------------
# /me/pending
# ---------------------------------------------------------------------------


def test_me_pending_returns_proposals_across_member_spaces(api_client, db):
    """Pending proposals in all member spaces are included."""
    space_a = _new_id()
    space_b = _new_id()
    factories.create_test_space(db, space_id=space_a, name="A", space_type="team", commit=False)
    factories.create_test_space(db, space_id=space_b, name="B", space_type="team", commit=False)
    user = factories.create_test_user(db, space_id=space_a, commit=False)

    from app.models import SpaceMembership
    db.add(SpaceMembership(id=_new_id(), space_id=space_b, user_id=user.id, role="member", status="active"))
    db.flush()

    prop_a = factories.create_test_proposal(
        db, space_id=space_a, created_by_user_id=user.id, status="pending", commit=False
    )
    prop_b = factories.create_test_proposal(
        db, space_id=space_b, created_by_user_id=user.id, status="pending", commit=False
    )
    db.commit()

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/pending", params={"space_id": space_a})
    assert r.status_code == 200
    prop_ids = {p["id"] for p in r.json()}
    assert prop_a.id in prop_ids
    assert prop_b.id in prop_ids


def test_me_pending_excludes_private_proposals_of_other_user(api_client, db):
    """Private proposals owned by another user are not included."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Team", space_type="team", commit=False)
    user_me = factories.create_test_user(db, space_id=space_id, commit=False)
    user_other = factories.create_test_user(db, space_id=space_id, commit=False)

    private_prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=user_other.id, status="pending", commit=False
    )
    private_prop.visibility = "private"
    db.flush()
    db.commit()

    c = _authed_client(db, user_me.id)
    r = c.get("/api/v1/me/pending", params={"space_id": space_id})
    assert r.status_code == 200
    prop_ids = {p["id"] for p in r.json()}
    assert private_prop.id not in prop_ids


def test_me_pending_response_has_minimal_shape(api_client, db):
    """Pending proposal response omits full payload content."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="P", space_type="personal", commit=False)
    user = factories.create_test_user(db, space_id=space_id, commit=False)
    prop = factories.create_test_proposal(
        db, space_id=space_id, created_by_user_id=user.id, status="pending", commit=True
    )

    c = _authed_client(db, user.id)
    r = c.get("/api/v1/me/pending", params={"space_id": space_id})
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    item = next(i for i in items if i["id"] == prop.id)
    for key in ("id", "space_id", "proposal_type", "status", "urgency", "title", "visibility", "created_at"):
        assert key in item, f"missing key: {key}"
    # Full payload must not be exposed
    assert "payload_json" not in item
    assert "payload" not in item


def test_me_pending_excludes_non_member_space_proposals(api_client, db):
    """Proposals from spaces where user is not a member are excluded."""
    space_mine = _new_id()
    space_other = _new_id()
    factories.create_test_space(db, space_id=space_mine, name="Mine", space_type="personal", commit=False)
    factories.create_test_space(db, space_id=space_other, name="Other", space_type="team", commit=False)
    user_me = factories.create_test_user(db, space_id=space_mine, commit=False)
    user_other = factories.create_test_user(db, space_id=space_other, commit=False)

    foreign_prop = factories.create_test_proposal(
        db, space_id=space_other, created_by_user_id=user_other.id, status="pending", commit=True
    )

    c = _authed_client(db, user_me.id)
    r = c.get("/api/v1/me/pending", params={"space_id": space_mine})
    assert r.status_code == 200
    prop_ids = {p["id"] for p in r.json()}
    assert foreign_prop.id not in prop_ids
