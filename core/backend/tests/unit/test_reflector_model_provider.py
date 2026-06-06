"""Tests for the reflector ModelProvider integration.

Covers:
  1. Static guard: reflector.py does not import anthropic package or read anthropic_api_key
  2. resolve_reflector_provider_id: settings → (provider_id, model_override)
  3. MemoryReflector LLM mode (mocked complete_text)
  4. Non-LLM (pattern) reflector mode still works

The shared invocation primitive (complete_text, build_litellm_model_name,
resolve_usable_provider) is tested in test_provider_invocation.py.
"""

from __future__ import annotations
import uuid

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

# parents[0] = tests/unit, parents[1] = tests, parents[2] = backend
_REFLECTOR_PY = Path(__file__).resolve().parents[2] / "app" / "memory" / "reflector.py"


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

    def test_routes_through_shared_invocation(self):
        """reflector.py must resolve via provider_client and call the shared complete_text."""
        source = self._source()
        assert "resolve_reflector_provider_id" in source
        assert "complete_text" in source


# ===========================================================================
# 2. resolve_reflector_provider_id — settings-only resolution
# ===========================================================================

class TestResolveReflectorProviderId:
    def test_error_code_defined(self):
        from app.memory.provider_client import ReflectorModelProviderMissingError
        assert ReflectorModelProviderMissingError.error_code == "reflector_model_provider_missing"

    def test_raises_when_no_provider_configured(self):
        from app.memory.provider_client import (
            ReflectorModelProviderMissingError,
            resolve_reflector_provider_id,
        )
        from app.config import Settings

        settings = Settings(reflector_model_provider_id=None, reflector_model=None)
        with pytest.raises(ReflectorModelProviderMissingError) as exc_info:
            resolve_reflector_provider_id(settings)
        assert "REFLECTOR_MODEL_PROVIDER_ID" in str(exc_info.value)

    def test_returns_provider_id(self):
        from app.memory.provider_client import resolve_reflector_provider_id
        from app.config import Settings

        settings = Settings(reflector_model_provider_id="prov-123", reflector_model=None)
        provider_id, model = resolve_reflector_provider_id(settings)
        assert provider_id == "prov-123"
        assert model is None

    def test_returns_model_override(self):
        from app.memory.provider_client import resolve_reflector_provider_id
        from app.config import Settings

        settings = Settings(reflector_model_provider_id="prov-123", reflector_model="gpt-4o")
        _, model = resolve_reflector_provider_id(settings)
        assert model == "gpt-4o"


# ===========================================================================
# 3. MemoryReflector integration (mocked invocation)
# ===========================================================================

