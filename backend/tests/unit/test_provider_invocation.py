"""Tests for the shared provider invocation primitive (providers/invocation.py).

Covers the model-name builder retained for Python-owned helpers plus the fixed
control-plane forwarding path used by Python callers:
  1. build_litellm_model_name qualification (incl. anthropic — ADR 0010)
  2. resolve_usable_provider validation (missing / disabled / unsupported)
  3. complete_text: service-authenticated control-plane forwarding, no litellm
"""
from __future__ import annotations

from unittest.mock import patch

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


class TestCompleteText:
    def test_control_plane_authority_forwards_without_litellm(self, db, test_space, monkeypatch):
        from app.providers.invocation import complete_text
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=False,
            default_model="gpt-4o-mini",
            enabled=True,
        )
        calls = []

        def _fake_complete(**payload):
            calls.append(payload)
            return {"text": "from-ts", "model": "gpt-4o-mini", "usage": {"total_tokens": 3}}

        monkeypatch.setattr(
            "app.providers.invocation.complete_text_via_control_plane",
            _fake_complete,
        )

        with patch("litellm.completion") as mock_litellm:
            result = complete_text(
                db,
                provider_id=mp.id,
                model=None,
                system="sys",
                user="usr",
            )

        mock_litellm.assert_not_called()
        assert result.text == "from-ts"
        assert result.usage == {"total_tokens": 3}
        assert calls == [
            {
                "space_id": test_space.id,
                "provider_id": mp.id,
                "model": None,
                "system": "sys",
                "user": "usr",
                "max_tokens": 2048,
                "task": None,
            }
        ]

    def test_model_override_is_forwarded_to_control_plane(self, db, test_space, monkeypatch):
        from app.providers.invocation import complete_text
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=False,
            default_model="gpt-4o-mini",
            enabled=True,
        )
        calls = []

        def _fake_complete(**payload):
            calls.append(payload)
            return {"text": "from-ts", "model": payload["model"], "usage": None}

        monkeypatch.setattr(
            "app.providers.invocation.complete_text_via_control_plane",
            _fake_complete,
        )

        with patch("litellm.completion") as mock_litellm:
            result = complete_text(db, provider_id=mp.id, model="gpt-4o", system="s", user="u")

        mock_litellm.assert_not_called()
        assert result.model == "gpt-4o"
        assert calls[0]["model"] == "gpt-4o"

    def test_task_is_forwarded_to_control_plane(self, db, test_space, monkeypatch):
        from app.providers.invocation import complete_text
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=False,
            enabled=True,
        )
        calls = []

        def _fake_complete(**payload):
            calls.append(payload)
            return {"text": "from-ts", "model": "gpt-4o-mini", "usage": None}

        monkeypatch.setattr(
            "app.providers.invocation.complete_text_via_control_plane",
            _fake_complete,
        )

        complete_text(db, provider_id=mp.id, model=None, system="s", user="u", task="reflector")

        assert calls[0]["task"] == "reflector"

    def test_missing_provider_still_fails_before_forward(self, db, monkeypatch):
        from app.providers.invocation import ProviderUnavailableError, complete_text

        monkeypatch.setattr(
            "app.providers.invocation.complete_text_via_control_plane",
            lambda **_payload: {"text": "unexpected"},
        )

        with pytest.raises(ProviderUnavailableError):
            complete_text(
                db,
                provider_id="01NONEXISTENT000000000000000",
                model=None,
                system="s",
                user="u",
            )
