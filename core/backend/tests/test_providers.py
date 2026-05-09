"""
Tests for the providers module — ModelService, LiteLLMProvider, and API routes.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.providers.models import (
    ChatRequest, ChatResponse, ChatMessage,
    ProviderConfigCreate, ProviderConfigOut,
    ConnectionTestResult,
)
from app.providers.service import ModelService
from app.providers.litellm_provider import LiteLLMProvider
from app.providers.registry import ProviderRegistry, registry


# ---------------------------------------------------------------------------
# ModelService — unit tests (no DB, no network)
# ---------------------------------------------------------------------------

class TestProviderSchemas:
    """Test that schema round-trips are correct."""

    def test_chat_request_build(self):
        req = ChatRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="hello")],
            temperature=0.7,
            max_tokens=100,
        )
        assert req.model == "gpt-4o"
        assert len(req.messages) == 1
        assert req.messages[0].content == "hello"
        assert req.temperature == 0.7
        assert req.max_tokens == 100

    def test_chat_response_structure(self):
        resp = ChatResponse(
            content="hello back",
            provider="openai",
            model="gpt-4o",
            usage={"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        )
        assert resp.content == "hello back"
        assert resp.provider == "openai"
        assert resp.usage["total_tokens"] == 12

    def test_provider_config_create_fields(self):
        cfg = ProviderConfigCreate(
            name="test provider",
            provider="openai",
            api_key="sk-test",
            models=["gpt-4o"],
            api_base=None,
            is_default=True,
        )
        assert cfg.name == "test provider"
        assert cfg.provider == "openai"
        assert cfg.api_key == "sk-test"
        assert cfg.models == ["gpt-4o"]
        assert cfg.is_default is True

    def test_test_connection_result(self):
        result = ConnectionTestResult(success=True, message="ok", model="gpt-4o")
        assert result.success is True
        assert result.model == "gpt-4o"


class TestProviderRegistry:
    """Test the registry and adapter pattern."""

    def test_register_and_get(self):
        reg = ProviderRegistry()
        adapter = MagicMock()
        reg.register("test", adapter)
        assert reg.get("test") is adapter
        assert reg.get("nonexistent") is None

    def test_global_registry_has_litellm(self):
        assert registry.get("litellm") is not None
        assert isinstance(registry.get("litellm"), LiteLLMProvider)


class TestLiteLLMProvider:
    """Test LiteLLMProvider.translate_model logic via complete()."""

    @pytest.mark.asyncio
    async def test_complete_builds_correct_params(self):
        provider = LiteLLMProvider()
        request = ChatRequest(
            model="openai/gpt-4o",
            messages=[ChatMessage(role="user", content="say hi")],
            system="you are helpful",
            temperature=0.5,
            max_tokens=50,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hi"
        mock_response.model = "openai/gpt-4o"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            response = await provider.complete("sk-test-key", None, request)

            mock_litellm.acompletion.assert_called_once()
            call_kwargs = mock_litellm.acompletion.call_args[1]
            assert call_kwargs["model"] == "openai/gpt-4o"
            assert call_kwargs["api_key"] == "sk-test-key"
            assert len(call_kwargs["messages"]) == 2  # system + user
            assert call_kwargs["messages"][0]["role"] == "system"
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 50

            assert response.content == "hi"
            assert response.model == "openai/gpt-4o"
            assert response.usage["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_complete_with_api_base(self):
        provider = LiteLLMProvider()
        request = ChatRequest(
            model="azure/gpt-4o",
            messages=[ChatMessage(role="user", content="hi")],
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hello"
        mock_response.model = "azure/gpt-4o"
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 3
        mock_response.usage.total_tokens = 8

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            await provider.complete("key", "https://my-resource.openai.azure.com", request)

            call_kwargs = mock_litellm.acompletion.call_args[1]
            assert call_kwargs["api_base"] == "https://my-resource.openai.azure.com"

    @pytest.mark.asyncio
    async def test_complete_litellm_error_raises(self):
        provider = LiteLLMProvider()
        request = ChatRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="hi")],
        )

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("litellm error"))

            with pytest.raises(Exception, match="litellm error"):
                await provider.complete("key", None, request)


# ---------------------------------------------------------------------------
# API route tests via test client
# ---------------------------------------------------------------------------

class TestProviderCatalogRoute:
    def test_catalog_returns_info(self, client):
        resp = client.get("/api/v1/providers/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "litellm"
        assert "description" in data
        assert "model_hint" in data


class TestProviderCRUDRoutes:
    def test_create_and_list_provider(self, client):
        # Create
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "Test OpenAI",
                "provider": "openai/gpt-4o",
                "api_key": "sk-test123",
                "models": ["gpt-4o", "gpt-4o-mini"],
                "is_default": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test OpenAI"
        assert data["provider"] == "openai/gpt-4o"
        assert data["is_default"] is True
        assert "api_key" not in data  # never exposed
        provider_id = data["id"]

        # List
        resp = client.get("/api/v1/providers")
        assert resp.status_code == 200
        configs = resp.json()
        assert any(c["id"] == provider_id for c in configs)

        # Get single
        resp = client.get(f"/api/v1/providers/{provider_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test OpenAI"

        # Update
        resp = client.put(
            f"/api/v1/providers/{provider_id}",
            json={"name": "Updated Name", "models": ["gpt-4o"]},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["models"] == ["gpt-4o"]

        # Delete (soft)
        resp = client.delete(f"/api/v1/providers/{provider_id}")
        assert resp.status_code == 204

        # Confirm deleted — GET returns 404 for soft-deleted configs
        resp = client.get(f"/api/v1/providers/{provider_id}")
        assert resp.status_code == 404

    def test_create_provider_without_models_fails(self, client):
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "Bad",
                "provider": "openai",
                "api_key": "sk-test",
                "models": [],
            },
        )
        assert resp.status_code == 400

    def test_create_provider_arbitrary_provider_id(self, client):
        """Any litellm model name works — no catalog validation."""
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "DeepSeek",
                "provider": "deepseek/deepseek-chat",
                "api_key": "sk-test",
                "models": ["deepseek-chat"],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["provider"] == "deepseek/deepseek-chat"


class TestProviderChatRoute:
    def test_chat_without_default_provider_fails(self, client):
        """No default provider configured → 404."""
        resp = client.post(
            "/api/v1/providers/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        # Should get 404 because no default provider exists
        assert resp.status_code == 404

    def test_chat_with_provider_id(self, client):
        """Create provider then chat with it."""
        # Create provider
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "Test",
                "provider": "openai",
                "api_key": "sk-test",
                "models": ["gpt-4o"],
            },
        )
        assert resp.status_code == 201
        provider_id = resp.json()["id"]

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "hello"
            mock_response.model = "gpt-4o"
            mock_response.usage.prompt_tokens = 5
            mock_response.usage.completion_tokens = 2
            mock_response.usage.total_tokens = 7
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            resp = client.post(
                "/api/v1/providers/chat",
                json={
                    "provider_id": provider_id,
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "say hello"}],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["content"] == "hello"
            assert data["model"] == "gpt-4o"


class TestProviderTestConnection:
    def test_test_connection_success(self, client):
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "Test",
                "provider": "openai",
                "api_key": "sk-test",
                "models": ["gpt-4o"],
            },
        )
        assert resp.status_code == 201
        provider_id = resp.json()["id"]

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "hi"
            mock_response.model = "gpt-4o"
            mock_response.usage.prompt_tokens = 3
            mock_response.usage.completion_tokens = 2
            mock_response.usage.total_tokens = 5
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            resp = client.post(f"/api/v1/providers/{provider_id}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["model"] == "gpt-4o"

    def test_test_connection_failure(self, client):
        resp = client.post(
            "/api/v1/providers",
            json={
                "name": "Bad",
                "provider": "openai",
                "api_key": "sk-test",
                "models": ["gpt-4o"],
            },
        )
        assert resp.status_code == 201
        provider_id = resp.json()["id"]

        with patch("app.providers.litellm_provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("connection refused"))

            resp = client.post(f"/api/v1/providers/{provider_id}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is False
            assert "connection refused" in data["message"]
