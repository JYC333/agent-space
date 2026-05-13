"""Runtime adapter package (product execution).

Registered adapters live under ``app.runtimes.adapters`` and are wired through
``app.runtimes.registry``. Tests use the echo adapter or direct DB fixtures;
obsolete ``runtime`` query overrides are not executed in production.
"""

from .base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext

__all__ = ["BaseRuntimeAdapter", "RuntimeAdapterResult", "RuntimeExecutionContext"]
