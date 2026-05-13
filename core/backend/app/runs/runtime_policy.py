"""Runtime policy helpers.

Computes ``required_sandbox_level`` and policy snapshot fields from
``AgentVersion.runtime_policy_json``. Does not select adapters, call
providers, or touch sandboxes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from ..models import AgentVersion, Run

_VALID_SANDBOX_LEVELS = frozenset({"none", "dry_run", "worktree", "one_shot_docker"})


@dataclass(frozen=True)
class RuntimePolicyDecision:
    """Outcome of evaluating runtime policy for a queued Run."""

    required_sandbox_level: str
    risk_level: str
    policy_snapshot: dict[str, Any]


def _norm_risk(risk: Any) -> str:
    s = (str(risk) if risk is not None else "low").lower().strip()
    if s in ("low", "medium", "high", "critical"):
        return s
    return "low"


def required_sandbox_level_for_risk(risk_level: str) -> str:
    """Map policy ``risk_level`` to ``required_sandbox_level`` (policy table)."""
    r = _norm_risk(risk_level)
    if r == "low":
        return "none"
    if r == "medium":
        return "dry_run"
    if r == "high":
        return "worktree"
    return "one_shot_docker"


def compute_runtime_policy_decision(*, run: Run, version: AgentVersion) -> RuntimePolicyDecision:
    """Read ``runtime_policy_json`` and derive execution constraints for this Run."""
    policy: dict[str, Any] = dict(version.runtime_policy_json or {})
    risk = _norm_risk(policy.get("risk_level"))
    level = required_sandbox_level_for_risk(risk)
    if level not in _VALID_SANDBOX_LEVELS:
        level = "none"

    snapshot = {
        "risk_level": risk,
        "required_sandbox_level": level,
        "allowed_adapter_types": policy.get("allowed_adapter_types"),
        "allowed_model_providers": policy.get("allowed_model_providers"),
    }
    return RuntimePolicyDecision(
        required_sandbox_level=level,
        risk_level=risk,
        policy_snapshot=snapshot,
    )


def validate_adapter_and_provider_or_raise(
    *,
    run: Run,
    version: AgentVersion,
    policy: dict[str, Any],
) -> None:
    """If Run / version carry adapter or provider IDs, ensure they are allowed when lists exist."""
    allowed_adapters = policy.get("allowed_adapter_types")
    if (
        allowed_adapters is not None
        and isinstance(allowed_adapters, list)
        and len(allowed_adapters) > 0
        and run.adapter_type
        and run.adapter_type not in allowed_adapters
    ):
        raise HTTPException(
            status_code=403,
            detail=f"adapter_type '{run.adapter_type}' is not allowed by runtime_policy_json.allowed_adapter_types",
        )

    allowed_providers = policy.get("allowed_model_providers")
    if (
        allowed_providers is not None
        and isinstance(allowed_providers, list)
        and len(allowed_providers) > 0
    ):
        for mp_id in (run.model_provider_id, version.model_provider_id):
            if mp_id and mp_id not in allowed_providers:
                raise HTTPException(
                    status_code=403,
                    detail="model_provider_id is not allowed by runtime_policy_json.allowed_model_providers",
                )
