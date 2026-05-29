"""HTTP contract: activity inbox uses get_identity; space-scoped; visibility enforced for mutations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from ulid import ULID

from app.models import ActivityRecord, MemoryEntry
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


def test_post_activity_normalizes_user_input_source_type_to_user_capture(api_client, cross_space_pair):
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


def test_patch_review_does_not_create_active_memory(api_client, db, cross_space_pair):
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
        f"/api/v1/activity/{act.id}/review",
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
        f"/api/v1/activity/{act.id}/review",
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


# ---------------------------------------------------------------------------
# occurred_at field
# ---------------------------------------------------------------------------

def test_post_activity_accepts_occurred_at_and_stores_it(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    explicit_time = "2024-03-15T09:00:00Z"
    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={
            "source_type": "file_import",
            "content": "historical import",
            "occurred_at": explicit_time,
        },
    )
    assert r.status_code == 200
    out = r.json()
    assert "occurred_at" in out
    assert out["occurred_at"] is not None
    # Strip TZ info for comparison — SQLite may return naive datetimes.
    from datetime import datetime
    stored_str = out["occurred_at"].replace("Z", "").replace("+00:00", "")
    stored = datetime.fromisoformat(stored_str)
    expected = datetime(2024, 3, 15, 9, 0, 0)
    assert abs((stored - expected).total_seconds()) < 1


def test_post_activity_without_occurred_at_uses_server_time(api_client, db, cross_space_pair):
    from datetime import datetime, UTC
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before = datetime.now(UTC).replace(tzinfo=None)
    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={
            "source_type": "user_capture",
            "content": "no explicit time",
        },
    )
    after = datetime.now(UTC).replace(tzinfo=None)
    assert r.status_code == 200
    out = r.json()
    assert "occurred_at" in out
    assert out["occurred_at"] is not None
    stored_str = out["occurred_at"].replace("Z", "").replace("+00:00", "")
    stored = datetime.fromisoformat(stored_str)
    assert before <= stored <= after


# ---------------------------------------------------------------------------
# Helpers for activity mutation visibility tests
# ---------------------------------------------------------------------------

def _nid() -> str:
    return str(ULID())


def _make_private_activity(db, *, space_id: str, owner_user_id: str) -> ActivityRecord:
    now = datetime.now(UTC)
    record = ActivityRecord(
        id=_nid(),
        space_id=space_id,
        user_id=owner_user_id,
        owner_user_id=owner_user_id,
        visibility="private",
        activity_type="user_capture",
        source_kind="user_capture",
        content="private activity content",
        status="raw",
        occurred_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    return record


# ---------------------------------------------------------------------------
# PATCH /activity/{id}/review — visibility enforcement
# ---------------------------------------------------------------------------

def test_review_private_activity_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/review",
        params={"space_id": space},
    )
    assert r.status_code == 404


def test_review_private_activity_non_owner_db_unchanged(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    same_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/review",
        params={"space_id": space},
    )

    db.expire_all()
    record_after = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).first()
    assert record_after.status == "raw"


def test_process_private_activity_owner_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_a"].patch(
        f"/api/v1/activity/{act.id}/review",
        params={"space_id": space},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "processed"


def test_process_space_shared_activity_any_member_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=space,
        actor_user_id=ua.id,
        activity_type="user_capture",
        commit=True,
    )

    r = same_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/review",
        params={"space_id": space},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /activity/{id}/archive — visibility enforcement
# ---------------------------------------------------------------------------

def test_archive_private_activity_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/archive",
        params={"space_id": space},
    )
    assert r.status_code == 404


def test_archive_private_activity_non_owner_db_unchanged(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    same_space_pair["client_b"].patch(
        f"/api/v1/activity/{act.id}/archive",
        params={"space_id": space},
    )

    db.expire_all()
    record_after = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).first()
    assert record_after.status == "raw"


def test_archive_private_activity_owner_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_a"].patch(
        f"/api/v1/activity/{act.id}/archive",
        params={"space_id": space},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# POST /activity/{id}/consolidate — visibility enforcement
# ---------------------------------------------------------------------------

def test_consolidate_private_activity_non_owner_returns_404(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_b"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params={"space_id": space},
    )
    assert r.status_code == 404


def test_consolidate_private_activity_non_owner_creates_no_proposals(api_client, db, same_space_pair):
    from app.models import Proposal

    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    before = db.query(func.count(Proposal.id)).filter(Proposal.space_id == space).scalar()

    same_space_pair["client_b"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params={"space_id": space},
    )

    db.expire_all()
    after = db.query(func.count(Proposal.id)).filter(Proposal.space_id == space).scalar()
    assert after == before


def test_consolidate_private_activity_owner_succeeds(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    act = _make_private_activity(db, space_id=space, owner_user_id=ua.id)

    r = same_space_pair["client_a"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params={"space_id": space},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
