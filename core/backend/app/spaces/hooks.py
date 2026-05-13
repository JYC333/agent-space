"""
Side effects when a new ``Space`` row is created (OAuth, ``POST /spaces``, system_core).

The DB may stay empty until the first login; nothing runs at app import time.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def on_space_created(db: Session, space_id: str, *, seeded_by_user_id: str) -> None:
    """
    Run after a new ``Space`` exists.

    ``seeded_by_user_id`` is the acting owner's ``users.id`` (used for built-in
    agents and audit); system policy memories are space-owned with ``subject_user_id`` NULL.
    """
    from ..memory.seeder import seed_system_memories_for_space
    from ..agents.seeder import seed_builtin_agents

    seed_system_memories_for_space(db, space_id)
    seed_builtin_agents(db, space_id=space_id, owner_user_id=seeded_by_user_id)
