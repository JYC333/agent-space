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
    required_sandbox_level_for_risk,
    validate_adapter_and_provider_or_raise,
    validate_file_access_adapter_policy,
)


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
            "allowed_adapter_types": ["echo"],
            "allowed_model_providers": ["p1"],
        }
    )
    out = compute_runtime_policy_decision(run=run, version=version)
    assert isinstance(out, RuntimePolicyDecision)
    assert out.required_sandbox_level == "worktree"
    assert out.risk_level == "high"
    assert out.policy_snapshot["risk_level"] == "high"
    assert out.policy_snapshot["required_sandbox_level"] == "worktree"
    assert out.policy_snapshot["allowed_adapter_types"] == ["echo"]
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
    policy = {"allowed_adapter_types": ["echo"]}
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


def test_validate_provider_denies_when_adapter_row_provider_not_allowed():
    """A provider pinned on the RuntimeAdapter row is subject to the allowlist too.

    run/version carry no provider, so without checking the adapter row's
    provider_id a disallowed provider would slip through the allowlist.
    """
    run = SimpleNamespace(adapter_type=None, model_provider_id=None)
    version = SimpleNamespace(model_provider_id=None)
    policy = {"allowed_model_providers": ["good-mp"]}
    with pytest.raises(HTTPException) as ei:
        validate_adapter_and_provider_or_raise(
            run=run, version=version, policy=policy, adapter_provider_id="bad-mp"
        )
    assert ei.value.status_code == 403


def test_validate_provider_allows_when_adapter_row_provider_is_allowed():
    run = SimpleNamespace(adapter_type=None, model_provider_id=None)
    version = SimpleNamespace(model_provider_id=None)
    policy = {"allowed_model_providers": ["good-mp"]}
    validate_adapter_and_provider_or_raise(
        run=run, version=version, policy=policy, adapter_provider_id="good-mp"
    )


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


def test_echo_adapter_with_low_risk_returns_none():
    """Non-file-access adapters can safely use low risk."""
    msg = validate_file_access_adapter_policy(
        adapter_type="echo",
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
