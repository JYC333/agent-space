"""HTTP contract: provider configuration and obsolete runtime-adapter APIs."""

from __future__ import annotations

import pytest

from app.config import paths


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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/runtime-adapters"),
        ("get", "/api/v1/runtime-adapters/catalog"),
        ("get", "/api/v1/runtime-adapters/detect"),
        ("get", "/api/v1/runtime-adapters/claude_code/detect"),
        ("post", "/api/v1/runtime-adapters"),
        ("patch", "/api/v1/runtime-adapters/adapter-1"),
        ("delete", "/api/v1/runtime-adapters/adapter-1"),
        ("post", "/api/v1/runtime-adapters/adapter-1/probe"),
        ("get", "/api/v1/runtime-adapters/adapter-1/usage"),
        ("post", "/api/v1/runtime-adapters/adapter-1/usage/refresh"),
    ],
)
def test_runtime_adapter_instance_api_removed(method, path, api_client, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]
    request = getattr(client, method)
    kwargs = {"params": _params(a, ua.id)}
    if method in {"post", "patch"}:
        kwargs["json"] = {"adapter_type": "model_api", "name": "Model API"}
    assert request(path, **kwargs).status_code == 404


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


def test_provider_update_is_provider_scoped(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json=_provider_create_body(),
    )
    assert create.status_code == 201
    prov_id = create.json()["id"]

    up = cross_space_pair["client_a"].patch(
        f"/api/v1/providers/{prov_id}",
        params=_params(a, ua.id),
        json={"name": "LLM Renamed"},
    )
    assert up.status_code == 200
    assert up.json()["name"] == "LLM Renamed"


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
