"""Contract: session summary context seam.

Stage 6 migrates memory + sessions together. Until the authority moves, memory
context assembly should depend on a narrow sessions-owned port rather than the
concrete ``sessions.condenser`` internals.
"""

from __future__ import annotations

import uuid

from app.config import settings
from app.models import Message, Session as SessionModel
from app.sessions import (
    SessionSummaryForContext,
    SessionSummaryPort,
    get_session_summary_port,
)
from app.sessions.control_plane_client import ControlPlaneSessionSummaryPort
from app.sessions.condenser import SessionCondenser


def _make_session(db, *, space_id: str, user_id: str) -> SessionModel:
    row = SessionModel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        user_id=user_id,
        title="summary-port-test",
        status="active",
    )
    db.add(row)
    db.commit()
    return row


def _make_message(db, *, session_id: str, space_id: str, user_id: str, content: str) -> Message:
    row = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        role="user",
        content=content,
    )
    db.add(row)
    db.commit()
    return row


def test_session_condenser_satisfies_summary_port():
    assert issubclass(SessionCondenser, SessionSummaryPort)


def test_session_summary_port_is_reexported_from_facade():
    from app.sessions import SessionSummaryPort as FromFacade
    from app.sessions.ports import SessionSummaryPort as FromModule

    assert FromFacade is FromModule


def test_session_summary_port_returns_context_safe_dto(db, cross_space_pair_db, monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_SESSIONS_AUTHORITY", raising=False)
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    other_space_id = cross_space_pair_db["space_b_id"]
    session = _make_session(db, space_id=space_id, user_id=user_id)
    _make_message(
        db,
        session_id=session.id,
        space_id=space_id,
        user_id=user_id,
        content="Please help me plan the migration.",
    )
    SessionCondenser(db).condense(session.id, space_id, user_id=user_id)

    port = get_session_summary_port(db)
    summary = port.get_latest_for_context(session.id, space_id)

    assert isinstance(summary, SessionSummaryForContext)
    assert summary.session_id == session.id
    assert summary.version == 1
    assert summary.condenser_version == "pattern.v1"
    assert "migration" in summary.summary_text.lower()
    assert port.get_latest_for_context(session.id, other_space_id) is None


def test_session_summary_port_resolves_to_control_plane_when_flipped(db, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_SESSIONS_AUTHORITY", "ts")

    assert isinstance(get_session_summary_port(db), ControlPlaneSessionSummaryPort)


def test_control_plane_session_summary_port_parses_context_safe_dto(monkeypatch):
    calls: list[dict] = []

    class _Response:
        status_code = 200

        def json(self):
            return {
                "summary": {
                    "id": "summary-1",
                    "session_id": "session-1",
                    "version": 2,
                    "summary_text": "latest summary",
                    "condenser_version": "pattern.v1",
                }
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            calls.append({"timeout": kwargs.get("timeout")})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return _Response()

    monkeypatch.setattr("app.sessions.control_plane_client.httpx.Client", _Client)
    monkeypatch.setattr(settings, "control_plane_internal_url", "http://control-plane")
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    monkeypatch.setattr(settings, "control_plane_internal_timeout_seconds", 5.0)

    summary = ControlPlaneSessionSummaryPort().get_latest_for_context(
        "session-1",
        "space-1",
    )

    assert summary == SessionSummaryForContext(
        id="summary-1",
        session_id="session-1",
        version=2,
        summary_text="latest summary",
        condenser_version="pattern.v1",
    )
    assert calls[0] == {"timeout": 5.0}
    assert calls[1]["url"] == "http://control-plane/internal/sessions/session-summary/get-latest"
    assert calls[1]["headers"]["x-agent-space-internal-token"] == "internal-token"
    assert calls[1]["json"] == {"session_id": "session-1", "space_id": "space-1"}
