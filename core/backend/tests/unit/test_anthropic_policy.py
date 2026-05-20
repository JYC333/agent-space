"""Guard tests: Anthropic direct API adapter policy enforcement.

Product policy: Anthropic/Claude execution must go through CLI integrations
(``claude_code`` / ``claude_cli`` in ``app.cli_adapters``), not direct
in-process API key calls.

These tests prevent reintroduction of:
- ``anthropic_api`` adapter type in canonical registry
- ``anthropic_messages`` adapter type in canonical registry
- ``anthropic_messages.py`` file in ``app.runtimes.adapters``
- CLI subprocess auth (ANTHROPIC_API_KEY env passthrough) leaking into canonical
  runtime adapters via ``app.runtimes``

None of these tests should ever be deleted or modified to make a failing
assertion pass — they are policy guards, not implementation tests.
"""

from __future__ import annotations

import inspect


# ---------------------------------------------------------------------------
# A. Registry guards
# ---------------------------------------------------------------------------

class TestAnthropicDirectAPIAdaptersAbsentFromRegistry:
    """anthropic_api and anthropic_messages must never appear in the canonical runtime registry."""

    def test_anthropic_api_not_in_canonical_registry(self):
        """Guard: anthropic_api must not be registered as a canonical runtime adapter."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("anthropic_api"), (
            "POLICY VIOLATION: anthropic_api must not be in the canonical runtime registry. "
            "Anthropic/Claude execution must go through claude_code / claude_cli CLI integrations."
        )

    def test_anthropic_messages_not_in_canonical_registry(self):
        """Guard: anthropic_messages must not be registered as a canonical runtime adapter."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("anthropic_messages"), (
            "POLICY VIOLATION: anthropic_messages must not be in the canonical runtime registry. "
            "Anthropic/Claude execution must go through claude_code / claude_cli CLI integrations."
        )


# ---------------------------------------------------------------------------
# B. File-level guards
# ---------------------------------------------------------------------------

class TestAnthropicAdapterFilesAbsent:
    """The deleted adapter file must not be recreated."""

    def test_anthropic_messages_module_not_importable(self):
        """Guard: app.runtimes.adapters.anthropic_messages must not exist."""
        import importlib.util
        spec = importlib.util.find_spec("app.runtimes.adapters.anthropic_messages")
        assert spec is None, (
            "POLICY VIOLATION: app.runtimes.adapters.anthropic_messages must not exist. "
            "Delete the file — Anthropic direct API adapter is not supported."
        )

    def test_anthropic_api_module_not_importable(self):
        """Guard: app.runtimes.adapters.anthropic_api must not exist."""
        import importlib.util
        spec = importlib.util.find_spec("app.runtimes.adapters.anthropic_api")
        assert spec is None, (
            "POLICY VIOLATION: app.runtimes.adapters.anthropic_api must not exist. "
            "Delete the file — Anthropic direct API adapter is not supported."
        )


# ---------------------------------------------------------------------------
# C. Credential boundary guards
# ---------------------------------------------------------------------------

class TestCanonicalRuntimeAdapterCredentialBoundary:
    """Canonical runtime adapters (app.runtimes) must not read ANTHROPIC_API_KEY from env or settings."""

    def test_echo_adapter_does_not_read_anthropic_env(self):
        """EchoRuntimeAdapter source must not reference ANTHROPIC_API_KEY."""
        from app.runtimes.adapters.echo import EchoRuntimeAdapter
        source = inspect.getsource(EchoRuntimeAdapter)
        assert "ANTHROPIC_API_KEY" not in source
        assert "anthropic_api_key" not in source

    def test_capability_adapter_does_not_read_anthropic_env(self):
        """CapabilityRuntimeAdapter source must not reference ANTHROPIC_API_KEY."""
        from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
        source = inspect.getsource(CapabilityRuntimeAdapter)
        assert "ANTHROPIC_API_KEY" not in source
        assert "anthropic_api_key" not in source

    def test_runtime_registry_does_not_import_anthropic_messages(self):
        """Registry source must not import AnthropicMessagesRuntimeAdapter."""
        import app.runtimes.registry as registry_module
        source = inspect.getsource(registry_module)
        assert "AnthropicMessagesRuntimeAdapter" not in source
        # The string "anthropic_messages" may appear in comments/policy notes, but
        # must not appear as a registered key in _RUNTIME_ADAPTER_CLASSES.
        from app.runtimes.registry import _RUNTIME_ADAPTER_CLASSES
        assert "anthropic_messages" not in _RUNTIME_ADAPTER_CLASSES, (
            "POLICY VIOLATION: anthropic_messages must not be a key in _RUNTIME_ADAPTER_CLASSES"
        )

    def test_runtimes_adapters_init_does_not_import_anthropic_messages(self):
        """app.runtimes.adapters __init__ must not export AnthropicMessagesRuntimeAdapter."""
        import app.runtimes.adapters as adapters_pkg
        source = inspect.getsource(adapters_pkg)
        assert "AnthropicMessagesRuntimeAdapter" not in source


# ---------------------------------------------------------------------------
# D. CLI adapter preservation guards
# ---------------------------------------------------------------------------

class TestClaudeCLIAdapterPreserved:
    """Claude CLI / Claude Code CLI support in app.cli_adapters must remain intact."""

    def test_claude_cli_adapter_importable(self):
        """ClaudeCLIAdapter must remain importable from app.cli_adapters.claude."""
        from app.cli_adapters.claude import ClaudeCLIAdapter
        assert ClaudeCLIAdapter is not None

    def test_claude_cli_adapter_type_is_claude_code(self):
        """ClaudeCLIAdapter.adapter_type must be claude_code."""
        from app.cli_adapters.claude import ClaudeCLIAdapter
        # adapter_type is a property — check on an instance
        adapter = ClaudeCLIAdapter()
        assert adapter.adapter_type == "claude_code"

    def test_codex_cli_adapter_importable(self):
        """CodexCLIAdapter must remain importable from app.cli_adapters.codex."""
        from app.cli_adapters.codex import CodexCLIAdapter
        assert CodexCLIAdapter is not None

    def test_cli_adapters_service_knows_claude_code(self):
        """cli_adapters/service.py must still map claude_code to ClaudeCLIAdapter."""
        import app.cli_adapters.service as svc_module
        source = inspect.getsource(svc_module)
        assert "claude_code" in source
        assert "ClaudeCLIAdapter" in source

    def test_anthropic_api_key_passthrough_confined_to_cli_adapters(self):
        """ANTHROPIC_API_KEY env passthrough must only appear in app.cli_adapters, not app.runtimes."""
        import app.runtimes.credentials as creds_module
        creds_source = inspect.getsource(creds_module)
        # The credentials module documents that env fallback is NOT performed,
        # but it must not also perform the env read.
        # It mentions ANTHROPIC_API_KEY only in the docstring as a prohibition.
        # We just ensure no os.environ / os.getenv read of ANTHROPIC_API_KEY.
        import re
        env_reads = re.findall(
            r'os\.environ.*ANTHROPIC_API_KEY|os\.getenv.*ANTHROPIC_API_KEY',
            creds_source,
        )
        assert env_reads == [], (
            f"POLICY VIOLATION: app.runtimes.credentials reads ANTHROPIC_API_KEY from env: {env_reads}"
        )
