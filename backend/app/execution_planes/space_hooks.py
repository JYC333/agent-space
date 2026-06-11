"""Execution-planes module's space-created hook: seed default execution planes.

Registered through ``app.modules.registry`` so the spaces module never imports
execution_planes directly. The seeding logic stays in ``seeder``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..spaces import SpaceCreatedContext, SpaceCreatedHookRegistry


def _seed_default_execution_planes(context: "SpaceCreatedContext") -> None:
    from .seeder import seed_default_execution_planes

    # commit=False: the space-creation caller owns the single outer transaction,
    # so a later hook's failure rolls these rows back too (atomic space creation).
    seed_default_execution_planes(context.db, context.space_id, commit=False)


def register_space_created_hooks(registry: "SpaceCreatedHookRegistry") -> None:
    """Register the execution-planes module's space-created hooks."""
    registry.register(
        "execution_planes:default_planes", _seed_default_execution_planes, order=200
    )
