"""HTTP contract: POST /api/v1/runs/preflight rejects obsolete request fields.

PreflightRequest has extra="forbid" so any field not in the schema causes a
422 validation error before any handler logic executes.
"""

from __future__ import annotations

from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def test_preflight_valid_body_returns_preflight_result(db, cross_space_pair):
    """A minimal valid body is accepted; result contains executable and adapter_type."""
    from app.models import AgentVersion

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
    db.commit()

    r = cross_space_pair["client_a"].post(
        "/api/v1/runs/preflight",
        json={"agent_id": agent.id},
        params=_params(a),
    )
    assert r.status_code == 200
    body = r.json()
    assert "executable" in body
    assert body.get("adapter_type") == "model_api"


def test_preflight_rejects_space_id_in_body(db, cross_space_pair):
    """Sending space_id in the preflight body returns 422 (obsolete field)."""
    a = cross_space_pair["space_a_id"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/runs/preflight",
        json={"agent_id": "some-agent", "space_id": a},
        params=_params(a),
    )
    assert r.status_code == 422


def test_preflight_rejects_risk_level_in_body(db, cross_space_pair):
    """Sending risk_level in the preflight body returns 422 (obsolete field)."""
    a = cross_space_pair["space_a_id"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/runs/preflight",
        json={"agent_id": "some-agent", "risk_level": "high"},
        params=_params(a),
    )
    assert r.status_code == 422


def test_preflight_rejects_arbitrary_unknown_field_in_body(db, cross_space_pair):
    """Any unknown field in the preflight body returns 422."""
    a = cross_space_pair["space_a_id"]
    r = cross_space_pair["client_a"].post(
        "/api/v1/runs/preflight",
        json={"agent_id": "some-agent", "unexpected_field": "value"},
        params=_params(a),
    )
    assert r.status_code == 422
