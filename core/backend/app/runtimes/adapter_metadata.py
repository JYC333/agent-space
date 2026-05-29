"""Runtime adapter model-config metadata for Run API disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .specs import get_runtime_adapter_spec


@dataclass(frozen=True)
class AdapterModelConfigMetadata:
    uses_model_config: bool
    model_config_behavior: Literal[
        "uses_model", "not_applicable", "unsupported", "unknown"
    ]
    model_config_note: str = ""


_UNKNOWN = AdapterModelConfigMetadata(
    uses_model_config=False,
    model_config_behavior="unknown",
    model_config_note="Adapter model config behavior is unknown for this adapter type.",
)


def get_adapter_model_config_metadata(
    adapter_type: str | None,
) -> AdapterModelConfigMetadata:
    if not adapter_type:
        return _UNKNOWN
    try:
        spec = get_runtime_adapter_spec(adapter_type)
    except KeyError:
        return AdapterModelConfigMetadata(
            uses_model_config=False,
            model_config_behavior="unsupported",
            model_config_note=(
                f"Runtime adapter '{adapter_type}' is not registered; "
                "model config cannot be applied."
            ),
        )
    behavior = spec.model.model_config_behavior
    if behavior not in ("uses_model", "not_applicable", "unsupported"):
        behavior = "unknown"
    return AdapterModelConfigMetadata(
        uses_model_config=bool(spec.model.supports_model_override),
        model_config_behavior=behavior,
        model_config_note=(
            "Model override is rendered only when RuntimeAdapterSpec supports it."
            if spec.model.supports_model_override else ""
        ),
    )
