"""Runtime adapter package (product execution).

Registered adapters live under ``app.runtimes.adapters`` and are wired through
``app.runtimes.registry``. Tests use explicit fake adapters or direct DB fixtures;
obsolete ``runtime`` query overrides are not executed in production.

This package is a lower-level execution layer: it must not import ``app.runs``.
Run evidence and subprocess registration flow through the ``app.runtimes.ports``
protocols, implemented and injected by the runs-owned composition root.
"""

from .base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
from .ports import RuntimeEvent, RuntimeEventSink, RuntimeProcessRegistry
from .requirements import (
    RuntimeRequirements,
    UnknownRuntimeRequirementsError,
    get_runtime_requirements,
)
from .specs import (
    RuntimeAdapterSpec,
    get_runtime_adapter_spec,
    list_runtime_adapter_specs,
)

__all__ = [
    "BaseRuntimeAdapter",
    "RuntimeAdapterResult",
    "RuntimeExecutionContext",
    "RuntimeAdapterSpec",
    "RuntimeRequirements",
    "RuntimeEvent",
    "RuntimeEventSink",
    "RuntimeProcessRegistry",
    "UnknownRuntimeRequirementsError",
    "get_runtime_adapter_spec",
    "get_runtime_requirements",
    "list_runtime_adapter_specs",
]
