"""HTTP contract: ModelProvider configs and RuntimeAdapter rows are independent resources."""

from __future__ import annotations

from app.config import paths
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _isolate_crypto_home(monkeypatch, tmp_path):
    import app.crypto as crypto

    monkeypatch.setattr(crypto, "_KEY", None)
    home = tmp_path / "crypto_home"
    monkeypatch.setattr(paths, "home", home)
    paths.init_dirs()


def _provider_create_body(**overrides):
    body = {
        "name": "LLM One",
        "provider_type": "openai",
        "api_key": "sk-test-contract",
        "available_models": ["gpt-4o-mini"],
        "default_model": "gpt-4o-mini",
        "is_default": False,
    }
    body.update(overrides)
    return body


def test_providers_list_shape(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].get("/api/v1/providers", params=_params(a, ua.id))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_runtime_adapters_list_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].get("/api/v1/runtime-adapters", params=_params(a, ua.id))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_runtime_adapters_catalog_and_detect_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    catalog = cross_space_pair["client_a"].get("/api/v1/runtime-adapters/catalog", params=_params(a, ua.id))
    assert catalog.status_code == 200
    assert any(item["adapter_type"] == "echo" for item in catalog.json())
    detect = cross_space_pair["client_a"].get("/api/v1/runtime-adapters/detect", params=_params(a, ua.id))
    assert detect.status_code == 200
    assert all("adapter_type" in item for item in detect.json())
    echo_status = next(item for item in detect.json() if item["adapter_type"] == "echo")
    assert echo_status["configured"] is False
    assert echo_status["last_run_status"] is None
    assert echo_status["last_error_code"] is None


def test_runtime_adapter_create_planned_and_usage_contract(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]
    created = client.post(
        "/api/v1/runtime-adapters",
        params=_params(a, ua.id),
        json={"adapter_type": "echo", "name": "Echo", "health_status": "ok", "quota_status": "medium"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["health_status"] == "ok"
    assert body["quota_status"] == "medium"
    usage = client.get(f"/api/v1/runtime-adapters/{body['id']}/usage", params=_params(a, ua.id))
    assert usage.status_code == 200
    assert usage.json()["usage_accuracy"] == "unknown"
    assert usage.json()["runtime_adapter_id"] == body["id"]
    refresh = client.post(f"/api/v1/runtime-adapters/{body['id']}/usage/refresh", params=_params(a, ua.id))
    assert refresh.status_code == 200
    assert refresh.json()["supports_usage_probe"] is False

    planned_enabled = client.post(
        "/api/v1/runtime-adapters",
        params=_params(a, ua.id),
        json={"adapter_type": "opencode", "name": "OpenCode", "enabled": True},
    )
    assert planned_enabled.status_code == 400
    planned_disabled = client.post(
        "/api/v1/runtime-adapters",
        params=_params(a, ua.id),
        json={"adapter_type": "opencode", "name": "OpenCode", "enabled": False},
    )
    assert planned_disabled.status_code == 201
    assert planned_disabled.json()["health_status"] == "unimplemented"
    patch = client.patch(
        f"/api/v1/runtime-adapters/{planned_disabled.json()['id']}",
        params=_params(a, ua.id),
        json={"enabled": True},
    )
    assert patch.status_code == 400


def test_runtime_adapter_probe_is_non_mutating_and_test_route_removed(api_client, db, cross_space_pair):
    from app.models import CliCredentialEvent, Run, RunEvent

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]
    created = client.post(
        "/api/v1/runtime-adapters",
        params=_params(a, ua.id),
        json={"adapter_type": "echo", "name": "Echo"},
    )
    assert created.status_code == 201
    adapter_id = created.json()["id"]

    before = {
        "runs": db.query(Run).count(),
        "events": db.query(RunEvent).count(),
        "credentials": db.query(CliCredentialEvent).count(),
    }
    probe = client.post(f"/api/v1/runtime-adapters/{adapter_id}/probe", params=_params(a, ua.id))
    assert probe.status_code == 200
    assert probe.json()["runtime_adapter_id"] == adapter_id
    assert probe.json()["adapter_type"] == "echo"
    removed = client.post(f"/api/v1/runtime-adapters/{adapter_id}/test", params=_params(a, ua.id))
    assert removed.status_code == 404
    after = {
        "runs": db.query(Run).count(),
        "events": db.query(RunEvent).count(),
        "credentials": db.query(CliCredentialEvent).count(),
    }
    assert after == before


def test_removed_old_runtime_adapter_route_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    removed_path = "/api/v1/" + "cli-adapters"
    r = cross_space_pair["client_a"].get(removed_path, params=_params(a, ua.id))
    assert r.status_code == 404


def test_model_provider_response_never_includes_api_key(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(name="Secret Test"),
    )
    assert create.status_code == 201
    data = create.json()
    assert data["has_api_key"] is True
    assert "api_key" not in data

    prov_id = data["id"]
    get_r = cross_space_pair["client_a"].get(f"/api/v1/providers/{prov_id}", params=_params(a, ua.id))
    assert get_r.status_code == 200
    assert "api_key" not in get_r.json()


def test_provider_update_does_not_mutate_runtime_adapter(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    rt = factories.create_test_runtime_adapter(
        db,
        space_id=a,
        name="Adapter Original",
        adapter_type="echo",
        commit=True,
    )
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(),
    )
    assert create.status_code == 201
    prov_id = create.json()["id"]

    adapters_before = cross_space_pair["client_a"].get("/api/v1/runtime-adapters", params=_params(a, ua.id)).json()
    mine = [x for x in adapters_before if x["id"] == rt.id]
    assert len(mine) == 1
    assert mine[0]["name"] == "Adapter Original"

    up = cross_space_pair["client_a"].patch(
        f"/api/v1/providers/{prov_id}",
        params=_params(a, ua.id),
        json={"name": "LLM Renamed"},
    )
    assert up.status_code == 200
    assert up.json()["name"] == "LLM Renamed"

    adapters_after = cross_space_pair["client_a"].get("/api/v1/runtime-adapters", params=_params(a, ua.id)).json()
    mine2 = [x for x in adapters_after if x["id"] == rt.id][0]
    assert mine2["name"] == "Adapter Original"


def test_runtime_adapter_update_does_not_mutate_provider(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    db.commit()
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(name="Stable Name", api_key="sk-test-contract-2"),
    )
    assert create.status_code == 201
    prov = create.json()

    rt = factories.create_test_runtime_adapter(
        db,
        space_id=a,
        name="RT",
        adapter_type="echo",
        commit=True,
    )
    patch = cross_space_pair["client_a"].patch(
        f"/api/v1/runtime-adapters/{rt.id}",
        params=_params(a, ua.id),
        json={"name": "RT Renamed", "notes": "n1"},
    )
    assert patch.status_code == 200

    prov_r = cross_space_pair["client_a"].get(
        f"/api/v1/providers/{prov['id']}",
        params=_params(a, ua.id),
    )
    assert prov_r.status_code == 200
    assert prov_r.json()["name"] == "Stable Name"


def test_get_provider_other_space_returns_404(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    db.commit()
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(name="A-only", api_key="sk-test-contract-3"),
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    r = cross_space_pair["client_b"].get(
        f"/api/v1/providers/{pid}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_provider_models_endpoint_returns_configured_source(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(available_models=["gpt-4o-mini", "gpt-4o"]),
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    r = cross_space_pair["client_a"].get(f"/api/v1/providers/{pid}/models", params=_params(a, ua.id))
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "configured"
    assert "gpt-4o-mini" in data["models"]
