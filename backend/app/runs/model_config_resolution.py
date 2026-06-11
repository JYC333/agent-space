"""Resolve model provider and model name for a Run — pure priority rules + DB lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import AgentVersion, ModelProvider


@dataclass(frozen=True)
class ResolvedModelConfig:
    model_provider_id: Optional[str]
    model_name: Optional[str]
    source: str


def resolve_model_config_priority(
    *,
    request_provider_id: Optional[str],
    request_model: Optional[str],
    version_provider_id: Optional[str],
    version_model_name: Optional[str],
    default_provider_id: Optional[str],
    default_provider_model: Optional[str],
    default_provider_available_models: Optional[list[str]] = None,
    default_provider_source: str = "space_default",
) -> ResolvedModelConfig:
    """Pure resolution — no database access."""
    if request_provider_id:
        model = request_model or version_model_name
        if not model and default_provider_id == request_provider_id:
            model = default_provider_model
        if not model and default_provider_available_models:
            model = default_provider_available_models[0]
        return ResolvedModelConfig(
            model_provider_id=request_provider_id,
            model_name=model,
            source="request",
        )

    if version_provider_id:
        return ResolvedModelConfig(
            model_provider_id=version_provider_id,
            model_name=version_model_name,
            source="agent_default",
        )

    if default_provider_id:
        model = default_provider_model
        if not model and default_provider_available_models:
            model = default_provider_available_models[0]
        return ResolvedModelConfig(
            model_provider_id=default_provider_id,
            model_name=model,
            source=default_provider_source,
        )

    return ResolvedModelConfig(
        model_provider_id=None,
        model_name=None,
        source="none",
    )


def _available_models(row: ModelProvider) -> list[str]:
    caps = row.capabilities_json or {}
    if isinstance(caps, dict):
        return list(caps.get("models") or [])
    if isinstance(caps, list):
        return list(caps)
    return []


def resolve_model_config_for_runtime(
    db: Session,
    *,
    space_id: str,
    adapter_type: Optional[str],
    request_provider_id: Optional[str],
    request_model: Optional[str],
    version: AgentVersion,
) -> ResolvedModelConfig:
    """Resolve model config only when the runtime requirements allow it."""
    from ..runtimes.requirements import (
        get_runtime_requirements,
        resolve_default_provider_for_runtime,
    )

    requirements = get_runtime_requirements(adapter_type)
    if requirements.model_provider_mode == "none":
        return ResolvedModelConfig(
            model_provider_id=None,
            model_name=None,
            source="none",
        )

    default_row = resolve_default_provider_for_runtime(db, space_id, adapter_type)
    default_id = default_row.id if default_row else None
    default_model = default_row.default_model if default_row else None
    default_models = _available_models(default_row) if default_row else []
    default_source = (
        "runtime_default"
        if _is_runtime_scoped_default(default_row, adapter_type)
        else "space_default"
    )

    if requirements.model_provider_mode == "optional":
        default_id = None
        default_model = None
        default_models = []
        default_source = "space_default"

    return resolve_model_config_priority(
        request_provider_id=request_provider_id,
        request_model=request_model,
        version_provider_id=version.model_provider_id,
        version_model_name=version.model_name,
        default_provider_id=default_id,
        default_provider_model=default_model,
        default_provider_available_models=default_models,
        default_provider_source=default_source,
    )


def _is_runtime_scoped_default(row: ModelProvider | None, adapter_type: str | None) -> bool:
    if row is None or not adapter_type:
        return False
    cfg = row.config_json or {}
    if not isinstance(cfg, dict):
        return False
    if cfg.get("runtime_default_for") == adapter_type:
        return True
    if cfg.get("runtime_default_adapter_type") == adapter_type:
        return True
    adapter_types = cfg.get("runtime_default_adapter_types")
    if isinstance(adapter_types, list) and adapter_type in adapter_types:
        return True
    runtime_defaults = cfg.get("runtime_defaults")
    return isinstance(runtime_defaults, dict) and runtime_defaults.get(adapter_type) is True
