"""HTTP contract: agent endpoints require authentication and are space-scoped."""

from __future__ import annotations

import pytest

from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _fresh_policy_record(action: str, **filters):
    from app.db import SessionLocal
    from app.models import PolicyDecisionRecord

    fresh = SessionLocal()
    try:
        query = fresh.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == action
        )
        for field, value in filters.items():
            query = query.filter(getattr(PolicyDecisionRecord, field) == value)
        return query.one()
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# Unauthenticated requests — all must return 401
# ---------------------------------------------------------------------------

def test_get_agent_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.get(f"/api/v1/agents/{agent.id}", params=_params(a))
    assert r.status_code == 401


def test_patch_agent_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.patch(
        f"/api/v1/agents/{agent.id}",
        params=_params(a),
        json={"name": "hacked"},
    )
    assert r.status_code == 401


def test_delete_agent_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.delete(f"/api/v1/agents/{agent.id}", params=_params(a))
    assert r.status_code == 401


def test_get_agent_run_by_id_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = api_client.get(f"/api/v1/agents/runs/{run.id}", params=_params(a))
    assert r.status_code == 401


def test_get_run_chain_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = api_client.get(f"/api/v1/agents/runs/{run.id}/chain", params=_params(a))
    assert r.status_code == 401


def test_get_agent_version_requires_auth(api_client, db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    version_id = agent.current_version_id
    r = api_client.get(
        f"/api/v1/agents/{agent.id}/versions/{version_id}",
        params=_params(a),
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cross-space requests — authenticated user from space B cannot access space A
# ---------------------------------------------------------------------------

def test_get_agent_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_b"].get(
        f"/api/v1/agents/{agent.id}",
        params=_params(b),
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


def test_patch_agent_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    original_name = agent.name
    r = cross_space_pair["client_b"].patch(
        f"/api/v1/agents/{agent.id}",
        params=_params(b),
        json={"name": "hacked"},
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"
    # DB state must be unchanged — the agent was not mutated
    from app.models import Agent as _Agent
    db.expire_all()
    agent_after = db.query(_Agent).filter(_Agent.id == agent.id).first()
    assert agent_after.name == original_name


def test_delete_agent_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_b"].delete(
        f"/api/v1/agents/{agent.id}",
        params=_params(b),
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"
    # DB state must be unchanged — the agent was not archived
    from app.models import Agent as _Agent
    db.expire_all()
    agent_after = db.query(_Agent).filter(_Agent.id == agent.id).first()
    assert agent_after.status == "active"


def test_get_agent_run_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = cross_space_pair["client_b"].get(
        f"/api/v1/agents/runs/{run.id}",
        params=_params(b),
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


def test_get_run_chain_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = cross_space_pair["client_b"].get(
        f"/api/v1/agents/runs/{run.id}/chain",
        params=_params(b),
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


def test_get_agent_version_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    version_id = agent.current_version_id
    r = cross_space_pair["client_b"].get(
        f"/api/v1/agents/{agent.id}/versions/{version_id}",
        params=_params(b),
    )
    assert r.status_code == 404
    assert r.json().get("error") == "not_found"


# ---------------------------------------------------------------------------
# Chain traversal does not cross space boundary
# ---------------------------------------------------------------------------

def test_run_chain_stops_at_cross_space_parent(api_client, db, cross_space_pair):
    """A run chain that has a parent in another space must not traverse into that space."""
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]

    agent_a = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    agent_b = factories.create_test_agent(db, space_id=b, owner_user_id=ub.id, commit=False)

    # Parent run lives in space B
    parent_run = factories.create_test_run(db, space_id=b, user_id=ub.id, agent=agent_b, commit=False)
    # Child run lives in space A
    child_run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent_a, commit=False)
    # Wire the cross-space parent link directly on the ORM object
    child_run.parent_run_id = parent_run.id
    db.commit()

    child_run_id = child_run.id

    # Space A user requests chain for the child run — must only see the child, not the parent
    r = cross_space_pair["client_a"].get(
        f"/api/v1/agents/runs/{child_run_id}/chain",
        params=_params(a),
    )
    assert r.status_code == 200
    chain = r.json()
    ids_in_chain = {item["id"] for item in chain}
    assert child_run_id in ids_in_chain
    assert parent_run.id not in ids_in_chain


# ---------------------------------------------------------------------------
# Same-space access still works after the fix
# ---------------------------------------------------------------------------

def test_get_agent_same_space_succeeds(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_a"].get(
        f"/api/v1/agents/{agent.id}",
        params=_params(a),
    )
    assert r.status_code == 200
    assert r.json()["id"] == agent.id


def test_get_agent_run_same_space_succeeds(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = cross_space_pair["client_a"].get(
        f"/api/v1/agents/runs/{run.id}",
        params=_params(a),
    )
    assert r.status_code == 200
    assert r.json()["id"] == run.id


def test_get_agent_version_same_space_succeeds(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    version_id = agent.current_version_id
    r = cross_space_pair["client_a"].get(
        f"/api/v1/agents/{agent.id}/versions/{version_id}",
        params=_params(a),
    )
    assert r.status_code == 200
    assert r.json()["id"] == version_id


def test_patch_agent_execution_fields_points_to_config_proposals(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    original_name = agent.name

    r = cross_space_pair["client_a"].patch(
        f"/api/v1/agents/{agent.id}",
        params=_params(a),
        json={"name": "new name", "system_prompt": "use stricter instructions"},
    )

    assert r.status_code == 409
    assert "config-proposals" in str(r.json().get("message"))
    db.expire_all()
    refreshed = db.query(type(agent)).filter(type(agent).id == agent.id).one()
    assert refreshed.name == original_name


def test_direct_agent_version_create_is_disabled(api_client, db, cross_space_pair):
    from app.models import AgentVersion

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    before = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).count()

    r = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/versions",
        params=_params(a),
        json={"system_prompt": "direct mutation"},
    )

    assert r.status_code == 409
    assert "config-proposals" in str(r.json().get("message"))
    assert db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).count() == before


@pytest.mark.durable_audit
def test_agent_config_proposal_accept_creates_immutable_new_version(api_client, db, cross_space_pair):
    from app.memory.digest_service import ContextDigestService
    from app.models import ActivityRecord, Agent, AgentVersion, ContextDigest, Proposal

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    base_version_id = agent.current_version_id
    ContextDigestService(db).generate_agent_digest(a, agent.id)
    db.commit()

    create = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/config-proposals",
        params=_params(a),
        json={
            "base_version_id": base_version_id,
            "system_prompt": "answer with citations",
            "runtime_policy_json": {"risk_level": "medium", "max_run_time_seconds": 120},
        },
    )
    assert create.status_code == 202, create.text
    proposal_id = create.json()["id"]

    db.expire_all()
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).one()
    assert proposal.proposal_type == "agent_config_update"
    assert proposal.payload_json["agent_id"] == agent.id
    assert proposal.payload_json["base_version_id"] == base_version_id
    assert proposal.payload_json["changes"]["system_prompt"] == "answer with citations"
    policy_record = _fresh_policy_record(
        "agent.config_update",
        resource_id=agent.id,
        actor_id=ua.id,
    )
    assert policy_record.decision == "allow"
    assert policy_record.metadata_json["changed_fields"] == ["runtime_policy_json", "system_prompt"]
    assert db.query(Agent).filter(Agent.id == agent.id).one().current_version_id == base_version_id

    accept = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{proposal_id}/accept",
        params=_params(a),
    )
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["result_type"] == "agent_version"
    new_version_id = body["result"]["agent_version_id"]
    assert new_version_id != base_version_id

    db.expire_all()
    updated_agent = db.query(Agent).filter(Agent.id == agent.id).one()
    new_version = db.query(AgentVersion).filter(AgentVersion.id == new_version_id).one()
    base_version = db.query(AgentVersion).filter(AgentVersion.id == base_version_id).one()
    assert updated_agent.current_version_id == new_version_id
    assert new_version.system_prompt == "answer with citations"
    assert new_version.runtime_policy_json["max_run_time_seconds"] == 120
    assert new_version.source_proposal_id == proposal_id
    assert new_version.source_activity_id
    assert base_version.system_prompt != "answer with citations"
    activity = (
        db.query(ActivityRecord)
        .filter(
            ActivityRecord.id == new_version.source_activity_id,
            ActivityRecord.activity_type == "agent_config_updated",
        )
        .one()
    )
    assert activity.user_id == ua.id
    assert activity.payload_json["new_version_id"] == new_version_id
    digest = (
        db.query(ContextDigest)
        .filter(
            ContextDigest.space_id == a,
            ContextDigest.scope_type == "agent",
            ContextDigest.scope_id == agent.id,
            ContextDigest.digest_type == "agent",
        )
        .one()
    )
    assert digest.status == "dirty"
    assert "agent_config_update" in digest.dirty_reason_json["latest"]


