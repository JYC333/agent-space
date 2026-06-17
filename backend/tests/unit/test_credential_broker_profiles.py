"""Unit tests for CredentialBroker under fixed TS credential authority."""

from __future__ import annotations

from app.credentials.broker import CredentialBroker


def test_control_plane_authority_resolves_profile(monkeypatch):
    calls = []

    def _fake_resolve(*, runtime: str, profile_id: str | None, require_existing: bool):
        calls.append((runtime, profile_id, require_existing))
        return {
            "kind": "cli_profile",
            "profile_id": "codex_cli/default",
            "runtime": "codex_cli",
            "source_path": "/aspace/secrets/cli-credentials/codex_cli/default",
            "target_path": "/home/agent/.codex",
            "readonly": False,
        }

    monkeypatch.setattr(
        "app.credentials.broker.resolve_cli_profile_via_control_plane",
        _fake_resolve,
    )

    broker = CredentialBroker(instance_root="/nonexistent")
    found = broker.get_default_profile("codex_cli")

    assert found is not None
    assert found.id == "codex_cli/default"
    assert found.source_path.endswith("/codex_cli/default")
    assert calls == [("codex_cli", None, True)]


def test_control_plane_authority_returns_none_for_missing_profile(monkeypatch):
    calls = []

    def _fake_resolve(*, runtime: str, profile_id: str | None, require_existing: bool):
        calls.append((runtime, profile_id, require_existing))
        return None

    monkeypatch.setattr(
        "app.credentials.broker.resolve_cli_profile_via_control_plane",
        _fake_resolve,
    )

    broker = CredentialBroker(instance_root="/nonexistent")

    assert broker.get_default_profile("claude_code") is None
    assert calls == [("claude_code", None, True)]


def test_control_plane_authority_grants_profile(monkeypatch):
    calls = []

    def _fake_grant(**payload):
        calls.append(payload)
        return {
            "granted": True,
            "profile_id": "codex_cli/default",
            "runtime": "codex_cli",
            "executor_mode": "worktree",
            "readonly": False,
            "temp_home": "/aspace/cache/runtime-homes/run-1",
            "host_source_path": None,
            "target_path": None,
            "env": {
                "HOME": "/aspace/cache/runtime-homes/run-1",
            },
            "fallback_reason": None,
        }

    monkeypatch.setattr(
        "app.credentials.broker.grant_cli_credential_via_control_plane",
        _fake_grant,
    )

    broker = CredentialBroker(instance_root="/nonexistent")
    grant = broker.grant_for_run(
        run_id="run-1",
        runtime="codex_cli",
        risk_level="medium",
        executor_mode="local",
    )

    assert grant is not None
    assert grant.profile_id == "codex_cli/default"
    assert grant.env == {"HOME": "/aspace/cache/runtime-homes/run-1"}
    assert calls == [
        {
            "run_id": "run-1",
            "runtime": "codex_cli",
            "risk_level": "medium",
            "executor_mode": "local",
            "profile_id": None,
        }
    ]


def test_cli_runtime_adapter_uses_cli_credentials():
    """Spec-driven local CLI runtime instances declare uses_cli_credentials=True."""
    from app.runtimes.registry import instantiate_runtime_adapter

    assert instantiate_runtime_adapter("claude_code").uses_cli_credentials is True
    assert instantiate_runtime_adapter("codex_cli").uses_cli_credentials is True


def test_native_runtime_classes_do_not_use_cli_credentials():
    """Native capability adapter does not use CLI login-state credentials."""
    from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
    from app.runtimes.base import BaseRuntimeAdapter

    assert BaseRuntimeAdapter.uses_cli_credentials is False
    assert CapabilityRuntimeAdapter.uses_cli_credentials is False
