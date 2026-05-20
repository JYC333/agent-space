"""Maps ``adapter_type`` strings to runtime adapter classes."""

from __future__ import annotations

from typing import Type

from .adapters import (
    AnthropicMessagesRuntimeAdapter,
    CapabilityRuntimeAdapter,
    EchoRuntimeAdapter,
)
from .base import BaseRuntimeAdapter

_RUNTIME_ADAPTER_CLASSES: dict[str, Type[BaseRuntimeAdapter]] = {
    EchoRuntimeAdapter.adapter_type: EchoRuntimeAdapter,
    AnthropicMessagesRuntimeAdapter.adapter_type: AnthropicMessagesRuntimeAdapter,
    CapabilityRuntimeAdapter.adapter_type: CapabilityRuntimeAdapter,
}


def is_adapter_type_implemented(adapter_type: str) -> bool:
    return adapter_type in _RUNTIME_ADAPTER_CLASSES


def instantiate_runtime_adapter(adapter_type: str) -> BaseRuntimeAdapter:
    cls = _RUNTIME_ADAPTER_CLASSES.get(adapter_type)
    if cls is None:
        raise KeyError(adapter_type)
    return cls()
