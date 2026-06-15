"""Contracts for Stage 6 temporary Python context ports."""

from __future__ import annotations

import uuid

from app.config import settings
from app.models import Message, Session as SessionModel
from app.sessions.condenser import SessionCondenser


HEADER = {"x-agent-space-internal-token": "internal-token"}


def _make_session(db, *, space_id: str, user_id: str) -> SessionModel:
    session = SessionModel(
        id=str(uuid.uuid4()),
        space_id=space_id,
        user_id=user_id,
        title="stage6-port-test",
        status="active",
    )
    db.add(session)
    db.commit()
    return session


def _make_message(db, *, session_id: str, space_id: str, user_id: str, content: str) -> Message:
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


def test_stage6_context_ports_require_service_token(api_client, monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.get("/api/v1/internal/stage6-context/ports")

    assert response.status_code == 401
    assert response.json().get("error") == "unauthorized"


def test_stage6_context_ports_manifest_declares_scope_and_non_authority(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.get("/api/v1/internal/stage6-context/ports", headers=HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "python_stage6_context_ports"
    ports = {item["operation"]: item for item in body["ports"]}
    assert set(ports) == {
        "session_summary.get_latest",
        "context.build",
        "memory.read",
        "memory.proposal_create",
    }
    assert ports["session_summary.get_latest"]["owner"] == "sessions"
    assert ports["session_summary.get_latest"]["implemented"] is True
    assert ports["session_summary.get_latest"]["writes"] == []
    assert ports["context.build"]["owner"] == "memory_context"
    assert ports["context.build"]["implemented"] is False
    assert "context_snapshots" in ports["context.build"]["writes"]
    assert ports["memory.read"]["implemented"] is False
    assert ports["memory.read"]["writes"] == []
    assert ports["memory.proposal_create"]["implemented"] is False
    assert ports["memory.proposal_create"]["writes"] == ["proposals"]


def test_stage6_session_summary_python_port_is_retired_under_ts_authority(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    monkeypatch.setenv("CONTROL_PLANE_SESSIONS_AUTHORITY", "ts")

    manifest = api_client.get("/api/v1/internal/stage6-context/ports", headers=HEADER)

    assert manifest.status_code == 200
    ports = {item["operation"]: item for item in manifest.json()["ports"]}
    summary_port = ports["session_summary.get_latest"]
    assert summary_port["implemented"] is False
    assert summary_port["error_codes"] == [
        "stage6_port_not_implemented",
        "stage6_port_invalid_request",
    ]
    assert "TypeScript control plane" in summary_port["notes"]

    response = api_client.post(
        "/api/v1/internal/stage6-context/operations",
        headers=HEADER,
        json={
            "operation": "session_summary.get_latest",
            "space_id": "space-1",
            "payload_json": {"session_id": "session-1"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_implemented"
    assert body["error_code"] == "stage6_port_not_implemented"


def test_stage6_session_summary_port_returns_context_safe_summary(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user_id = cross_space_pair["user_a"].id
    session = _make_session(db, space_id=space_id, user_id=user_id)
    _make_message(
        db,
        session_id=session.id,
        space_id=space_id,
        user_id=user_id,
        content="Please summarize this Stage 6 migration context.",
    )
    SessionCondenser(db).condense(session.id, space_id, user_id=user_id)
    db.commit()

    response = api_client.post(
        "/api/v1/internal/stage6-context/operations",
        headers=HEADER,
        json={
            "operation": "session_summary.get_latest",
            "space_id": space_id,
            "user_id": user_id,
            "payload_json": {"session_id": session.id},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "session_summary.get_latest"
    assert body["owner"] == "sessions"
    assert body["status"] == "succeeded"
    summary = body["result_json"]["summary"]
    assert summary["session_id"] == session.id
    assert summary["version"] == 1
    assert summary["condenser_version"] == "pattern.v1"
    assert "secret_ref" not in str(body)


def test_stage6_session_summary_port_is_space_scoped(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    other_space_id = cross_space_pair["space_b_id"]
    user_id = cross_space_pair["user_a"].id
    session = _make_session(db, space_id=space_id, user_id=user_id)
    _make_message(
        db,
        session_id=session.id,
        space_id=space_id,
        user_id=user_id,
        content="private summary",
    )
    SessionCondenser(db).condense(session.id, space_id, user_id=user_id)
    db.commit()

    response = api_client.post(
        "/api/v1/internal/stage6-context/operations",
        headers=HEADER,
        json={
            "operation": "session_summary.get_latest",
            "space_id": other_space_id,
            "payload_json": {"session_id": session.id},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "session_summary_not_found"
    assert "private summary" not in response.text


def test_stage6_declared_unimplemented_ports_fail_closed(api_client, monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.post(
        "/api/v1/internal/stage6-context/operations",
        headers=HEADER,
        json={
            "operation": "context.build",
            "space_id": "space-1",
            "payload_json": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_implemented"
    assert body["error_code"] == "stage6_port_not_implemented"
