"""HTTP contract: session get/messages require auth; space + user scoped.

Covers:
- GET /sessions/{id}   returns 401 without auth
- GET /sessions/{id}/messages returns 401 without auth
- cross-space user cannot read another space's session (404)
- cross-space user cannot read another space's messages (404)
- same-space non-owner cannot read another user's session (404)
- same-space non-owner cannot read another user's messages (404)
- owner can read their own session (200)
- owner can read their own session messages (200)
- unauthorized message request returns no content
"""

from __future__ import annotations
import uuid

from app.models import Message, Session as SessionModel
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _make_session(db, *, space_id: str, user_id: str, title: str = "test") -> SessionModel:
    session = SessionModel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        user_id=user_id,
        title=title,
        status="active",
    )
    db.add(session)
    db.commit()
    return session


def _make_message(db, *, session_id: str, space_id: str, user_id: str, content: str = "hello") -> Message:
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        role="user",
        content=content,
    )
    db.add(msg)
    db.commit()
    return msg


# ---------------------------------------------------------------------------
# Unauthenticated → 401
# ---------------------------------------------------------------------------

def test_get_session_requires_auth(api_client, db, cross_space_pair_db):
    space = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)

    r = api_client.get(f"/api/v1/sessions/{session.id}", params={"space_id": space})
    assert r.status_code == 401


def test_get_session_messages_requires_auth(api_client, db, cross_space_pair_db):
    space = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)
    _make_message(db, session_id=session.id, space_id=space, user_id=ua.id)

    r = api_client.get(f"/api/v1/sessions/{session.id}/messages", params={"space_id": space})
    assert r.status_code == 401


def test_add_session_message_requires_auth(api_client, db, cross_space_pair_db):
    space = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)

    r = api_client.post(
        f"/api/v1/sessions/{session.id}/messages",
        json={"role": "user", "content": "hello"},
        params={"space_id": space},
    )

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cross-space → 404 (session exists in space A, accessed by space B user)
# ---------------------------------------------------------------------------

def test_cross_space_cannot_get_session(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    session = _make_session(db, space_id=a, user_id=ua.id)

    r = cross_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}",
        params={"space_id": b},
    )
    assert r.status_code == 404


def test_cross_space_cannot_get_session_messages(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    session = _make_session(db, space_id=a, user_id=ua.id)
    _make_message(db, session_id=session.id, space_id=a, user_id=ua.id, content="secret")

    r = cross_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": b},
    )
    assert r.status_code == 404


def test_cross_space_messages_response_contains_no_content(api_client, db, cross_space_pair):
    """A 404 response body must not include any message content."""
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    session = _make_session(db, space_id=a, user_id=ua.id)
    _make_message(db, session_id=session.id, space_id=a, user_id=ua.id, content="top-secret")

    r = cross_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": b},
    )
    assert r.status_code == 404
    assert "top-secret" not in r.text


def test_cross_space_cannot_add_session_message(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    session = _make_session(db, space_id=a, user_id=ua.id)

    r = cross_space_pair["client_b"].post(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": b},
        json={"role": "user", "content": "cross-space-write"},
    )

    assert r.status_code == 404
    assert "cross-space-write" not in r.text
    assert db.query(Message).filter(Message.session_id == session.id).count() == 0


def test_cross_space_cannot_reflect_session(api_client, db, cross_space_pair, monkeypatch):
    calls: list[dict] = []

    class FakeReflector:
        def __init__(self, db):
            self.db = db

        def reflect(self, **kwargs):
            calls.append(kwargs)
            return []

    monkeypatch.setattr("app.sessions.api.MemoryReflector", FakeReflector)
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    session = _make_session(db, space_id=a, user_id=ua.id)

    r = cross_space_pair["client_b"].post(
        f"/api/v1/sessions/{session.id}/reflect",
        params={"space_id": b},
    )

    assert r.status_code == 404
    assert calls == []


# ---------------------------------------------------------------------------
# Same-space non-owner → 404
# ---------------------------------------------------------------------------

def test_same_space_non_owner_cannot_get_session(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id, title="private-session")

    r = same_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}",
        params={"space_id": space},
    )
    assert r.status_code == 404


def test_same_space_non_owner_cannot_get_messages(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)
    _make_message(db, session_id=session.id, space_id=space, user_id=ua.id, content="private-msg")

    r = same_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": space},
    )
    assert r.status_code == 404


def test_same_space_non_owner_messages_contains_no_content(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)
    _make_message(db, session_id=session.id, space_id=space, user_id=ua.id, content="sensitive-payload")

    r = same_space_pair["client_b"].get(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": space},
    )
    assert r.status_code == 404
    assert "sensitive-payload" not in r.text


def test_same_space_non_owner_cannot_add_session_message(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)

    r = same_space_pair["client_b"].post(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": space},
        json={"role": "user", "content": "non-owner-write"},
    )

    assert r.status_code == 404
    assert "non-owner-write" not in r.text
    assert db.query(Message).filter(Message.session_id == session.id).count() == 0


def test_same_space_non_owner_cannot_reflect_session(api_client, db, same_space_pair, monkeypatch):
    calls: list[dict] = []

    class FakeReflector:
        def __init__(self, db):
            self.db = db

        def reflect(self, **kwargs):
            calls.append(kwargs)
            return []

    monkeypatch.setattr("app.sessions.api.MemoryReflector", FakeReflector)
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)

    r = same_space_pair["client_b"].post(
        f"/api/v1/sessions/{session.id}/reflect",
        params={"space_id": space},
    )

    assert r.status_code == 404
    assert calls == []


# ---------------------------------------------------------------------------
# Owner → 200
# ---------------------------------------------------------------------------

def test_owner_can_get_their_session(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id, title="my-session")

    r = same_space_pair["client_a"].get(
        f"/api/v1/sessions/{session.id}",
        params={"space_id": space},
    )
    assert r.status_code == 200
    assert r.json()["id"] == session.id


def test_owner_can_get_their_session_messages(api_client, db, same_space_pair):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    session = _make_session(db, space_id=space, user_id=ua.id)
    msg = _make_message(db, session_id=session.id, space_id=space, user_id=ua.id, content="owner-msg")

    r = same_space_pair["client_a"].get(
        f"/api/v1/sessions/{session.id}/messages",
        params={"space_id": space},
    )
    assert r.status_code == 200
    contents = [m["content"] for m in r.json()]
    assert "owner-msg" in contents
