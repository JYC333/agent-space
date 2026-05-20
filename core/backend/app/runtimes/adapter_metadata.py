"""Runtime adapter model-config metadata for Run API disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry import _RUNTIME_ADAPTER_CLASSES


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
    cls = _RUNTIME_ADAPTER_CLASSES.get(adapter_type)
    if cls is None:
        return AdapterModelConfigMetadata(
            uses_model_config=False,
            model_config_behavior="unsupported",
            model_config_note=(
                f"Runtime adapter '{adapter_type}' is not registered; "
                "model config cannot be applied."
            ),
        )
    behavior = getattr(cls, "model_config_behavior", "not_applicable")
    if behavior not in ("uses_model", "not_applicable", "unsupported"):
        behavior = "unknown"
    return AdapterModelConfigMetadata(
        uses_model_config=bool(getattr(cls, "uses_model_config", False)),
        model_config_behavior=behavior,
        model_config_note=str(getattr(cls, "model_config_note", "") or ""),
    )
