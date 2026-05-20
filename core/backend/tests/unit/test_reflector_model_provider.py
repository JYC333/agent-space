"""Tests for the reflector ModelProvider integration.

Covers:
  1. Reflector LLM mode with a configured OpenAI-compatible provider (mocked)
  2. Reflector LLM mode with no provider configured → ReflectorModelProviderMissingError
  3. Static guard: reflector.py does not import anthropic or read anthropic_api_key
  4. provider_type=anthropic → UnsupportedProviderForReflectorError
  5. Non-LLM (pattern) reflector mode still works
"""

from __future__ import annotations

import importlib
import inspect
import ast
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# parents[0] = tests/unit, parents[1] = tests, parents[2] = backend
_REFLECTOR_PY = (
    Path(__file__).resolve().parents[2]
    / "app" / "memory" / "reflector.py"
)
_PROVIDER_CLIENT_PY = (
    Path(__file__).resolve().parents[2]
    / "app" / "memory" / "provider_client.py"
)


# ===========================================================================
# 1. Static source-code guard tests
# ===========================================================================

class TestReflectorSourceGuards:
    """reflector.py must not contain any of the removed Anthropic patterns."""

    def _source(self) -> str:
        return _REFLECTOR_PY.read_text(encoding="utf-8")

    def test_does_not_import_anthropic_package(self):
        """reflector.py must not directly import the anthropic Python package."""
        source = self._source()
        # Allow the string "anthropic" only inside comments or error messages,
        # but not as an import statement.
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [node.module or ""]
                for name in names:
                    assert "anthropic" not in (name or ""), (
                        f"reflector.py imports 'anthropic' package: {ast.dump(node)}"
                    )

    def test_does_not_read_anthropic_api_key_from_settings(self):
        """reflector.py must not reference settings.anthropic_api_key."""
        source = self._source()
        assert "anthropic_api_key" not in source, (
            "reflector.py still references 'anthropic_api_key'. "
            "Remove it — provider config goes through ModelProvider."
        )

    def test_does_not_reference_ANTHROPIC_API_KEY_env_var(self):
        """reflector.py must not reference ANTHROPIC_API_KEY env var."""
        source = self._source()
        assert "ANTHROPIC_API_KEY" not in source, (
            "reflector.py still references 'ANTHROPIC_API_KEY'. "
            "Remove it — credentials flow through Credential.secret_ref."
        )

    def test_does_not_hardcode_claude_model(self):
        """reflector.py must not hardcode any 'claude-*' model string."""
        source = self._source()
        assert "claude-" not in source, (
            "reflector.py has a hardcoded 'claude-*' model reference. "
            "Model selection goes through ModelProvider.default_model."
        )

    def test_uses_provider_client_imports(self):
        """reflector.py must import from .provider_client."""
        source = self._source()
        assert "provider_client" in source, (
            "reflector.py does not import from .provider_client. "
            "LLM mode must route through provider_client."
        )
        assert "resolve_reflector_provider" in source
        assert "call_reflector_llm" in source


# ===========================================================================
# 2. provider_client.py unit tests (no DB needed)
# ===========================================================================