def test_agent_config_proposal_rejects_stale_base_on_accept(api_client, db, cross_space_pair):
    from app.models import Agent, AgentVersion, Proposal

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    base = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()

    create = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/config-proposals",
        params=_params(a),
        json={"base_version_id": base.id, "system_prompt": "stale change"},
    )
    assert create.status_code == 202, create.text
    proposal_id = create.json()["id"]

    replacement = AgentVersion(
        agent_id=agent.id,
        space_id=a,
        version_label="v-stale-test",
        model_provider_id=base.model_provider_id,
        model_name=base.model_name,
        runtime_adapter_id=base.runtime_adapter_id,
        system_prompt="already changed",
        model_config_json=base.model_config_json,
        runtime_config_json=base.runtime_config_json,
        context_policy_json=base.context_policy_json,
        memory_policy_json=base.memory_policy_json,
        capabilities_json=base.capabilities_json,
        tool_permissions_json=base.tool_permissions_json,
        runtime_policy_json=base.runtime_policy_json,
    )
    db.add(replacement)
    db.flush()
    agent.current_version_id = replacement.id
    db.commit()

    accept = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{proposal_id}/accept",
        params=_params(a),
    )
    assert accept.status_code == 422
    assert "stale" in str(accept.json().get("message")).lower()
    db.expire_all()
    assert db.query(Agent).filter(Agent.id == agent.id).one().current_version_id == replacement.id
    assert db.query(Proposal).filter(Proposal.id == proposal_id).one().status == "pending"