def _make_session_and_messages(db, space_id: str, user_id: str, contents: list[str]):
    """Create a Session row + Message rows and return (session_id, messages)."""
    from app.models import Session, Message

    session_id = str(uuid.uuid4())
    session = Session(id=session_id, space_id=space_id, user_id=user_id, status="active")
    db.add(session)
    db.flush()

    msgs = []
    for content in contents:
        msg = Message(
            id=str(uuid.uuid4()),
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
    """Integration tests for MemoryReflector._reflect_llm with mocked invocation."""

    def test_llm_mode_calls_provider_and_returns_proposals(self, db, test_space, test_user):
        """With a valid provider mock, reflector creates proposals from LLM response."""
        from app.memory.reflector import MemoryReflector
        from app.providers.invocation import CompletionResult

        session_id, messages = _make_session_and_messages(
            db, test_space.id, test_user.id,
            ["I prefer Python over JavaScript for backend work."],
        )

        llm_payload = (
            '[{"memory_type": "preference", '
            '"target_namespace": "user.default.preferences", '
            '"proposed_title": "Prefers Python", '
            '"proposed_content": "User prefers Python.", '
            '"rationale": "Explicitly stated."}]'
        )

        with (
            patch("app.memory.reflector.settings") as mock_settings,
            patch("app.memory.reflector.resolve_reflector_provider_id", return_value=("prov-1", None)) as mock_resolve,
            patch(
                "app.memory.reflector.complete_text",
                return_value=CompletionResult(text=llm_payload, model="gpt-4o-mini"),
            ) as mock_call,
        ):
            mock_settings.reflector_mode = "llm"
            mock_settings.reflector_model_provider_id = "prov-1"
            mock_settings.reflector_model = None

            reflector = MemoryReflector(db)
            proposals = reflector._reflect_llm(
                messages, session_id, test_space.id, test_user.id, None
            )

        assert len(proposals) == 1
        assert proposals[0].proposed_title == "Prefers Python"
        mock_resolve.assert_called_once()
        mock_call.assert_called_once()
        # complete_text must receive the resolved provider_id (not an api key).
        assert mock_call.call_args.kwargs["provider_id"] == "prov-1"

    def test_llm_mode_missing_provider_raises(self, db, test_space, test_user):
        """When provider is missing, reflector raises ReflectorModelProviderMissingError."""
        from app.memory.reflector import MemoryReflector
        from app.memory.provider_client import ReflectorModelProviderMissingError

        session_id, messages = _make_session_and_messages(
            db, test_space.id, test_user.id, ["Some user message"],
        )

        with (
            patch("app.memory.reflector.settings") as mock_settings,
            patch(
                "app.memory.reflector.resolve_reflector_provider_id",
                side_effect=ReflectorModelProviderMissingError("no provider"),
            ),
        ):
            mock_settings.reflector_mode = "llm"
            mock_settings.reflector_model_provider_id = None

            reflector = MemoryReflector(db)
            with pytest.raises(ReflectorModelProviderMissingError):
                reflector._reflect_llm(messages, session_id, test_space.id, test_user.id, None)

    def test_llm_mode_does_not_read_anthropic_api_key(self, db, test_space, test_user):
        """Verify reflector never accesses settings.anthropic_api_key in llm mode."""
        from app.memory.reflector import MemoryReflector
        from app.memory.provider_client import ReflectorModelProviderMissingError

        session_id, messages = _make_session_and_messages(
            db, test_space.id, test_user.id, ["Another message"],
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
                "app.memory.reflector.resolve_reflector_provider_id",
                side_effect=ReflectorModelProviderMissingError("no provider"),
            ),
        ):
            reflector = MemoryReflector(db)
            with pytest.raises(ReflectorModelProviderMissingError):
                reflector._reflect_llm(messages, session_id, test_space.id, test_user.id, None)

        assert "anthropic_api_key" not in accessed_attrs, (
            f"reflector accessed settings.anthropic_api_key! Accessed: {accessed_attrs}"
        )


# ===========================================================================
# 4. Pattern mode regression (must still work unchanged)
# ===========================================================================

class TestMemoryReflectorPatternModeRegression:
    """Non-LLM reflector mode must be completely unaffected by this refactor."""

    def test_pattern_mode_creates_preference_proposal(self, db, test_space, test_user):
        from app.memory.reflector import MemoryReflector

        session_id, msgs = _make_session_and_messages(
            db, test_space.id, test_user.id, ["I prefer dark mode in all my editors."],
        )

        reflector = MemoryReflector(db)
        proposals = reflector._reflect_pattern(msgs, session_id, test_space.id, test_user.id, None)

        assert len(proposals) == 1
        assert proposals[0].memory_type == "preference"

    def test_pattern_mode_skips_non_signal_messages(self, db, test_space, test_user):
        from app.memory.reflector import MemoryReflector

        session_id, msgs = _make_session_and_messages(
            db, test_space.id, test_user.id, ["The weather today is fine."],
        )

        reflector = MemoryReflector(db)
        proposals = reflector._reflect_pattern(msgs, session_id, test_space.id, test_user.id, None)

        assert proposals == []

    def test_reflect_dispatches_to_pattern_when_mode_is_pattern(self, db, test_space, test_user):
        """reflect() must call _reflect_pattern when reflector_mode != 'llm'."""
        from app.memory.reflector import MemoryReflector

        session_id, _ = _make_session_and_messages(db, test_space.id, test_user.id, [])

        with patch("app.memory.reflector.settings") as mock_settings:
            mock_settings.reflector_mode = "pattern"
            reflector = MemoryReflector(db)
            with patch.object(reflector, "_reflect_pattern", return_value=[]) as mock_pattern:
                with patch.object(reflector, "_reflect_llm", return_value=[]) as mock_llm:
                    reflector.reflect(session_id, test_space.id, test_user.id)
            mock_pattern.assert_called_once()
            mock_llm.assert_not_called()
