"""Compatibility facade for Run runtime adapter resolution."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import AgentVersion, Run
from ..router import AdapterResolutionError, ResolvedRuntimeAdapter, RouterService
from ..runtimes import get_runtime_adapter_spec
from .runtime_policy import validate_adapter_and_provider_or_raise


def is_adapter_type_implemented(adapter_type: str) -> bool:
    try:
        return get_runtime_adapter_spec(adapter_type).implementation_status == "implemented"
    except KeyError:
        return False


def resolve_runtime_adapter(
    db: Session,
    *,
    run: Run,
    version: AgentVersion,
    policy: dict[str, Any],
) -> ResolvedRuntimeAdapter:
    """Pick adapter type and merged config; enforce policy + catalog.

    Routing ownership lives in ``app.router.RouterService``. This function stays
    as the historical runs facade and supplies the runs-owned model-provider
    policy validator.
    """

    def _validate_policy(adapter_type: str, adapter_provider_id: str | None) -> None:
        old_adapter = run.adapter_type
        try:
            run.adapter_type = adapter_type
            validate_adapter_and_provider_or_raise(
                run=run,
                version=version,
                policy=policy,
                adapter_provider_id=adapter_provider_id,
            )
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

    router = RouterService(
        db,
        spec_getter=get_runtime_adapter_spec,
        implementation_checker=is_adapter_type_implemented,
    )
    return router.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=policy,
        validate_policy=_validate_policy,
    )


__all__ = [
    "AdapterResolutionError",
    "ResolvedRuntimeAdapter",
    "get_runtime_adapter_spec",
    "is_adapter_type_implemented",
    "resolve_runtime_adapter",
]