def test_agent_save_default_model_provider(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import paths
    import app.crypto as crypto

    monkeypatch.setattr(crypto, "_KEY", None)
    home = tmp_path / "crypto_home_agent"
    monkeypatch.setattr(paths, "home", home)
    paths.init_dirs()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create_prov = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a),
        json={
            "name": "Agent Prov",
            "provider_type": "openai",
            "api_key": "sk-agent-test",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    assert create_prov.status_code == 201
    prov_id = create_prov.json()["id"]

    create_agent = cross_space_pair["client_a"].post(
        "/api/v1/agents",
        params=_params(a),
        json={
            "name": "Model Agent",
            "default_model_provider_id": prov_id,
            "default_model": "gpt-4o-mini",
        },
    )
    assert create_agent.status_code == 201
    body = create_agent.json()
    assert body["model"]["provider_id"] == prov_id
    assert body["model"]["model"] == "gpt-4o-mini"


def test_echo_run_create_does_not_attach_agent_default_model(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import paths
    import app.crypto as crypto

    monkeypatch.setattr(crypto, "_KEY", None)
    home = tmp_path / "crypto_home_run"
    monkeypatch.setattr(paths, "home", home)
    paths.init_dirs()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create_prov = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a),
        json={
            "name": "Run Prov",
            "provider_type": "openai",
            "api_key": "sk-run-test",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    assert create_prov.status_code == 201
    prov_id = create_prov.json()["id"]
    assert create_prov.json()["has_api_key"] is True
    assert "api_key" not in create_prov.json()

    create_agent = cross_space_pair["client_a"].post(
        "/api/v1/agents",
        params=_params(a),
        json={
            "name": "Run Model Agent",
            "default_model_provider_id": prov_id,
            "default_model": "gpt-4o-mini",
        },
    )
    assert create_agent.status_code == 201
    agent_id = create_agent.json()["id"]

    create_run = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent_id}/runs",
        params=_params(a),
        json={"mode": "live", "adapter_type": "echo"},
    )
    assert create_run.status_code == 201
    run_body = create_run.json()
    assert run_body["model_provider_id"] is None
    assert run_body["resolved_model"]["provider_id"] is None
    assert run_body["resolved_model"]["model"] is None
    assert run_body["resolved_model"]["source"] == "none"
    assert run_body["resolved_model"]["used_by_adapter"] is False
    assert run_body["resolved_model"]["adapter_model_support"] == "not_applicable"


