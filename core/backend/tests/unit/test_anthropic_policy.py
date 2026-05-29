"""Guard tests: Anthropic local CLI runtime policy enforcement.

Product policy: Anthropic/Claude execution must go through the ``claude_code``
RuntimeAdapterSpec and GenericCliRuntimeAdapter path.

These tests keep current runtime adapters from reading ambient Anthropic
credentials and verify that Claude Code is modeled as a local CLI spec.
"""

from __future__ import annotations

import inspect


# ---------------------------------------------------------------------------
# A. Credential boundary guards
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

# ---------------------------------------------------------------------------
# B. RuntimeAdapterSpec guards
# ---------------------------------------------------------------------------

class TestClaudeRuntimeAdapterSpec:
    """Claude Code is represented by spec data plus the generic CLI runtime."""

    def test_claude_code_spec_is_cli_profile_based(self):
        from app.runtimes.specs import get_runtime_adapter_spec
        spec = get_runtime_adapter_spec("claude_code")
        assert spec.runtime_kind == "local_cli"
        assert spec.credentials.credential_mode == "cli_profile"
        assert spec.credentials.env_auth_var == "ANTHROPIC_API_KEY"

    def test_codex_cli_spec_is_cli_profile_based(self):
        from app.runtimes.specs import get_runtime_adapter_spec
        spec = get_runtime_adapter_spec("codex_cli")
        assert spec.runtime_kind == "local_cli"
        assert spec.credentials.credential_mode == "cli_profile"
        assert spec.credentials.env_auth_var == "OPENAI_API_KEY"

    def test_generic_cli_runtime_does_not_read_ambient_anthropic_env(self):
        import re
        import app.runtimes.adapters.cli_runtime as cli_runtime
        source = inspect.getsource(cli_runtime)
        env_reads = re.findall(
            r'os\.environ.*ANTHROPIC_API_KEY|os\.getenv.*ANTHROPIC_API_KEY',
            source,
        )
        assert env_reads == []
