"""HTTP contract: provider chat and test use request-scoped DB; no outbound model calls when stubbed."""

from __future__ import annotations

from unittest.mock import patch

from app.config import paths
from app.providers.models import ChatResponse


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


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


def test_provider_chat_uses_test_db_session(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    _isolate_crypto_home(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    db.commit()
    create = api_client.post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "ChatCfg",
            "provider": "openai",
            "api_key": "sk-test-chat",
            "models": ["gpt-4o-mini"],
            "is_default": True,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = api_client.post(
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
    create = api_client.post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "SpaceAProv",
            "provider": "openai",
            "api_key": "sk-test-xspace",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = api_client.post(
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
    create = api_client.post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "TestCfg",
            "provider": "openai",
            "api_key": "sk-test-conn",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_StubAdapter()):
        r = api_client.post(
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
    create = api_client.post(
        "/api/v1/providers",
        params=_params(a, ua.id),
        json={
            "name": "FailCfg",
            "provider": "openai",
            "api_key": "sk-test-fail",
            "models": ["gpt-4o-mini"],
            "is_default": False,
        },
    )
    assert create.status_code == 201
    pid = create.json()["id"]
    db.commit()

    with patch("app.providers.service.registry.get", return_value=_FailingAdapter()):
        r = api_client.post(
            f"/api/v1/providers/{pid}/test",
            params=_params(a, ua.id),
        )
    assert r.status_code == 200
    out = r.json()
    assert out.get("success") is False
    assert "message" in out
    assert "simulated upstream failure" in (out.get("message") or "")
