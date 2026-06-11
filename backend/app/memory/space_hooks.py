"""Memory module's space-created hook: seed system-policy memories.

Registered through ``app.modules.registry`` so the spaces module never imports
memory directly. The seeding logic stays here (``seed_system_memories_for_space``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spaces import SpaceCreatedContext, SpaceCreatedHookRegistry


def _seed_system_memories(context: "SpaceCreatedContext") -> None:
    from .seeder import seed_system_memories_for_space

    # commit=False: the space-creation caller owns the single outer transaction,
    # so a later hook's failure rolls these rows back too (atomic space creation).
    seed_system_memories_for_space(context.db, context.space_id, commit=False)


def register_space_created_hooks(registry: "SpaceCreatedHookRegistry") -> None:
    """Register the memory module's space-created hooks."""
    registry.register("memory:system_memories", _seed_system_memories, order=100)
