"""Resolve RuntimeAdapterSpec entries to executable runtime adapters."""

from __future__ import annotations

from .adapters import CapabilityRuntimeAdapter, EchoRuntimeAdapter, GenericCliRuntimeAdapter
from .base import BaseRuntimeAdapter
from .specs import get_runtime_adapter_spec

_NATIVE_RUNTIME_ADAPTER_CLASSES: dict[str, type[BaseRuntimeAdapter]] = {
    EchoRuntimeAdapter.adapter_type: EchoRuntimeAdapter,
    CapabilityRuntimeAdapter.adapter_type: CapabilityRuntimeAdapter,
}


def is_adapter_type_implemented(adapter_type: str) -> bool:
    try:
        return get_runtime_adapter_spec(adapter_type).implementation_status == "implemented"
    except KeyError:
        return False


def instantiate_runtime_adapter(adapter_type: str) -> BaseRuntimeAdapter:
    spec = get_runtime_adapter_spec(adapter_type)
    if spec.implementation_status != "implemented":
        raise KeyError(adapter_type)
    cls = _NATIVE_RUNTIME_ADAPTER_CLASSES.get(adapter_type)
    if cls is not None:
        return cls()
    if spec.runtime_kind == "local_cli":
        return GenericCliRuntimeAdapter(spec)
    raise KeyError(adapter_type)
