"""Contracts for Stage 6 temporary Python context ports."""

from __future__ import annotations

from app.config import settings


HEADER = {"x-agent-space-internal-token": "internal-token"}


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
    assert ports["session_summary.get_latest"]["implemented"] is False
    assert ports["session_summary.get_latest"]["error_codes"] == [
        "stage6_port_not_implemented",
        "stage6_port_invalid_request",
    ]
    assert ports["session_summary.get_latest"]["writes"] == []
    assert ports["context.build"]["owner"] == "memory_context"
    assert ports["context.build"]["implemented"] is False
    assert "context_snapshots" in ports["context.build"]["writes"]
    assert ports["memory.read"]["implemented"] is False
    assert ports["memory.read"]["writes"] == []
    assert ports["memory.proposal_create"]["implemented"] is False
    assert ports["memory.proposal_create"]["writes"] == ["proposals"]


def test_stage6_session_summary_python_port_is_retired(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

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
