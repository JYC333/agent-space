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
