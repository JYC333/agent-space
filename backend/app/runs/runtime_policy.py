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

_VALID_SANDBOX_LEVELS = frozenset(
    {"none", "dry_run", "ephemeral", "worktree", "one_shot_docker"}
)

# Levels that do NOT isolate the filesystem. A file-access adapter (CLI) must
# never run at one of these (B13: sandboxed adapters are always sandboxed).
_NON_SANDBOX_LEVELS = frozenset({"none", "dry_run"})


def _safe_spec(adapter_type: str | None):
    """Look up a runtime adapter spec, returning None when unknown."""
    if not adapter_type:
        return None
    try:
        from ..runtimes.specs import get_runtime_adapter_spec

        return get_runtime_adapter_spec(adapter_type)
    except KeyError:
        return None


def resolve_sandbox_level(
    *, risk_level: str, adapter_type: str | None, has_workspace: bool
) -> str:
    """Resolve ``required_sandbox_level`` from risk + adapter + workspace binding.

    Working-directory scope (slice-1 of the scope ladder):
    - non file-access adapters → risk-derived level (unchanged).
    - file-access CLI adapter whose risk resolves to a non-isolating level
      (none/dry_run) AND has no persistent workspace bound → ``ephemeral``
      (run-scope: a system-provisioned throwaway working dir, no git).
    - file-access CLI adapter with a workspace bound → left at the risk-derived
      level so validation forces ``risk_level=high`` (worktree); operating on a
      persistent workspace needs worktree isolation + diff review (B19).
    - high/critical are never downgraded (B13): high→worktree, critical→
      one_shot_docker (fail-closed, unimplemented).
    """
    level = required_sandbox_level_for_risk(risk_level)
    if level not in _VALID_SANDBOX_LEVELS:
        level = "none"
    spec = _safe_spec(adapter_type)
    requires_file_access = bool(spec and spec.sandbox.requires_file_access)
    if requires_file_access and level in _NON_SANDBOX_LEVELS and not has_workspace:
        level = "ephemeral"
    return level


def file_access_sandbox_error(
    *, adapter_type: str | None, required_sandbox_level: str, risk_level: str
) -> str | None:
    """Return an error if a file-access adapter resolved to a non-sandbox level.

    A workspace-bound CLI at low/medium risk lands on none/dry_run and must be
    raised to ``risk_level=high`` (worktree). A no-workspace CLI is bumped to
    ``ephemeral`` by :func:`resolve_sandbox_level` and passes here.
    """
    spec = _safe_spec(adapter_type)
    if not (spec and spec.sandbox.requires_file_access):
        return None
    if required_sandbox_level in _NON_SANDBOX_LEVELS:
        return (
            f"Adapter '{adapter_type}' requires file-system access and must run in an "
            f"isolated sandbox, but required_sandbox_level='{required_sandbox_level}' "
            f"(derived from risk_level='{risk_level}'). Bind a workspace and set "
            "risk_level=high for worktree isolation, or run without a workspace for an "
            "ephemeral working directory."
        )
    return None


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
    level = resolve_sandbox_level(
        risk_level=risk,
        adapter_type=getattr(run, "adapter_type", None),
        has_workspace=bool(getattr(run, "workspace_id", None)),
    )

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
    """If Run / version carry adapter or provider IDs, ensure they are allowed when lists exist.
    """
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


def parse_allow_dirty_workspace(policy_json: dict | None) -> bool:
    """Extract allow_dirty_workspace from runtime_policy_json.

    Returns False when the key is absent.
    Raises ValueError with error code 'automation_preflight_invalid_runtime_policy'
    when the key is present but not a bool.
    """
    if not policy_json:
        return False
    raw = policy_json.get("allow_dirty_workspace")
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ValueError(
            "automation_preflight_invalid_runtime_policy: "
            f"runtime_policy_json.allow_dirty_workspace must be a bool, got {type(raw).__name__!r}"
        )
    return raw


def validate_file_access_adapter_policy(
    *,
    adapter_type: str,
    decision: RuntimePolicyDecision,
) -> str | None:
    """Return an error message if a file-access adapter is configured with an unsafe policy.

    CLI adapters such as ``claude_code`` and ``codex_cli`` read and write workspace
    files, so they must run inside a worktree sandbox (``risk_level=high``).
    Running them at lower risk levels would execute untrusted file writes directly
    in the live workspace, bypassing the code_patch review flow.

    Returns a human-readable error string when the combo is unsafe, or ``None``
    when the policy is acceptable.

    This check fires before the adapter is started so the misconfiguration is
    caught early rather than failing mid-execution or silently mutating the
    workspace.

    A no-workspace CLI run is resolved to ``ephemeral`` (a real sandbox) by
    :func:`resolve_sandbox_level`, so it passes; only a non-sandbox level
    (none/dry_run) for a file-access adapter is rejected.
    """
    return file_access_sandbox_error(
        adapter_type=adapter_type,
        required_sandbox_level=decision.required_sandbox_level,
        risk_level=decision.risk_level,
    )
