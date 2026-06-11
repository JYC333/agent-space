"""Runtime capability and credential requirements.

Runtime requirements decide whether ModelProvider resolution is relevant for a
runtime. Space-wide default providers must not leak into runtimes that do not
use ModelProvider/API-key credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from ..models import ModelProvider
from .specs import get_runtime_adapter_spec

ModelProviderMode = Literal["none", "optional", "required"]
CredentialMode = Literal["none", "model_provider_api_key", "cli_profile"]


@dataclass(frozen=True)
class RuntimeRequirements:
    model_provider_mode: ModelProviderMode
    credential_mode: CredentialMode
    supports_model_override: bool


class UnknownRuntimeRequirementsError(ValueError):
    """Raised when a concrete runtime adapter lacks explicit requirements."""

    def __init__(self, adapter_type: str):
        self.adapter_type = adapter_type
        super().__init__(
            f"runtime_requirements_missing: Runtime requirements are not configured "
            f"for adapter_type={adapter_type!r}"
        )


def get_runtime_requirements(adapter_type: str | None) -> RuntimeRequirements:
    normalized = (adapter_type or "").strip()
    if not normalized:
        return RuntimeRequirements(
            model_provider_mode="none",
            credential_mode="none",
            supports_model_override=False,
        )
    try:
        spec = get_runtime_adapter_spec(normalized)
    except KeyError as exc:
        raise UnknownRuntimeRequirementsError(normalized)
    return RuntimeRequirements(
        model_provider_mode=spec.model.model_provider_mode,
        credential_mode=spec.credentials.credential_mode,
        supports_model_override=spec.model.supports_model_override,
    )


def resolve_default_provider_for_runtime(
    db: Session,
    space_id: str,
    adapter_type: str | None,
) -> ModelProvider | None:
    """Resolve a runtime-scoped default ModelProvider.

    No new table exists yet. Runtime-scoped defaults are expressed on
    ModelProvider.config_json using one of:
      - runtime_default_for: "<adapter_type>"
      - runtime_default_adapter_type: "<adapter_type>"
      - runtime_default_adapter_types: ["<adapter_type>", ...]
      - runtime_defaults: {"<adapter_type>": true}
    """
    requirements = get_runtime_requirements(adapter_type)
    if requirements.model_provider_mode == "none":
        return None

    if adapter_type:
        rows = (
            db.query(ModelProvider)
            .filter(ModelProvider.space_id == space_id, ModelProvider.enabled.is_(True))
            .all()
        )
        for row in rows:
            cfg = row.config_json or {}
            if not isinstance(cfg, dict):
                continue
            if cfg.get("runtime_default_for") == adapter_type:
                return row
            if cfg.get("runtime_default_adapter_type") == adapter_type:
                return row
            adapter_types = cfg.get("runtime_default_adapter_types")
            if isinstance(adapter_types, list) and adapter_type in adapter_types:
                return row
            runtime_defaults = cfg.get("runtime_defaults")
            if isinstance(runtime_defaults, dict) and runtime_defaults.get(adapter_type) is True:
                return row

    if requirements.model_provider_mode != "required":
        return None

    for row in db.query(ModelProvider).filter(ModelProvider.space_id == space_id).all():
        cfg = row.config_json or {}
        if isinstance(cfg, dict) and bool(cfg.get("is_default")) and row.enabled:
            return row
    return None