class TestProviderClientGuards:
    """Tests for provider_client.py error classes and type guards."""

    def test_unsupported_provider_anthropic_raises(self):
        """provider_type=anthropic must raise UnsupportedProviderForReflectorError."""
        from app.memory.provider_client import (
            UnsupportedProviderForReflectorError,
            _guard_provider_type,
        )
        with pytest.raises(UnsupportedProviderForReflectorError) as exc_info:
            _guard_provider_type("anthropic")
        assert "CLI-only" in str(exc_info.value) or "not supported" in str(exc_info.value)

    def test_unsupported_provider_unknown_raises(self):
        """Unknown provider_type must raise UnsupportedProviderForReflectorError."""
        from app.memory.provider_client import (
            UnsupportedProviderForReflectorError,
            _guard_provider_type,
        )
        with pytest.raises(UnsupportedProviderForReflectorError):
            _guard_provider_type("totally_unknown_provider")

    def test_supported_provider_types_pass_guard(self):
        """Known openai-compatible provider types must not raise."""
        from app.memory.provider_client import _guard_provider_type
        for pt in ("openai", "openrouter", "ollama", "custom_openai_compatible", "other"):
            _guard_provider_type(pt)  # must not raise

    def test_error_codes_defined(self):
        """Error classes must have the canonical error_code attribute."""
        from app.memory.provider_client import (
            ReflectorModelProviderMissingError,
            UnsupportedProviderForReflectorError,
        )
        assert ReflectorModelProviderMissingError.error_code == "reflector_model_provider_missing"
        assert UnsupportedProviderForReflectorError.error_code == "unsupported_provider_for_reflector"

    def test_build_litellm_model_name_openai(self):
        from app.memory.provider_client import _build_litellm_model_name
        assert _build_litellm_model_name("openai", "gpt-4o") == "gpt-4o"

    def test_build_litellm_model_name_openrouter(self):
        from app.memory.provider_client import _build_litellm_model_name
        assert _build_litellm_model_name("openrouter", "mistral-7b") == "openrouter/mistral-7b"

    def test_build_litellm_model_name_ollama(self):
        from app.memory.provider_client import _build_litellm_model_name
        assert _build_litellm_model_name("ollama", "llama3") == "ollama/llama3"

    def test_build_litellm_model_name_already_qualified(self):
        from app.memory.provider_client import _build_litellm_model_name
        assert _build_litellm_model_name("openrouter", "openai/gpt-4o") == "openai/gpt-4o"

    def test_call_reflector_llm_rejects_anthropic(self):
        """call_reflector_llm must raise for provider_type=anthropic without calling litellm."""
        from app.memory.provider_client import (
            UnsupportedProviderForReflectorError,
            call_reflector_llm,
        )
        with pytest.raises(UnsupportedProviderForReflectorError):
            call_reflector_llm(
                "anthropic",
                None,
                "claude-3-5-sonnet",
                "sk-ant-fake",
                "system",
                "user",
            )

    def test_call_reflector_llm_openai_compatible(self):
        """call_reflector_llm with openai provider calls litellm.completion."""
        from app.memory.provider_client import call_reflector_llm

        mock_choice = MagicMock()
        mock_choice.message.content = '["extracted"]'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.completion", return_value=mock_response) as mock_litellm:
            result = call_reflector_llm(
                "openai",
                None,
                "gpt-4o-mini",
                "sk-test-fake-key",
                "system prompt",
                "user prompt",
            )

        mock_litellm.assert_called_once()
        call_kwargs = mock_litellm.call_args[1]
        # Must use model name directly for openai
        assert call_kwargs["model"] == "gpt-4o-mini"
        # api_key must be passed
        assert call_kwargs["api_key"] == "sk-test-fake-key"
        # api_base must NOT be present when base_url is None
        assert "api_base" not in call_kwargs
        assert result == '["extracted"]'

    def test_call_reflector_llm_passes_base_url(self):
        """When base_url is provided it is passed as api_base to litellm."""
        from app.memory.provider_client import call_reflector_llm

        mock_choice = MagicMock()
        mock_choice.message.content = "[]"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.completion", return_value=mock_response) as mock_litellm:
            call_reflector_llm(
                "custom_openai_compatible",
                "http://my-llm:8080/v1",
                "my-local-model",
                "sk-fake",
                "sys",
                "usr",
            )

        call_kwargs = mock_litellm.call_args[1]
        assert call_kwargs["api_base"] == "http://my-llm:8080/v1"

    def test_call_reflector_llm_api_key_not_in_output(self):
        """The raw API key must not appear in the return value."""
        from app.memory.provider_client import call_reflector_llm

        secret_key = "sk-super-secret-do-not-leak"
        mock_choice = MagicMock()
        mock_choice.message.content = "[]"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.completion", return_value=mock_response):
            result = call_reflector_llm(
                "openai", None, "gpt-4o-mini", secret_key, "sys", "usr"
            )

        assert secret_key not in result


# ===========================================================================
# 3. resolve_reflector_provider — DB-level unit tests
# ===========================================================================

