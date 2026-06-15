from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.policy.control_plane_client import (
    ControlPlanePolicyGateway,
    policy_owned_by_control_plane,
)
from app.policy.exceptions import PolicyGateBlocked
from app.policy.gateway import PolicyCheckRequest


def _wire_decision(decision: str = "allow") -> dict:
    return {
        "decision": decision,
        "message": "from ts",
        "risk_level": "medium",
        "action": "runtime.execute",
        "actor_type": "run",
        "actor_id": "run-1",
        "space_id": "space-1",
        "resource_type": "run",
        "resource_id": "run-1",
    }


def test_policy_authority_flag_reads_settings(monkeypatch):
    monkeypatch.setattr(settings, "control_plane_policy_authority", "ts")
    assert policy_owned_by_control_plane() is True
    monkeypatch.setattr(settings, "control_plane_policy_authority", "python")
    assert policy_owned_by_control_plane() is False


def test_enforce_allow_returns_policy_decision(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def _post(path: str, payload: dict):
        calls.append((path, payload))
        return {"status": "allow", "decision": _wire_decision("allow")}

    monkeypatch.setattr("app.policy.control_plane_client._post_internal", _post)

    decision = ControlPlanePolicyGateway(db=object()).enforce(
        PolicyCheckRequest(
            action="runtime.execute",
            actor_type="run",
            actor_id="run-1",
            space_id="space-1",
            resource_type="run",
            resource_id="run-1",
        )
    )

    assert decision.allowed
    assert calls[0][0] == "/internal/policy/enforce"
    assert calls[0][1]["action"] == "runtime.execute"


def test_enforce_blocked_marks_audit_as_already_handled(monkeypatch):
    def _post(path: str, payload: dict):
        return {"status": "blocked", "decision": _wire_decision("deny")}

    monkeypatch.setattr("app.policy.control_plane_client._post_internal", _post)

    with pytest.raises(PolicyGateBlocked) as exc_info:
        ControlPlanePolicyGateway(db=object()).enforce(
            PolicyCheckRequest(
                action="runtime.execute",
                actor_type="run",
                actor_id="run-1",
                space_id="space-1",
            )
        )

    assert exc_info.value.error_code == "policy_denied"
    assert exc_info.value.audit_already_persisted is True


def test_proposal_apply_sends_python_owned_context_inputs(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def _post(path: str, payload: dict):
        calls.append((path, payload))
        return {
            "status": "allow",
            "decision": {
                **_wire_decision("allow"),
                "action": "proposal.apply",
                "resource_type": "proposal",
                "resource_id": "proposal-1",
            },
        }

    monkeypatch.setattr("app.policy.control_plane_client._post_internal", _post)
    monkeypatch.setattr("app.policy.control_plane_client.get_space_role", lambda *_: "owner")
    monkeypatch.setattr(
        "app.policy.control_plane_client.supported_proposal_apply_types",
        lambda: frozenset({"memory_create"}),
    )

    proposal = SimpleNamespace(
        id="proposal-1",
        proposal_type="memory_create",
        risk_level="medium",
        payload_json={"title": "safe summary"},
    )
    decision = ControlPlanePolicyGateway(db=object()).enforce_proposal_apply(
        user_id="user-1",
        space_id="space-1",
        proposal=proposal,
        metadata_json={"reason": "test"},
    )

    assert decision.allowed
    assert calls[0][0] == "/internal/policy/enforce-proposal-apply"
    assert calls[0][1]["membership_role"] == "owner"
    assert calls[0][1]["supported_proposal_types"] == ["memory_create"]
    assert calls[0][1]["payload"] == {"title": "safe summary"}
