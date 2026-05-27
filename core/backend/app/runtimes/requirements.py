"""Runtime capability and credential requirements.

Runtime requirements decide whether ModelProvider resolution is relevant for a
runtime. Space-wide default providers must not leak into runtimes that do not
use ModelProvider/API-key credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from ..models import AgentVersion, ModelProvider, RuntimeAdapter

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


_NONE = RuntimeRequirements(
    model_provider_mode="none",
    credential_mode="none",
    supports_model_override=False,
)
_CLI = RuntimeRequirements(
    model_provider_mode="none",
    credential_mode="cli_profile",
    supports_model_override=False,
)
_API = RuntimeRequirements(
    model_provider_mode="required",
    credential_mode="model_provider_api_key",
    supports_model_override=True,
)


_REQUIREMENTS: dict[str, RuntimeRequirements] = {
    "echo": _NONE,
    "capability": _NONE,
    "claude_code": _CLI,
    "codex_cli": _CLI,
    # Not registered as canonical adapters today; kept here so future API
    # runtimes get the safe default semantics before they are wired.
    "model_provider_api": _API,
    "openai_chat": _API,
    "openai_responses": _API,
    "litellm": _API,
}


def get_runtime_requirements(adapter_type: str | None) -> RuntimeRequirements:
    normalized = (adapter_type or "").strip()
    if not normalized:
        return _NONE
    requirements = _REQUIREMENTS.get(normalized)
    if requirements is None:
        raise UnknownRuntimeRequirementsError(normalized)
    return requirements


def resolve_effective_adapter_type(
    db: Session,
    *,
    space_id: str,
    version: AgentVersion,
    run_adapter_type: str | None = None,
) -> str | None:
    """Resolve adapter_type using the same priority shape as execution."""
    if version.runtime_adapter_id:
        row = (
            db.query(RuntimeAdapter)
            .filter(
                RuntimeAdapter.id == version.runtime_adapter_id,
                RuntimeAdapter.space_id == space_id,
            )
            .first()
        )
        return row.adapter_type if row is not None and row.enabled else None

    runtime_config = dict(version.runtime_config_json or {})
    policy = dict(version.runtime_policy_json or {})
    return (
        (runtime_config.get("adapter_type") or "").strip()
        or (run_adapter_type or "").strip()
        or (str(policy.get("default_adapter_type") or "").strip())
        or None
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