class TestResolveReflectorProvider:
    """Tests for provider_client.resolve_reflector_provider using DB fixtures."""

    def test_raises_when_no_provider_configured(self, db):
        """When reflector_model_provider_id is None, raise ReflectorModelProviderMissingError."""
        from app.memory.provider_client import (
            ReflectorModelProviderMissingError,
            resolve_reflector_provider,
        )
        from app.config import Settings

        fake_settings = Settings(reflector_model_provider_id=None, reflector_model=None)
        with pytest.raises(ReflectorModelProviderMissingError) as exc_info:
            resolve_reflector_provider(db, fake_settings)
        assert "REFLECTOR_MODEL_PROVIDER_ID" in str(exc_info.value)

    def test_raises_when_provider_id_not_in_db(self, db):
        """When reflector_model_provider_id points to a non-existent row, raise."""
        from app.memory.provider_client import (
            ReflectorModelProviderMissingError,
            resolve_reflector_provider,
        )
        from app.config import Settings

        fake_settings = Settings(
            reflector_model_provider_id="01NONEXISTENT000000000000000",
            reflector_model=None,
        )
        with pytest.raises(ReflectorModelProviderMissingError) as exc_info:
            resolve_reflector_provider(db, fake_settings)
        assert "not found" in str(exc_info.value)

    def test_raises_for_disabled_provider(self, db, test_space):
        """Disabled ModelProvider must raise ReflectorModelProviderMissingError."""
        from app.memory.provider_client import (
            ReflectorModelProviderMissingError,
            resolve_reflector_provider,
        )
        from app.config import Settings
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            enabled=False,
        )

        fake_settings = Settings(
            reflector_model_provider_id=mp.id,
            reflector_model=None,
        )
        with pytest.raises(ReflectorModelProviderMissingError) as exc_info:
            resolve_reflector_provider(db, fake_settings)
        assert "disabled" in str(exc_info.value)

    def test_raises_for_anthropic_provider_type(self, db, test_space):
        """ModelProvider with provider_type=anthropic must raise UnsupportedProviderForReflectorError."""
        from app.memory.provider_client import (
            UnsupportedProviderForReflectorError,
            resolve_reflector_provider,
        )
        from app.config import Settings
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="anthropic",
            with_api_key=True,
            enabled=True,
        )

        fake_settings = Settings(
            reflector_model_provider_id=mp.id,
            reflector_model=None,
        )
        with pytest.raises(UnsupportedProviderForReflectorError) as exc_info:
            resolve_reflector_provider(db, fake_settings)
        assert "CLI-only" in str(exc_info.value) or "not supported" in str(exc_info.value)

    def test_resolves_openai_provider_with_credential(self, db, test_space):
        """A configured openai provider with a Credential resolves successfully."""
        from app.memory.provider_client import resolve_reflector_provider
        from app.config import Settings
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=True,
            default_model="gpt-4o-mini",
            enabled=True,
        )
        db.flush()

        fake_settings = Settings(
            reflector_model_provider_id=mp.id,
            reflector_model=None,
        )
        provider_type, base_url, model, api_key = resolve_reflector_provider(
            db, fake_settings
        )

        assert provider_type == "openai"
        assert model == "gpt-4o-mini"
        # api_key must be non-empty and not expose literal key string in repr
        assert api_key
        assert len(api_key) > 0
        # Verify it decrypted to the factory's test key
        assert api_key == "sk-test-factory-key"

    def test_settings_model_override_takes_priority(self, db, test_space):
        """reflector_model setting overrides the provider's default_model."""
        from app.memory.provider_client import resolve_reflector_provider
        from app.config import Settings
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=True,
            default_model="gpt-4o-mini",
            enabled=True,
        )
        db.flush()

        fake_settings = Settings(
            reflector_model_provider_id=mp.id,
            reflector_model="gpt-4o",  # override
        )
        _, _, model, _ = resolve_reflector_provider(db, fake_settings)
        assert model == "gpt-4o"


# ===========================================================================
# 4. MemoryReflector integration (mocked LLM)
# ===========================================================================

def _make_session_and_messages(db, space_id: str, user_id: str, contents: list[str]):
    """Create a Session row + Message rows and return (session_id, messages)."""
    from app.models import Session, Message
    from ulid import ULID

    session_id = str(ULID())
    session = Session(
        id=session_id,
        space_id=space_id,
        user_id=user_id,
        status="active",
    )
    db.add(session)
    db.flush()

    msgs = []
    for content in contents:
        msg = Message(
            id=str(ULID()),
            space_id=space_id,
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=content,
        )
        db.add(msg)
        msgs.append(msg)
    db.flush()
    return session_id, msgs


