"""Knowledge module's space-created hook: seed default Notes collections.

Registered through ``app.modules.registry`` so the spaces module never imports
knowledge directly. The seeding logic stays in ``seeder``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spaces import SpaceCreatedContext, SpaceCreatedHookRegistry


def _seed_default_note_collections(context: "SpaceCreatedContext") -> None:
    from .seeder import seed_default_note_collections

    seed_default_note_collections(context.db, context.space_id)


def register_space_created_hooks(registry: "SpaceCreatedHookRegistry") -> None:
    """Register the knowledge module's space-created hooks."""
    registry.register(
        "knowledge:default_note_collections", _seed_default_note_collections, order=300
    )
