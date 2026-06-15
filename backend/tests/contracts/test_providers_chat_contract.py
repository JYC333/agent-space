"""HTTP contract: provider chat and test use request-scoped DB; no outbound model calls when stubbed."""

from __future__ import annotations

from unittest.mock import patch

from app.config import paths
from app.providers.models import ChatResponse


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _isolate_crypto_home(monkeypatch, tmp_path):
    import app.crypto as crypto

    monkeypatch.setattr(crypto, "_KEY", None)
    home = tmp_path / "crypto_home_chat"
    monkeypatch.setattr(paths, "home", home)
    paths.init_dirs()


class _StubAdapter:
    """No network: returns a fixed ChatResponse."""

    async def complete(self, api_key, api_base, request):
        return ChatResponse(
            content="stubbed",
            provider="stub",
            model="stub-model",
            usage={"total_tokens": 1},
        )

    async def stream(self, api_key, api_base, request):
        del api_key, api_base, request
        if False:
            yield None


class _FailingAdapter:
    async def complete(self, api_key, api_base, request):
        del api_key, api_base, request
        raise RuntimeError("simulated upstream failure")

    async def stream(self, api_key, api_base, request):
        del api_key, api_base, request
        if False:
            yield None


def _assert_no_provider_secret_fields(data: dict) -> None:
    forbidden = {"api_key", "secret_ref", "encrypted_key", "credential_secret_ref"}
    assert forbidden.isdisjoint(data.keys())
    assert "sk-" not in str(data)


# Wire shape of ModelProviderOut, kept in lockstep with the shared TS contract
# (packages/protocol/src/providers.ts, ModelProviderDTOSchema). Adding or
# renaming a response field must update both sides together.
PROVIDER_WIRE_CONTRACT: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "space_id": (str,),
    "name": (str,),
    "provider_type": (str,),
    "base_url": (str, type(None)),
    "default_model": (str, type(None)),
    "available_models": (list,),
    "enabled": (bool,),
    "is_default": (bool,),
    "has_api_key": (bool,),
    "created_at": (str,),
    "updated_at": (str,),
}


def _assert_provider_wire_shape(data: dict) -> None:
    assert set(data.keys()) == set(PROVIDER_WIRE_CONTRACT.keys())
    for field, allowed in PROVIDER_WIRE_CONTRACT.items():
        assert isinstance(data[field], allowed), f"{field}={data[field]!r}"
    assert all(isinstance(m, str) for m in data["available_models"])


def test_provider_read_responses_match_shared_wire_contract(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    """Pin the exact ModelProviderOut JSON shape consumed by the TS edge facade."""
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()

    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "WireShapeCfg",
            "provider_type": "openai",
            "api_key": "sk-wire-shape",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
        },
    )
    assert create.status_code == 201
    _assert_provider_wire_shape(create.json())
    pid = create.json()["id"]
    db.commit()

    detail = cross_space_pair["client_a"].get(
        f"/api/v1/providers/{pid}", params=_params(a, ua.id)
    )
    assert detail.status_code == 200
    _assert_provider_wire_shape(detail.json())

    listing = cross_space_pair["client_a"].get(
        "/api/v1/providers", params=_params(a, ua.id)
    )
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)
    for item in listing.json():
        _assert_provider_wire_shape(item)


def test_provider_static_read_shapes_match_shared_wire_contract(
    api_client, db, cross_space_pair
):
    """Pin /providers/catalog and /providers/litellm-providers shapes; the TS
    edge claims these static routes explicitly and validates them."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()

    catalog = cross_space_pair["client_a"].get(
        "/api/v1/providers/catalog", params=_params(a, ua.id)
    )
    assert catalog.status_code == 200
    info = catalog.json()
    _assert_no_provider_secret_fields(info)
    # Exact values, pinned against PROVIDER_CATALOG_INFO in
    # packages/protocol/src/providers.ts. The TS provider authority serves this
    # payload, so the two must stay identical.
    assert info == {
        "id": "litellm",
        "name": "LiteLLM (Open Format)",
        "description": (
            "Configure OpenAI, Anthropic, OpenRouter, Ollama, or custom "
            "OpenAI-compatible endpoints."
        ),
        "model_hint": "Set default_model and/or available_models on the provider",
        "supported_params": ["model", "temperature", "max_tokens", "system"],
    }

    litellm_providers = cross_space_pair["client_a"].get(
        "/api/v1/providers/litellm-providers", params=_params(a, ua.id)
    )
    assert litellm_providers.status_code == 200
    payload = litellm_providers.json()
    assert isinstance(payload, list)
    assert all(isinstance(p, str) for p in payload)


def test_provider_crud_responses_are_secret_free(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()

    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "SecretFreeCfg",
            "provider_type": "openai",
            "api_key": "sk-secret-free",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": True,
        },
    )
    assert create.status_code == 201
    created = create.json()
    _assert_no_provider_secret_fields(created)
    assert created["has_api_key"] is True
    pid = created["id"]
    db.commit()

    get = cross_space_pair["client_a"].get(
        f"/api/v1/providers/{pid}",
        params=_params(a, ua.id),
    )
    assert get.status_code == 200
    _assert_no_provider_secret_fields(get.json())

    list_response = cross_space_pair["client_a"].get(
        "/api/v1/providers",
        params=_params(a, ua.id),
    )
    assert list_response.status_code == 200
    for item in list_response.json():
        _assert_no_provider_secret_fields(item)

    update = cross_space_pair["client_a"].patch(
        f"/api/v1/providers/{pid}",
        params=_params(a, ua.id),
        json={"api_key": "sk-secret-free-replacement"},
    )
    assert update.status_code == 200
    updated = update.json()
    _assert_no_provider_secret_fields(updated)
    assert updated["has_api_key"] is True


def test_provider_chat_uses_test_db_session(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "ChatCfg",
            "provider_type": "openai",
            "api_key": "sk-test-chat",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": True,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = cross_space_pair["client_a"].post(
            "/api/v1/providers/chat",
            params=_params(a, ua.id),
            json={
                "provider_id": pid,
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "stubbed"
    assert set(data.keys()) >= {"content", "provider", "model", "usage"}


def test_provider_chat_cross_space_provider_id_returns_404(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    db.commit()
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "SpaceAProv",
            "provider_type": "openai",
            "api_key": "sk-test-xspace",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = cross_space_pair["client_b"].post(
            "/api/v1/providers/chat",
            params=_params(b, ub.id),
            json={
                "provider_id": pid,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 404


def test_provider_test_connection_uses_test_db_session(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "TestCfg",
            "provider_type": "openai",
            "api_key": "sk-test-conn",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = cross_space_pair["client_a"].post(
            f"/api/v1/providers/{pid}/test",
            params=_params(a, ua.id),
        )
    assert r.status_code == 200
    out = r.json()
    assert out.get("success") is True


def test_provider_test_connection_failure_stable_shape(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()
    create = cross_space_pair["client_a"].post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "FailCfg",
            "provider_type": "openai",
            "api_key": "sk-test-fail",
            "available_models": ["gpt-4o-mini"],
            "default_model": "gpt-4o-mini",
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_FailingAdapter()):
        r = cross_space_pair["client_a"].post(
            f"/api/v1/providers/{pid}/test",
            params=_params(a, ua.id),
        )
    assert r.status_code == 200
    out = r.json()
    assert out.get("success") is False
    assert "message" in out
    assert "simulated upstream failure" in (out.get("message") or "")