class TestMemoryReflectorLLMMode:
    """Integration tests for MemoryReflector._reflect_llm with mocked provider_client."""

    def test_llm_mode_calls_provider_and_returns_proposals(self, db, test_space, test_user):
        """With a valid provider mock, reflector creates proposals from LLM response."""
        from app.memory.reflector import MemoryReflector
        from tests.support import factories

        mp = factories.create_test_model_provider(
            db,
            space_id=test_space.id,
            provider_type="openai",
            with_api_key=True,
            default_model="gpt-4o-mini",
            enabled=True,
        )
        db.flush()

        session_id, messages = _make_session_and_messages(
            db,
            test_space.id,
            test_user.id,
            ["I prefer Python over JavaScript for backend work."],
        )

        llm_payload = (
            '[{"memory_type": "preference", '
            '"target_namespace": "user.default.preferences", '
            '"proposed_title": "Prefers Python", '
            '"proposed_content": "User prefers Python.", '
            '"rationale": "Explicitly stated."}]'
        )

        # Patch settings in reflector module and mock both provider_client functions
        with (
            patch("app.memory.reflector.settings") as mock_settings,
            patch("app.memory.reflector.resolve_reflector_provider") as mock_resolve,
            patch("app.memory.reflector.call_reflector_llm", return_value=llm_payload) as mock_call,
        ):
            mock_settings.reflector_mode = "llm"
            mock_settings.reflector_model_provider_id = mp.id
            mock_settings.reflector_model = None
            mock_resolve.return_value = ("openai", None, "gpt-4o-mini", "sk-test-key")

            reflector = MemoryReflector(db)
            proposals = reflector._reflect_llm(
                messages, session_id, test_space.id, test_user.id, None
            )

        assert len(proposals) == 1
        assert proposals[0].proposed_title == "Prefers Python"
        mock_resolve.assert_called_once()
        mock_call.assert_called_once()
        # api_key must have been passed positionally; check it was "sk-test-key"
        call_args = mock_call.call_args
        assert "sk-test-key" in call_args[0]

    def test_llm_mode_missing_provider_raises(self, db, test_space, test_user):
        """When provider is missing, reflector raises ReflectorModelProviderMissingError."""
        from app.memory.reflector import MemoryReflector
        from app.memory.provider_client import ReflectorModelProviderMissingError

        session_id, messages = _make_session_and_messages(
            db,
            test_space.id,
            test_user.id,
            ["Some user message"],
        )

        with (
            patch("app.memory.reflector.settings") as mock_settings,
            patch(
                "app.memory.reflector.resolve_reflector_provider",
                side_effect=ReflectorModelProviderMissingError("no provider"),
            ),
        ):
            mock_settings.reflector_mode = "llm"
            mock_settings.reflector_model_provider_id = None

            reflector = MemoryReflector(db)
            with pytest.raises(ReflectorModelProviderMissingError):
                reflector._reflect_llm(
                    messages, session_id, test_space.id, test_user.id, None
                )

    def test_llm_mode_does_not_read_anthropic_api_key(self, db, test_space, test_user):
        """Verify reflector never accesses settings.anthropic_api_key in llm mode."""
        from app.memory.reflector import MemoryReflector
        from app.memory.provider_client import ReflectorModelProviderMissingError

        session_id, messages = _make_session_and_messages(
            db,
            test_space.id,
            test_user.id,
            ["Another message"],
        )

        accessed_attrs: list[str] = []

        class TrackingSettings:
            reflector_mode = "llm"
            reflector_model_provider_id = None

            def __getattr__(self, name: str):
                accessed_attrs.append(name)
                if name == "reflector_model_provider_id":
                    return None
                raise AttributeError(name)

        with (
            patch("app.memory.reflector.settings", TrackingSettings()),
            patch(
                "app.memory.reflector.resolve_reflector_provider",
                side_effect=ReflectorModelProviderMissingError("no provider"),
            ),
        ):
            reflector = MemoryReflector(db)
            with pytest.raises(ReflectorModelProviderMissingError):
                reflector._reflect_llm(
                    messages, session_id, test_space.id, test_user.id, None
                )

        assert "anthropic_api_key" not in accessed_attrs, (
            f"reflector accessed settings.anthropic_api_key! Accessed: {accessed_attrs}"
        )


# ===========================================================================
# 5. Pattern mode regression (must still work unchanged)
# ===========================================================================

class TestMemoryReflectorPatternModeRegression:
    """Non-LLM reflector mode must be completely unaffected by this refactor."""

    def test_pattern_mode_creates_preference_proposal(self, db, test_space, test_user):
        from app.memory.reflector import MemoryReflector

        session_id, msgs = _make_session_and_messages(
            db,
            test_space.id,
            test_user.id,
            ["I prefer dark mode in all my editors."],
        )

        reflector = MemoryReflector(db)
        proposals = reflector._reflect_pattern(
            msgs, session_id, test_space.id, test_user.id, None
        )

        assert len(proposals) == 1
        assert proposals[0].memory_type == "preference"

    def test_pattern_mode_skips_non_signal_messages(self, db, test_space, test_user):
        from app.memory.reflector import MemoryReflector

        session_id, msgs = _make_session_and_messages(
            db,
            test_space.id,
            test_user.id,
            ["The weather today is fine."],
        )

        reflector = MemoryReflector(db)
        proposals = reflector._reflect_pattern(
            msgs, session_id, test_space.id, test_user.id, None
        )

        assert proposals == []

    def test_reflect_dispatches_to_pattern_when_mode_is_pattern(self, db, test_space, test_user):
        """reflect() must call _reflect_pattern when reflector_mode != 'llm'."""
        from app.memory.reflector import MemoryReflector

        session_id, _ = _make_session_and_messages(
            db, test_space.id, test_user.id, []
        )

        with patch("app.memory.reflector.settings") as mock_settings:
            mock_settings.reflector_mode = "pattern"
            reflector = MemoryReflector(db)
            with patch.object(reflector, "_reflect_pattern", return_value=[]) as mock_pattern:
                with patch.object(reflector, "_reflect_llm", return_value=[]) as mock_llm:
                    reflector.reflect(session_id, test_space.id, test_user.id)
            mock_pattern.assert_called_once()
            mock_llm.assert_not_called()
