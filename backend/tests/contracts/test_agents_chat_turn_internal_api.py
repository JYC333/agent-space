from __future__ import annotations

import uuid

from app.config import settings
from app.models import (
    ContextSnapshot,
    ContextSnapshotItem,
    Message,
    Run,
    Session as SessionModel,
)
from tests.support import factories


HEADER = {"x-agent-space-internal-token": "internal-token"}


def _make_session(db, *, space_id: str, user_id: str) -> SessionModel:
    session = SessionModel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        user_id=user_id,
        title="chat-turn-prep-test",
        status="active",
    )
    db.add(session)
    db.flush()
    return session


def _make_message(db, *, session_id: str, space_id: str, user_id: str) -> Message:
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        role="user",
        content="Plan the TS chat turn migration.",
    )
    db.add(message)
    db.flush()
    return message


def test_chat_turn_prepare_run_requires_service_token(api_client, monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.post(
        "/api/v1/internal/agents-chat/prepare-run",
        json={
            "agent_id": "agent-1",
            "space_id": "space-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "message": "hello",
        },
    )

    assert response.status_code == 401
    assert response.json().get("error") == "unauthorized"


def test_chat_turn_prepare_run_fails_closed_without_creating_run(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user_id,
        name="Assistant",
    )
    session = _make_session(db, space_id=space_id, user_id=user_id)
    _make_message(db, session_id=session.id, space_id=space_id, user_id=user_id)
    assert db.query(Message).filter(Message.session_id == session.id).count() == 1
    runs_before = db.query(Run).count()

    response = api_client.post(
        "/api/v1/internal/agents-chat/prepare-run",
        headers=HEADER,
        json={
            "agent_id": agent.id,
            "space_id": space_id,
            "user_id": user_id,
            "session_id": session.id,
            "message": "  What changed in Stage 6 chat turn?  ",
        },
    )

    assert response.status_code == 410
    assert "TypeScript control plane" in response.text
    db.expire_all()
    assert db.query(Run).count() == runs_before
    assert db.query(Message).filter(Message.session_id == session.id).count() == 1


def test_prepare_run_fails_closed_when_context_authority_is_ts(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    """The combined build-and-persist port is permanently retired."""
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    session = _make_session(db, space_id=space_id, user_id=user_id)

    response = api_client.post(
        "/api/v1/internal/agents-chat/prepare-run",
        headers=HEADER,
        json={
            "agent_id": agent.id,
            "space_id": space_id,
            "user_id": user_id,
            "session_id": session.id,
            "message": "hello",
        },
    )

    assert response.status_code == 410


def test_context_candidates_returns_unbudgeted_candidates_without_writes(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    session = _make_session(db, space_id=space_id, user_id=user_id)
    snapshots_before = db.query(ContextSnapshot).count()

    response = api_client.post(
        "/api/v1/internal/agents-chat/context-candidates",
        headers=HEADER,
        json={
            "agent_id": agent.id,
            "space_id": space_id,
            "user_id": user_id,
            "session_id": session.id,
            "message": "what changed?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "memory" in body["allowed_sources"]
    assert body["max_tokens"] == 4000
    assert body["max_items"] == 20
    assert body["context_policy_applied"] is True
    assert isinstance(body["items"], list)
    # Read-only: the candidate port persists no snapshot rows.
    db.expire_all()
    assert db.query(ContextSnapshot).count() == snapshots_before


def test_context_candidates_requires_service_token(api_client, monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    response = api_client.post(
        "/api/v1/internal/agents-chat/context-candidates",
        json={
            "agent_id": "a",
            "space_id": "s",
            "user_id": "u",
            "session_id": "sess",
            "message": "hi",
        },
    )
    assert response.status_code == 401


def test_create_run_creates_queued_run_and_empty_snapshot(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    session = _make_session(db, space_id=space_id, user_id=user_id)

    response = api_client.post(
        "/api/v1/internal/agents-chat/create-run",
        headers=HEADER,
        json={
            "agent_id": agent.id,
            "space_id": space_id,
            "user_id": user_id,
            "session_id": session.id,
            "prompt": "PREAMBLE\n\nwhat changed?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert body["context_snapshot_id"]

    db.expire_all()
    run = db.query(Run).filter(Run.id == body["run_id"]).one()
    assert run.status == "queued"
    assert run.session_id == session.id
    assert run.prompt == "PREAMBLE\n\nwhat changed?"
    assert run.context_snapshot_id == body["context_snapshot_id"]
    # create-run does not build context: no snapshot items, no messages.
    assert (
        db.query(ContextSnapshotItem)
        .filter(ContextSnapshotItem.context_snapshot_id == body["context_snapshot_id"])
        .count()
        == 0
    )
    assert db.query(Message).filter(Message.session_id == session.id).count() == 0
