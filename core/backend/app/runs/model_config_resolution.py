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
            source="space_default",
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


def _find_space_default_provider(db: Session, space_id: str) -> ModelProvider | None:
    from app.models import ModelProvider

    for row in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
        cfg = row.config_json or {}
        if bool(cfg.get("is_default")) and row.enabled:
            return row
    return None


def resolve_model_config_for_run(
    db: Session,
    *,
    space_id: str,
    request_provider_id: Optional[str],
    request_model: Optional[str],
    version: AgentVersion,
) -> ResolvedModelConfig:
    default_row = _find_space_default_provider(db, space_id)
    default_id = default_row.id if default_row else None
    default_model = default_row.default_model if default_row else None
    default_models = _available_models(default_row) if default_row else []

    return resolve_model_config_priority(
        request_provider_id=request_provider_id,
        request_model=request_model,
        version_provider_id=version.model_provider_id,
        version_model_name=version.model_name,
        default_provider_id=default_id,
        default_provider_model=default_model,
        default_provider_available_models=default_models,
    )
