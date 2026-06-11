"""Spaces module: HTTP API (``api``), default-space resolution (``defaults``),
and the space-created lifecycle hook registry (``hooks``).

The public surface is the space-created hook API. Importing it is lightweight:
``hooks`` imports no product modules at module level (it populates its registry
lazily through ``app.modules.registry``), so the facade stays cheap.
"""

from __future__ import annotations

from .hooks import (
    DuplicateSpaceCreatedHookError,
    SpaceCreatedContext,
    SpaceCreatedHook,
    SpaceCreatedHookRegistry,
)

__all__ = [
    "SpaceCreatedContext",
    "SpaceCreatedHook",
    "SpaceCreatedHookRegistry",
    "DuplicateSpaceCreatedHookError",
]
