"""Contract: non-chat capture uses ActivityRecord; chat sessions use Session/Message.

These tests protect the M6 product boundary:
- Non-chat manual capture (user_capture, web_capture, etc.) creates ActivityRecord.
- Chat session creation creates Session + Message, not ActivityRecord.
- Activity create accepts all canonical source types.
- Activity create preserves source_url.
- Activity create does not create active MemoryEntry.
"""

from __future__ import annotations

from sqlalchemy import func

from app.models import ActivityRecord, MemoryEntry, Session, Message
from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# Non-chat capture → ActivityRecord
# ---------------------------------------------------------------------------


def test_user_capture_creates_activity_record(api_client, db, cross_space_pair):
    """POST /activity with user_capture creates ActivityRecord, not Session/Message."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before_sessions = db.query(func.count(Session.id)).filter(Session.space_id == a).scalar()
    before_messages = db.query(func.count(Message.id)).filter(Message.space_id == a).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "user_capture",
            "content": "A quick thought to save",
            "title": "quick thought",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source_type"] == "user_capture"
    assert out["status"] == "raw"
    assert out["space_id"] == a
    assert out["user_id"] == ua.id

    db.expire_all()
    after_sessions = db.query(func.count(Session.id)).filter(Session.space_id == a).scalar()
    after_messages = db.query(func.count(Message.id)).filter(Message.space_id == a).scalar()
    assert after_sessions == before_sessions, "non-chat capture must not create Session rows"
    assert after_messages == before_messages, "non-chat capture must not create Message rows"


def test_web_capture_creates_activity_record_with_source_url(api_client, db, cross_space_pair):
    """web_capture with source_url creates ActivityRecord preserving the URL."""
    a = cross_space_pair["space_a_id"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "web_capture",
            "content": "Page content excerpt",
            "title": "Some page",
            "source_url": "https://example.com/article",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source_type"] == "web_capture"
    assert out["source_url"] == "https://example.com/article"
    assert out["status"] == "raw"

    db.expire_all()
    rec = db.query(ActivityRecord).filter(ActivityRecord.id == out["id"]).one()
    assert rec.source_url == "https://example.com/article"


def test_non_chat_capture_does_not_create_active_memory(api_client, db, cross_space_pair):
    """Non-chat capture via activity API creates only ActivityRecord; no active MemoryEntry."""
    a = cross_space_pair["space_a_id"]

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "user_capture",
            "content": "thought that must not become memory directly",
            "title": "raw thought",
        },
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before, "activity create must not create active memory"


def test_all_canonical_nonchat_source_types_accepted(api_client, cross_space_pair):
    """All non-chat canonical source_type values are accepted by the activity API."""
    a = cross_space_pair["space_a_id"]

    non_chat_types = [
        "user_capture",
        "web_capture",
        "file_import",
        "external_source",
        "external_chat",
    ]
    for st in non_chat_types:
        r = cross_space_pair["client_a"].post(
            "/api/v1/activity",
            params=_params(a),
            json={"source_type": st, "content": "body", "title": st},
        )
        assert r.status_code == 200, f"source_type {st!r} rejected: {r.text}"
        assert r.json()["source_type"] == st


# ---------------------------------------------------------------------------
# Chat session path → Session + Message (not ActivityRecord)
# ---------------------------------------------------------------------------


def test_chat_session_create_still_creates_session_and_message(api_client, db, cross_space_pair):
    """POST /sessions + /sessions/{id}/messages creates Session and Message rows."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before_activities = (
        db.query(func.count(ActivityRecord.id))
        .filter(
            ActivityRecord.space_id == a,
            ActivityRecord.activity_type == "user_capture",
        )
        .scalar()
    )

    rs = cross_space_pair["client_a"].post(
        "/api/v1/sessions",
        params=_params(a),
        json={"title": "A real conversation", "space_id": a, "user_id": ua.id},
    )
    assert rs.status_code == 201, rs.text
    session_id = rs.json()["id"]

    rm = cross_space_pair["client_a"].post(
        f"/api/v1/sessions/{session_id}/messages",
        params=_params(a),
        json={"role": "user", "content": "Hello, agent."},
    )
    assert rm.status_code == 201, rm.text

    db.expire_all()
    sess = db.query(Session).filter(Session.id == session_id).first()
    assert sess is not None
    msgs = db.query(Message).filter(Message.session_id == session_id).all()
    assert len(msgs) == 1
    assert msgs[0].content == "Hello, agent."

    after_activities = (
        db.query(func.count(ActivityRecord.id))
        .filter(
            ActivityRecord.space_id == a,
            ActivityRecord.activity_type == "user_capture",
        )
        .scalar()
    )
    assert after_activities == before_activities, (
        "chat session create must not create user_capture ActivityRecord"
    )
