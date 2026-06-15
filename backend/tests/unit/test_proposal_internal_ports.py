from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.modules.registry import _REGISTRY
from app.proposals import internal_api as internal_api_module
from app.proposals.internal_api import router


def test_proposal_internal_ports_require_service_token(monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    unauthorized = client.get("/api/v1/internal/proposals-context/ports")
    assert unauthorized.status_code == 401

    authorized = client.get(
        "/api/v1/internal/proposals-context/ports",
        headers={"x-agent-space-internal-token": "internal-token"},
    )

    assert authorized.status_code == 200
    body = authorized.json()
    assert body["service"] == "python_proposals_context_ports"
    assert [port["operation"] for port in body["ports"]] == [
        "proposal.accept",
        "proposal.reject",
        "proposal.egress_approval",
        "memory.apply_gate",
    ]


def test_internal_accept_does_not_leak_memory_apply_ownership_for_invisible_proposal(
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    monkeypatch.setenv("CONTROL_PLANE_MEMORY_APPLY_AUTHORITY", "ts")

    class FakeProposalService:
        def __init__(self, db):
            self.db = db

        def get(self, proposal_id):
            raise AssertionError("unscoped get must not run before visibility check")

        def get_proposal_for_viewer(self, proposal_id, space_id, user_id):
            return None

        def accept(self, proposal_id, *, space_id, user_id):
            return None

    monkeypatch.setattr(internal_api_module, "ProposalService", FakeProposalService)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    response = client.post(
        "/api/v1/internal/proposals-context/accept",
        headers={"x-agent-space-internal-token": "internal-token"},
        json={"proposal_id": "proposal-1", "space_id": "space-1", "user_id": "user-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Proposal not found or already decided"


def test_internal_accept_fails_closed_for_visible_memory_proposal_when_ts_apply(
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    monkeypatch.setenv("CONTROL_PLANE_MEMORY_APPLY_AUTHORITY", "ts")

    class FakeProposalService:
        def __init__(self, db):
            self.db = db

        def get_proposal_for_viewer(self, proposal_id, space_id, user_id):
            return SimpleNamespace(proposal_type="memory_create")

        def accept(self, proposal_id, *, space_id, user_id):
            raise AssertionError("Python accept must not apply TS-owned memory proposals")

    monkeypatch.setattr(internal_api_module, "ProposalService", FakeProposalService)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    response = client.post(
        "/api/v1/internal/proposals-context/accept",
        headers={"x-agent-space-internal-token": "internal-token"},
        json={"proposal_id": "proposal-1", "space_id": "space-1", "user_id": "user-1"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "TypeScript control plane applies memory_create/update/archive" in detail


def test_proposals_module_declares_public_and_internal_routers():
    proposals = next(module for module in _REGISTRY if module.id == "proposals")

    assert proposals.api_modules == ["api", "internal_api"]
