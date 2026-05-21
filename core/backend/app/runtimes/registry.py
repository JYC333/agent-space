"""Maps ``adapter_type`` strings to runtime adapter classes.

Policy note:
  ``anthropic_messages`` (direct Anthropic Messages API adapter) has been
  intentionally removed from this registry per product policy.
  Anthropic/Claude usage must go through CLI integrations only
  (``claude_code`` via ``app.cli_adapters``).
  Do NOT re-add ``anthropic_messages`` or ``anthropic_api`` here.
"""

from __future__ import annotations

from typing import Type

from .adapters import (
    CapabilityRuntimeAdapter,
    ClaudeCodeRuntimeAdapter,
    CodexCliRuntimeAdapter,
    EchoRuntimeAdapter,
)
from .base import BaseRuntimeAdapter

_RUNTIME_ADAPTER_CLASSES: dict[str, Type[BaseRuntimeAdapter]] = {
    EchoRuntimeAdapter.adapter_type: EchoRuntimeAdapter,
    CapabilityRuntimeAdapter.adapter_type: CapabilityRuntimeAdapter,
    # CLI runtime bridge — delegates to app.cli_adapters implementations.
    # See app.runtimes.adapters.cli_runtime for the bridge design.
    ClaudeCodeRuntimeAdapter.adapter_type: ClaudeCodeRuntimeAdapter,
    CodexCliRuntimeAdapter.adapter_type: CodexCliRuntimeAdapter,
}


def is_adapter_type_implemented(adapter_type: str) -> bool:
    return adapter_type in _RUNTIME_ADAPTER_CLASSES


def instantiate_runtime_adapter(adapter_type: str) -> BaseRuntimeAdapter:
    cls = _RUNTIME_ADAPTER_CLASSES.get(adapter_type)
    if cls is None:
        raise KeyError(adapter_type)
    return cls()
