"""
Boundary unit tests for runtime policy decisions (app.runs.runtime_policy).

There is no separate RuntimeRouter class; these helpers are the stable decision surface.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.runs.runtime_policy import (
    RuntimePolicyDecision,
    compute_runtime_policy_decision,
    file_access_sandbox_error,
    required_sandbox_level_for_risk,
    resolve_sandbox_level,
    validate_adapter_and_provider_or_raise,
    validate_file_access_adapter_policy,
)


def test_resolve_sandbox_level_cli_no_workspace_is_ephemeral():
    # File-access CLI without a workspace gets a run-scope ephemeral working dir
    # at low/medium risk (instead of an unsandboxed none/dry_run).
    assert resolve_sandbox_level(
        risk_level="low", adapter_type="claude_code", has_workspace=False
    ) == "ephemeral"
    assert resolve_sandbox_level(
        risk_level="medium", adapter_type="codex_cli", has_workspace=False
    ) == "ephemeral"


def test_resolve_sandbox_level_cli_with_workspace_keeps_risk_level():
    # A workspace-bound CLI is NOT bumped to ephemeral; low/medium stay at the
    # risk-derived (non-sandbox) level so validation forces risk_level=high.
    assert resolve_sandbox_level(
        risk_level="low", adapter_type="claude_code", has_workspace=True
    ) == "none"
    assert resolve_sandbox_level(
        risk_level="high", adapter_type="claude_code", has_workspace=True
    ) == "worktree"


def test_resolve_sandbox_level_b13_no_downgrade_for_high_and_critical():
    # B13: high/critical are never downgraded to ephemeral, even with no workspace.
    assert resolve_sandbox_level(
        risk_level="high", adapter_type="claude_code", has_workspace=False
    ) == "worktree"
    assert resolve_sandbox_level(
        risk_level="critical", adapter_type="claude_code", has_workspace=False
    ) == "one_shot_docker"


def test_resolve_sandbox_level_non_file_adapter_unchanged():
    assert resolve_sandbox_level(
        risk_level="low", adapter_type="model_api", has_workspace=False
    ) == "none"
    assert resolve_sandbox_level(
        risk_level="high", adapter_type="model_api", has_workspace=False
    ) == "worktree"


def test_file_access_sandbox_error_allows_ephemeral_and_worktree():
    assert file_access_sandbox_error(
        adapter_type="claude_code", required_sandbox_level="ephemeral", risk_level="low"
    ) is None
    assert file_access_sandbox_error(
        adapter_type="claude_code", required_sandbox_level="worktree", risk_level="high"
    ) is None
    # none/dry_run are not real sandboxes for a file-access adapter.
    assert file_access_sandbox_error(
        adapter_type="claude_code", required_sandbox_level="none", risk_level="low"
    ) is not None
    assert file_access_sandbox_error(
        adapter_type="codex_cli", required_sandbox_level="dry_run", risk_level="medium"
    ) is not None
    # Non file-access adapter is never constrained here.
    assert file_access_sandbox_error(
        adapter_type="model_api", required_sandbox_level="none", risk_level="low"
    ) is None


def test_compute_runtime_policy_decision_cli_no_workspace_ephemeral():
    run = SimpleNamespace(adapter_type="claude_code", workspace_id=None)
    version = SimpleNamespace(runtime_policy_json={"risk_level": "low"})
    out = compute_runtime_policy_decision(run=run, version=version)
    assert out.required_sandbox_level == "ephemeral"
    assert out.policy_snapshot["required_sandbox_level"] == "ephemeral"


def test_required_sandbox_level_maps_risk_to_level():
    assert required_sandbox_level_for_risk("low") == "none"
    assert required_sandbox_level_for_risk("medium") == "dry_run"
    assert required_sandbox_level_for_risk("high") == "worktree"
    assert required_sandbox_level_for_risk("critical") == "one_shot_docker"


def test_required_sandbox_level_unknown_risk_falls_back_to_low():
    assert required_sandbox_level_for_risk("nonsense") == "none"


def test_compute_runtime_policy_decision_stable_snapshot():
    run = SimpleNamespace()
    version = SimpleNamespace(
        runtime_policy_json={
            "risk_level": "HIGH",
            "allowed_adapter_types": ["model_api"],
            "allowed_model_providers": ["p1"],
        }
    )
    out = compute_runtime_policy_decision(run=run, version=version)
    assert isinstance(out, RuntimePolicyDecision)
    assert out.required_sandbox_level == "worktree"
    assert out.risk_level == "high"
    assert out.policy_snapshot["risk_level"] == "high"
    assert out.policy_snapshot["required_sandbox_level"] == "worktree"
    assert out.policy_snapshot["allowed_adapter_types"] == ["model_api"]
    assert out.policy_snapshot["allowed_model_providers"] == ["p1"]


def test_compute_runtime_policy_decision_empty_policy_defaults():
    run = SimpleNamespace()
    version = SimpleNamespace(runtime_policy_json=None)
    out = compute_runtime_policy_decision(run=run, version=version)
    assert out.risk_level == "low"
    assert out.required_sandbox_level == "none"


def test_validate_adapter_denies_disallowed_adapter_type():
    run = SimpleNamespace(adapter_type="claude_code", model_provider_id=None)
    version = SimpleNamespace(model_provider_id=None)
    policy = {"allowed_adapter_types": ["model_api"]}
    with pytest.raises(HTTPException) as ei:
        validate_adapter_and_provider_or_raise(run=run, version=version, policy=policy)
    assert ei.value.status_code == 403
    assert "adapter_type" in ei.value.detail


def test_validate_adapter_allows_when_adapter_list_empty_means_unrestricted():
    """Non-empty list is required before adapter_type is checked."""
    run = SimpleNamespace(adapter_type="anything", model_provider_id=None)
    version = SimpleNamespace(model_provider_id=None)
    validate_adapter_and_provider_or_raise(run=run, version=version, policy={"allowed_adapter_types": []})


def test_validate_provider_denies_when_run_provider_not_allowed():
    run = SimpleNamespace(adapter_type=None, model_provider_id="bad-mp")
    version = SimpleNamespace(model_provider_id=None)
    policy = {"allowed_model_providers": ["good-mp"]}
    with pytest.raises(HTTPException) as ei:
        validate_adapter_and_provider_or_raise(run=run, version=version, policy=policy)
    assert ei.value.status_code == 403


# ===========================================================================
# validate_file_access_adapter_policy — Task 6
# ===========================================================================


def _decision(risk_level: str) -> RuntimePolicyDecision:
    from app.runs.runtime_policy import required_sandbox_level_for_risk
    return RuntimePolicyDecision(
        required_sandbox_level=required_sandbox_level_for_risk(risk_level),
        risk_level=risk_level,
        policy_snapshot={},
    )


def test_claude_code_with_low_risk_returns_error_message():
    msg = validate_file_access_adapter_policy(
        adapter_type="claude_code",
        decision=_decision("low"),
    )
    assert msg is not None
    assert "worktree" in msg
    assert "claude_code" in msg


def test_claude_code_with_high_risk_returns_none():
    msg = validate_file_access_adapter_policy(
        adapter_type="claude_code",
        decision=_decision("high"),
    )
    assert msg is None


def test_codex_cli_with_medium_risk_returns_error_message():
    msg = validate_file_access_adapter_policy(
        adapter_type="codex_cli",
        decision=_decision("medium"),
    )
    assert msg is not None
    assert "codex_cli" in msg


def test_codex_cli_with_high_risk_returns_none():
    msg = validate_file_access_adapter_policy(
        adapter_type="codex_cli",
        decision=_decision("high"),
    )
    assert msg is None


def test_model_api_adapter_with_low_risk_returns_none():
    """Non-file-access adapters can safely use low risk."""
    msg = validate_file_access_adapter_policy(
        adapter_type="model_api",
        decision=_decision("low"),
    )
    assert msg is None


def test_capability_adapter_with_low_risk_returns_none():
    """Capability adapter is not a file-access adapter."""
    msg = validate_file_access_adapter_policy(
        adapter_type="capability",
        decision=_decision("low"),
    )
    assert msg is None
