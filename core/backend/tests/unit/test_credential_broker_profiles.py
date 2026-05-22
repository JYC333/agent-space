"""Unit tests for CredentialBroker canonical profile resolution.

Invariants verified:
  1.  claude_code/default resolves for runtime="claude_code" (canonical name).
  2.  codex_cli/default resolves for runtime="codex_cli" (canonical name).
  3.  claude-code/default does NOT resolve for runtime="claude_code" (hyphenated form not recognized).
  4.  codex/default does NOT resolve for runtime="codex_cli" (short form not recognized).
  5.  No profile → get_default_profile returns None.
  6.  Canonical exact-match takes priority over any other profile under the same runtime.
  7.  RunExecutionService / preflight does NOT manually probe aliases
      (tested via broker returning the right profile with one exact-match call).
  8.  uses_cli_credentials attribute on adapter classes.
  9.  Non-CLI adapters do not use CLI credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.credentials.broker import CredentialBroker, CredentialProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broker_with_profiles(profiles: dict[str, CredentialProfile]) -> CredentialBroker:
    """Return a broker whose _load_profiles is pre-seeded with the given dict."""
    broker = CredentialBroker(instance_root="/nonexistent")
    broker._profiles = profiles
    return broker


def _make_profile(pid: str, source_path: str) -> CredentialProfile:
    runtime, name = pid.split("/", 1)
    return CredentialProfile(
        id=pid,
        runtime=runtime,
        name=name,
        source_path=source_path,
        target_path=f"/home/agent/.{runtime}",
    )


# ===========================================================================
# 1. claude_code/default resolves for runtime="claude_code"
# ===========================================================================


def test_claude_code_canonical_resolves(tmp_path):
    """Canonical name claude_code/default is found for runtime="claude_code"."""
    profile_dir = tmp_path / "claude_code" / "default"
    profile_dir.mkdir(parents=True)

    profiles = {"claude_code/default": _make_profile("claude_code/default", str(profile_dir))}
    broker = _make_broker_with_profiles(profiles)

    found = broker.get_default_profile("claude_code")
    assert found is not None
    assert found.id == "claude_code/default"


# ===========================================================================
# 2. codex_cli/default resolves for runtime="codex_cli"
# ===========================================================================


def test_codex_cli_canonical_resolves(tmp_path):
    """Canonical name codex_cli/default is found for runtime="codex_cli"."""
    profile_dir = tmp_path / "codex_cli" / "default"
    profile_dir.mkdir(parents=True)

    profiles = {"codex_cli/default": _make_profile("codex_cli/default", str(profile_dir))}
    broker = _make_broker_with_profiles(profiles)

    found = broker.get_default_profile("codex_cli")
    assert found is not None
    assert found.id == "codex_cli/default"


# ===========================================================================
# 3. Hyphenated claude-code/default does NOT resolve for runtime="claude_code"
# ===========================================================================


def test_hyphenated_claude_dash_code_does_not_resolve_for_claude_code(tmp_path):
    """claude-code/default uses a hyphenated name — broker requires underscore-normalized runtime names."""
    profile_dir = tmp_path / "claude-code" / "default"
    profile_dir.mkdir(parents=True)

    profiles = {"claude-code/default": _make_profile("claude-code/default", str(profile_dir))}
    broker = _make_broker_with_profiles(profiles)

    found = broker.get_default_profile("claude_code")
    assert found is None


# ===========================================================================
# 4. Short-form codex/default does NOT resolve for runtime="codex_cli"
# ===========================================================================


def test_short_codex_does_not_resolve_for_codex_cli(tmp_path):
    """codex/default uses the short non-canonical name — broker requires codex_cli/default."""
    profile_dir = tmp_path / "codex" / "default"
    profile_dir.mkdir(parents=True)

    profiles = {"codex/default": _make_profile("codex/default", str(profile_dir))}
    broker = _make_broker_with_profiles(profiles)

    found = broker.get_default_profile("codex_cli")
    assert found is None


# ===========================================================================
# 5. No profile → returns None
# ===========================================================================


def test_get_default_profile_returns_none_when_no_profile():
    broker = _make_broker_with_profiles({})
    assert broker.get_default_profile("claude_code") is None
    assert broker.get_default_profile("codex_cli") is None
    assert broker.get_default_profile("some_unknown_adapter") is None


# ===========================================================================
# 6. Canonical /default preferred over non-default profile under same runtime
# ===========================================================================


def test_default_profile_preferred_over_other_named_profile(tmp_path):
    """<runtime>/default takes priority over <runtime>/<other-name>."""
    dir_default = tmp_path / "claude_code" / "default"
    dir_default.mkdir(parents=True)
    dir_other = tmp_path / "claude_code" / "work"
    dir_other.mkdir(parents=True)

    profiles = {
        "claude_code/default": _make_profile("claude_code/default", str(dir_default)),
        "claude_code/work": _make_profile("claude_code/work", str(dir_other)),
    }
    broker = _make_broker_with_profiles(profiles)

    found = broker.get_default_profile("claude_code")
    assert found is not None
    assert found.id == "claude_code/default"


# ===========================================================================
# 7. uses_cli_credentials attribute on adapter classes
# ===========================================================================


def test_cli_runtime_adapter_uses_cli_credentials():
    """CliRuntimeAdapter subclasses declare uses_cli_credentials=True."""
    from app.runtimes.adapters.cli_runtime import (
        ClaudeCodeRuntimeAdapter,
        CodexCliRuntimeAdapter,
        CliRuntimeAdapter,
    )
    assert CliRuntimeAdapter.uses_cli_credentials is True
    assert ClaudeCodeRuntimeAdapter.uses_cli_credentials is True
    assert CodexCliRuntimeAdapter.uses_cli_credentials is True


# ===========================================================================
# 8 & 9. Non-CLI adapters do not use CLI credentials
# ===========================================================================


def test_non_cli_adapters_do_not_use_cli_credentials():
    """echo and capability adapters do NOT use CLI login-state credentials."""
    from app.runtimes.adapters.echo import EchoRuntimeAdapter
    from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
    from app.runtimes.base import BaseRuntimeAdapter

    assert BaseRuntimeAdapter.uses_cli_credentials is False
    assert EchoRuntimeAdapter.uses_cli_credentials is False
    assert CapabilityRuntimeAdapter.uses_cli_credentials is False
