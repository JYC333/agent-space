"""Guard tests: credential channel isolation for runtime adapters (ADR 0010).

Invariant: an Anthropic API key must never enter a Claude Code CLI subprocess
environment. Canonical runtime adapters must not read ambient ANTHROPIC_API_KEY
from env/settings, and Claude Code is modeled as a local CLI spec using cli_profile
credentials granted explicitly by the CredentialBroker.

(In-process API calls — reflector, /providers/chat, the model_api adapter —
pass the key as a litellm parameter and never touch os.environ, so they may serve
any provider including Anthropic; that channel is out of scope for these CLI tests.)
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
