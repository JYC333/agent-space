"""HTTP contract: agent endpoints require authentication and are space-scoped."""

from __future__ import annotations

from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# Unauthenticated requests — all must return 401
# ---------------------------------------------------------------------------

def test_get_agent_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.get(f"/api/v1/agents/{agent.id}", params=_params(a))
    assert r.status_code == 401


def test_patch_agent_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.patch(
        f"/api/v1/agents/{agent.id}",
        params=_params(a),
        json={"name": "hacked"},
    )
    assert r.status_code == 401


def test_delete_agent_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    r = api_client.delete(f"/api/v1/agents/{agent.id}", params=_params(a))
    assert r.status_code == 401


def test_get_agent_run_by_id_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = api_client.get(f"/api/v1/agents/runs/{run.id}", params=_params(a))
    assert r.status_code == 401


def test_get_run_chain_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    r = api_client.get(f"/api/v1/agents/runs/{run.id}/chain", params=_params(a))
    assert r.status_code == 401


def test_get_agent_version_requires_auth(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
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


def test_run_create_resolves_agent_default_model(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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
    assert run_body["model_provider_id"] == prov_id
    assert run_body["resolved_model"]["model"] == "gpt-4o-mini"
    assert run_body["resolved_model"]["source"] == "agent_default"
    assert run_body["resolved_model"]["used_by_adapter"] is False
    assert run_body["resolved_model"]["adapter_model_support"] == "not_applicable"


def test_run_create_request_model_overrides_agent_default(
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
    assert run_body["resolved_model"]["model"] == "gpt-4o"
    assert run_body["resolved_model"]["source"] == "request"
