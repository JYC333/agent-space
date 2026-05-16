"""HTTP contract: ModelProvider (LLM configs) vs RuntimeAdapter (CLI adapters) are independent resources."""

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


def test_providers_list_shape(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].get("/api/v1/providers", params=_params(a, ua.id))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_cli_adapters_list_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].get("/api/v1/cli-adapters", params=_params(a, ua.id))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


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
        json={
            "name": "LLM One",
            "provider": "openai",
            "api_key": "sk-test-contract",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
    )
    assert create.status_code == 201
    prov_id = create.json()["id"]

    adapters_before = cross_space_pair["client_a"].get("/api/v1/cli-adapters", params=_params(a, ua.id)).json()
    mine = [x for x in adapters_before if x["id"] == rt.id]
    assert len(mine) == 1
    assert mine[0]["display_name"] == "Adapter Original"

    up = cross_space_pair["client_a"].put(
        f"/api/v1/providers/{prov_id}",
        params=_params(a, ua.id),
        json={"name": "LLM Renamed"},
    )
    assert up.status_code == 200
    assert up.json()["name"] == "LLM Renamed"

    adapters_after = cross_space_pair["client_a"].get("/api/v1/cli-adapters", params=_params(a, ua.id)).json()
    mine2 = [x for x in adapters_after if x["id"] == rt.id][0]
    assert mine2["display_name"] == "Adapter Original"


def test_cli_adapter_update_does_not_mutate_provider(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    db.commit()
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "Stable Name",
            "provider": "openai",
            "api_key": "sk-test-contract-2",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
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
        f"/api/v1/cli-adapters/{rt.id}",
        params=_params(a, ua.id),
        json={"display_name": "RT Renamed", "notes": "n1"},
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
        json={
            "name": "A-only",
            "provider": "openai",
            "api_key": "sk-test-contract-3",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    r = cross_space_pair["client_b"].get(
        f"/api/v1/providers/{pid}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
