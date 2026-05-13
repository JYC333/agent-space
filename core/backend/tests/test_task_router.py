"""
Tests for TaskRouter, TaskClassification, and AnthropicAPIAdapter.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.router.task_router import (
    TaskRouter, TaskClassification,
    _CLI_ADAPTERS, _LIGHTWEIGHT_TASK_TYPES, _HEAVY_TASK_TYPES,
)
from app.agents.api_adapter import AnthropicAPIAdapter


# ---------------------------------------------------------------------------
# TaskClassification.needs_cli
# ---------------------------------------------------------------------------

def test_needs_cli_false_for_generic_task():
    c = TaskClassification(task_type="generic")
    assert c.needs_cli is False


def test_needs_cli_false_for_lightweight_task_types():
    for t in _LIGHTWEIGHT_TASK_TYPES:
        c = TaskClassification(task_type=t)
        assert c.needs_cli is False, f"Expected {t} to be lightweight"


def test_needs_cli_true_for_heavy_task_types():
    for t in _HEAVY_TASK_TYPES:
        c = TaskClassification(task_type=t)
        assert c.needs_cli is True, f"Expected {t} to need CLI"


def test_needs_cli_true_when_requires_filesystem():
    c = TaskClassification(task_type="summarize", requires_filesystem=True)
    assert c.needs_cli is True


def test_needs_cli_true_when_requires_terminal():
    c = TaskClassification(requires_terminal=True)
    assert c.needs_cli is True


def test_needs_cli_true_when_requires_git():
    c = TaskClassification(requires_git=True)
    assert c.needs_cli is True


def test_needs_cli_true_when_requires_long_reasoning():
    c = TaskClassification(requires_long_reasoning=True)
    assert c.needs_cli is True


def test_needs_cli_false_when_all_flags_false():
    c = TaskClassification(
        task_type="summarize",
        requires_filesystem=False,
        requires_terminal=False,
        requires_git=False,
        requires_long_reasoning=False,
    )
    assert c.needs_cli is False


# ---------------------------------------------------------------------------
# TaskRouter.resolve_adapter
# ---------------------------------------------------------------------------

router = TaskRouter()


def test_resolve_keeps_echo_unchanged():
    c = TaskClassification(task_type="summarize")
    assert router.resolve_adapter("echo", c) == "echo"


def test_resolve_keeps_anthropic_api_unchanged():
    c = TaskClassification(task_type="code_modify", requires_git=True)
    assert router.resolve_adapter("anthropic_api", c) == "anthropic_api"


def test_resolve_downgrades_claude_code_for_lightweight_task():
    c = TaskClassification(task_type="summarize")
    assert router.resolve_adapter("claude_code", c) == "anthropic_api"


def test_resolve_keeps_claude_code_when_git_required():
    c = TaskClassification(task_type="summarize", requires_git=True)
    assert router.resolve_adapter("claude_code", c) == "claude_code"


def test_resolve_keeps_claude_code_for_heavy_task():
    c = TaskClassification(task_type="code_modify")
    assert router.resolve_adapter("claude_code", c) == "claude_code"


def test_resolve_downgrades_codex_cli_for_lightweight():
    c = TaskClassification(task_type="classify")
    assert router.resolve_adapter("codex_cli", c) == "anthropic_api"


def test_resolve_keeps_codex_cli_when_filesystem_required():
    c = TaskClassification(requires_filesystem=True)
    assert router.resolve_adapter("codex_cli", c) == "codex_cli"


def test_resolve_claude_cli_synonym_downgraded():
    c = TaskClassification(task_type="digest")
    assert router.resolve_adapter("claude_cli", c) == "anthropic_api"


# ---------------------------------------------------------------------------
# TaskRouter.classify_from_request
# ---------------------------------------------------------------------------

def test_classify_from_request_defaults():
    c = router.classify_from_request(
        task_type=None,
        risk_level="medium",
        requires_filesystem=False,
        requires_terminal=False,
        requires_git=False,
        requires_long_reasoning=False,
    )
    assert c.task_type == "generic"
    assert c.risk_level == "medium"
    assert c.needs_cli is False


def test_classify_from_request_heavy():
    c = router.classify_from_request(
        task_type="migration",
        risk_level="high",
        requires_filesystem=True,
        requires_terminal=True,
        requires_git=True,
        requires_long_reasoning=False,
    )
    assert c.needs_cli is True


# ---------------------------------------------------------------------------
# RunRequest routing fields integrate with AgentService
# ---------------------------------------------------------------------------

def test_agent_service_resolves_adapter_via_task_router(db):
    """AgentService._resolve_adapter_type uses TaskRouter to downgrade CLI → API."""
    from app.agents.agent_service import AgentService
    from app.schemas import RunRequest

    svc = AgentService(db)
    req = RunRequest(
        prompt="Summarize this session",
        adapter_type="claude_code",
        task_type="summarize",
        requires_filesystem=False,
        requires_terminal=False,
        requires_git=False,
        requires_long_reasoning=False,
    )
    assert svc._resolve_adapter_type(req) == "anthropic_api"


def test_agent_service_keeps_cli_when_git_required(db):
    from app.agents.agent_service import AgentService
    from app.schemas import RunRequest

    svc = AgentService(db)
    req = RunRequest(
        prompt="Fix the failing tests",
        adapter_type="claude_code",
        task_type="test_fix",
        requires_git=True,
    )
    assert svc._resolve_adapter_type(req) == "claude_code"


# ---------------------------------------------------------------------------
# AnthropicAPIAdapter
# ---------------------------------------------------------------------------

def test_api_adapter_type():
    assert AnthropicAPIAdapter().adapter_type == "anthropic_api"


def test_api_adapter_get_capabilities():
    caps = AnthropicAPIAdapter().get_capabilities()
    assert caps.supports_headless_run is True
    assert caps.supports_interactive_run is False
    assert caps.supports_model_override is True


def test_api_adapter_unavailable_without_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    adapter = AnthropicAPIAdapter()
    assert adapter.is_available() is False


def test_api_adapter_unavailable_without_package(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "anthropic", None)
    adapter = AnthropicAPIAdapter()
    assert adapter.is_available() is False


def test_api_adapter_run_returns_error_without_package(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "anthropic", None)
    adapter = AnthropicAPIAdapter()
    result = adapter.run(prompt="hello", context={})
    assert result.success is False
    assert "anthropic" in result.error.lower()


def test_api_adapter_run_success(monkeypatch):
    mock_content = MagicMock()
    mock_content.text = "Here is the summary."
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.agents.api_adapter.AnthropicAPIAdapter.is_available", lambda self: True)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    adapter = AnthropicAPIAdapter(model="claude-haiku-4-5-20251001")
    result = adapter.run(prompt="Summarize this.", context={"user_memory": []})

    assert result.success is True
    assert result.output == "Here is the summary."
    assert result.error is None


def test_api_adapter_run_sdk_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("rate limit")

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.agents.api_adapter.AnthropicAPIAdapter.is_available", lambda self: True)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    adapter = AnthropicAPIAdapter()
    result = adapter.run(prompt="Do something.", context={})

    assert result.success is False
    assert "rate limit" in result.error


def test_api_adapter_context_with_memories(monkeypatch):
    """Context memories are summarized and injected into the system prompt."""
    captured = {}

    mock_content = MagicMock()
    mock_content.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    def stub_create(**kwargs):
        captured["system"] = kwargs.get("system", "")
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = lambda **kw: stub_create(**kw)

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.agents.api_adapter.AnthropicAPIAdapter.is_available", lambda self: True)

    import sys
    monkeypatch.setitem(sys.modules, "anthropic", mock_anthropic)

    adapter = AnthropicAPIAdapter()
    adapter.run(
        prompt="Summarize.",
        context={
            "user_memory": [{"title": "User pref", "content": "I prefer dark mode."}],
        },
    )
    assert "user_memory" in captured["system"]
    assert "User pref" in captured["system"]
