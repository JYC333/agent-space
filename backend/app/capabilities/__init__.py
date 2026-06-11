"""Public facade for the ``capabilities`` module.

Re-exports the capability registry surface other modules import today
(``runs``, ``runtimes``, ``evolution``, ``main``). Callers should depend on
``app.capabilities`` rather than ``capabilities.registry``.
"""

from __future__ import annotations

from .registry import (
    CapabilityRegistry,
    FileDefinedCapability,
    load_installed_capability,
)

__all__ = [
    "CapabilityRegistry",
    "FileDefinedCapability",
    "load_installed_capability",
]
