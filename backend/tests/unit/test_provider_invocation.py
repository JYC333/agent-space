"""Tests for the shared provider invocation primitive (providers/invocation.py).

Covers the single litellm call site and model-name builder used by both the memory
reflector path and the model_api runtime adapter:
  1. build_litellm_model_name qualification (incl. anthropic — ADR 0010)
  2. resolve_usable_provider validation (missing / disabled / unsupported)
  3. complete_text: litellm call, base_url, key isolation, anthropic in-process
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. build_litellm_model_name
# ===========================================================================

class TestBuildLitellmModelName:
    def test_openai_qualified(self):
        """openai → 'openai/<model>' so litellm selects the OpenAI handler."""
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("openai", "gpt-4o") == "openai/gpt-4o"

    def test_openai_compatible_uses_openai_prefix(self):
        """custom_openai_compatible / other → 'openai/<model>' (+ api_base routes it)."""
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("custom_openai_compatible", "MiniMax-M3") == "openai/MiniMax-M3"
        assert build_litellm_model_name("other", "some-model") == "openai/some-model"

    def test_anthropic_qualified(self):
        """Anthropic models are qualified as 'anthropic/<model>' (ADR 0010)."""
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("anthropic", "claude-3-5-sonnet") == "anthropic/claude-3-5-sonnet"

    def test_openrouter_qualified(self):
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("openrouter", "mistral-7b") == "openrouter/mistral-7b"

    def test_ollama_qualified(self):
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("ollama", "llama3") == "ollama/llama3"

    def test_already_qualified_passthrough(self):
        from app.providers.invocation import build_litellm_model_name
        assert build_litellm_model_name("openrouter", "openai/gpt-4o") == "openai/gpt-4o"


# ===========================================================================
# 2. Error classes + resolve_usable_provider
# ===========================================================================

class TestProviderValidation:
    def test_error_codes_defined(self):
        from app.providers.invocation import ProviderUnavailableError, UnsupportedProviderError
        assert ProviderUnavailableError.error_code == "provider_unavailable"
        assert UnsupportedProviderError.error_code == "unsupported_provider"

    def test_missing_provider_raises_unavailable(self, db):
        from app.providers.invocation import ProviderUnavailableError, resolve_usable_provider
        with pytest.raises(ProviderUnavailableError):
            resolve_usable_provider(db, "01NONEXISTENT000000000000000")

    def test_disabled_provider_raises_unavailable(self, db, test_space):
        from app.providers.invocation import ProviderUnavailableError, resolve_usable_provider
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="openai", enabled=False
        )
        with pytest.raises(ProviderUnavailableError):
            resolve_usable_provider(db, mp.id)

    def test_supported_types_resolve(self, db, test_space):
        from app.providers.invocation import resolve_usable_provider
        from tests.support import factories
        for pt in ("openai", "anthropic", "openrouter", "ollama", "custom_openai_compatible", "other"):
            mp = factories.create_test_model_provider(
                db, space_id=test_space.id, provider_type=pt, with_api_key=True, enabled=True
            )
            row = resolve_usable_provider(db, mp.id)
            assert row.provider_type == pt


# ===========================================================================
# 3. complete_text
# ===========================================================================

def _mock_litellm_response(content: str):
    mock_choice = MagicMock()
    mock_choice.message.content = content
    resp = MagicMock()
    resp.choices = [mock_choice]
    resp.usage = None
    return resp


class TestCompleteText:
    def test_openai_calls_litellm(self, db, test_space):
        from app.providers.invocation import complete_text
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="openai",
            with_api_key=True, default_model="gpt-4o-mini", enabled=True,
        )
        with patch("litellm.completion", return_value=_mock_litellm_response('["ok"]')) as mock_litellm:
            result = complete_text(db, provider_id=mp.id, model=None, system="sys", user="usr")
        kwargs = mock_litellm.call_args[1]
        assert kwargs["model"] == "openai/gpt-4o-mini"  # openai → openai/<model>
        assert kwargs["api_key"] == "sk-test-factory-key"
        assert "api_base" not in kwargs
        assert result.text == '["ok"]'
        assert result.model == "gpt-4o-mini"

    def test_anthropic_in_process_qualified_model(self, db, test_space):
        """provider_type=anthropic resolves in-process (ADR 0010) and qualifies the model."""
        from app.providers.invocation import complete_text
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="anthropic",
            with_api_key=True, default_model="claude-3-5-sonnet-latest", enabled=True,
        )
        with patch("litellm.completion", return_value=_mock_litellm_response("hi")) as mock_litellm:
            result = complete_text(db, provider_id=mp.id, model=None, system="sys", user="usr")
        assert mock_litellm.call_args[1]["model"] == "anthropic/claude-3-5-sonnet-latest"
        assert result.text == "hi"

    def test_base_url_passed_as_api_base(self, db, test_space):
        from app.providers.invocation import complete_text
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="custom_openai_compatible",
            with_api_key=True, default_model="my-local-model",
            base_url="http://my-llm:8080/v1", enabled=True,
        )
        with patch("litellm.completion", return_value=_mock_litellm_response("[]")) as mock_litellm:
            complete_text(db, provider_id=mp.id, model=None, system="s", user="u")
        assert mock_litellm.call_args[1]["api_base"] == "http://my-llm:8080/v1"

    def test_api_key_not_in_output(self, db, test_space):
        from app.providers.invocation import complete_text
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="openai",
            with_api_key=True, default_model="gpt-4o-mini", enabled=True,
        )
        with patch("litellm.completion", return_value=_mock_litellm_response("[]")):
            result = complete_text(db, provider_id=mp.id, model=None, system="s", user="u")
        assert "sk-test-factory-key" not in result.text

    def test_model_override_takes_priority(self, db, test_space):
        from app.providers.invocation import complete_text
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="openai",
            with_api_key=True, default_model="gpt-4o-mini", enabled=True,
        )
        with patch("litellm.completion", return_value=_mock_litellm_response("[]")) as mock_litellm:
            result = complete_text(db, provider_id=mp.id, model="gpt-4o", system="s", user="u")
        assert mock_litellm.call_args[1]["model"] == "openai/gpt-4o"
        assert result.model == "gpt-4o"

    def test_unsupported_provider_raises_without_litellm(self, db, test_space):
        from app.providers.invocation import UnsupportedProviderError, complete_text
        from app.models import ModelProvider
        from tests.support import factories
        mp = factories.create_test_model_provider(
            db, space_id=test_space.id, provider_type="openai", with_api_key=True, enabled=True
        )
        # Force an unsupported provider_type directly on the row
        db.query(ModelProvider).filter(ModelProvider.id == mp.id).update(
            {"provider_type": "totally_unknown_provider"}
        )
        db.flush()
        with patch("litellm.completion") as mock_litellm:
            with pytest.raises(UnsupportedProviderError):
                complete_text(db, provider_id=mp.id, model=None, system="s", user="u")
        mock_litellm.assert_not_called()
