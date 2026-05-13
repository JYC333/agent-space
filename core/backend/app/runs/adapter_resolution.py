"""Resolve which runtime adapter should execute a Run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import AgentVersion, Run, RuntimeAdapter
from ..runtimes.registry import is_adapter_type_implemented
from .runtime_policy import validate_adapter_and_provider_or_raise


class AdapterResolutionError(Exception):
    """Non-HTTP failure path — caller marks the Run failed with ``error_code``."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedRuntimeAdapter:
    adapter_type: str
    runtime_adapter_row: RuntimeAdapter | None
    merged_config: dict[str, Any]


def resolve_runtime_adapter(
    db: Session,
    *,
    run: Run,
    version: AgentVersion,
    policy: dict[str, Any],
) -> ResolvedRuntimeAdapter:
    """Pick adapter type and merged config; enforce policy + registry."""
    row: RuntimeAdapter | None = None
    if version.runtime_adapter_id:
        row = (
            db.query(RuntimeAdapter)
            .filter(
                RuntimeAdapter.id == version.runtime_adapter_id,
                RuntimeAdapter.space_id == version.space_id,
            )
            .first()
        )
        if row is None:
            raise AdapterResolutionError(
                "adapter_not_configured",
                "AgentVersion.runtime_adapter_id points to a missing RuntimeAdapter row",
            )
        if not row.enabled:
            raise AdapterResolutionError(
                "adapter_disabled",
                f"RuntimeAdapter '{row.id}' is disabled",
            )
        adapter_type = row.adapter_type
        merged = {**(version.runtime_config_json or {}), **(row.config_json or {})}
    else:
        rc = dict(version.runtime_config_json or {})
        adapter_type = (
            (rc.get("adapter_type") or "").strip()
            or (run.adapter_type or "").strip()
            or (str(policy.get("default_adapter_type") or "").strip())
        )
        if not adapter_type:
            raise AdapterResolutionError(
                "adapter_not_configured",
                "No runtime adapter is configured (runtime_adapter_id, runtime_config_json.adapter_type, run.adapter_type, or policy default_adapter_type)",
            )
        merged = rc

    allowed = policy.get("allowed_adapter_types")
    if allowed is not None and isinstance(allowed, list) and len(allowed) > 0:
        if adapter_type not in allowed:
            raise AdapterResolutionError(
                "adapter_type_disallowed",
                f"adapter_type '{adapter_type}' is not allowed by runtime_policy_json.allowed_adapter_types",
            )

    old_adapter = run.adapter_type
    try:
        run.adapter_type = adapter_type
        validate_adapter_and_provider_or_raise(run=run, version=version, policy=policy)
    except HTTPException as exc:
        detail = str(exc.detail)
        code = (
            "model_provider_disallowed"
            if "model_provider" in detail.lower()
            else "adapter_type_disallowed"
        )
        raise AdapterResolutionError(code, detail) from exc
    finally:
        run.adapter_type = old_adapter

    if not is_adapter_type_implemented(adapter_type):
        raise AdapterResolutionError(
            "adapter_not_implemented",
            f"Runtime adapter type '{adapter_type}' is not implemented",
        )

    return ResolvedRuntimeAdapter(
        adapter_type=adapter_type,
        runtime_adapter_row=row,
        merged_config=merged,
    )