def test_echo_run_create_ignores_request_model_override(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import paths
    import app.crypto as crypto

    monkeypatch.setattr(crypto, "_KEY", None)
    home = tmp_path / "crypto_home_run_override"
    monkeypatch.setattr(paths, "home", home)
    paths.init_dirs()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create_prov = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a),
        json={
            "name": "Override Prov",
            "provider_type": "openai",
            "api_key": "sk-override",
            "available_models": ["gpt-4o-mini", "gpt-4o"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    prov_id = create_prov.json()["id"]

    create_agent = cross_space_pair["client_a"].post(
        "/api/v1/agents",
        params=_params(a),
        json={
            "name": "Override Agent",
            "default_model_provider_id": prov_id,
            "default_model": "gpt-4o-mini",
        },
    )
    agent_id = create_agent.json()["id"]

    create_run = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent_id}/runs",
        params=_params(a),
        json={
            "mode": "live",
            "adapter_type": "echo",
            "model_provider_id": prov_id,
            "model": "gpt-4o",
        },
    )
    assert create_run.status_code == 201
    run_body = create_run.json()
    assert run_body["model_provider_id"] is None
    assert run_body["resolved_model"]["provider_id"] is None
    assert run_body["resolved_model"]["model"] is None
    assert run_body["resolved_model"]["source"] == "none"
    assert run_body["resolved_model"]["used_by_adapter"] is False
    assert run_body["resolved_model"]["adapter_model_support"] == "not_applicable"


# ---------------------------------------------------------------------------
# No delegate route; public run schemas reject unknown fields
# ---------------------------------------------------------------------------

def test_delegate_route_does_not_exist(api_client, db, cross_space_pair):
    """POST /{agent_id}/delegate must return 404, not 501."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/delegate",
        params=_params(a),
        json={},
    )
    assert r.status_code == 404


def test_run_creation_rejects_parent_run_trigger_origin(api_client, db, cross_space_pair):
    """trigger_origin='parent_run' is not a valid trigger origin."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/runs",
        params=_params(a),
        json={"mode": "live", "trigger_origin": "parent_run"},
    )
    assert r.status_code == 422


def test_run_creation_rejects_instructed_by_agent_id(api_client, db, cross_space_pair):
    """instructed_by_agent_id is not a public RunCreate field; RunCreate uses extra='forbid'."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/runs",
        params=_params(a),
        json={"mode": "live", "instructed_by_agent_id": agent.id},
    )
    assert r.status_code == 422


def test_superseded_run_endpoint_rejects_parent_run_id(api_client, db, cross_space_pair):
    """POST /{agent_id}/run does not support lineage; parent_run_id returns 422."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = cross_space_pair["client_a"].post(
        f"/api/v1/agents/{agent.id}/run",
        params=_params(a),
        json={"prompt": "test", "parent_run_id": run.id},
    )
    assert r.status_code == 422
