"""
Side effects when a new ``Space`` row is created (OAuth, ``POST /spaces``, system_core).

The DB may stay empty until the first login; nothing runs at app import time.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def on_space_created(db: Session, space_id: str, *, seeded_by_user_id: str) -> None:
    """
    Run after a new ``Space`` exists.

    ``seeded_by_user_id`` is the acting owner's ``users.id`` (used for audit);
    system policy memories are space-owned with ``subject_user_id`` NULL.

    No concrete agents are seeded per space. Built-in product behavior comes from
    system AgentTemplates (factories, seeded once globally in ``bootstrap``); a
    concrete Agent is created only on demand via
    ``AgentTemplateService.create_agent_from_template`` (copy-on-create).
    """
    from ..memory.seeder import seed_system_memories_for_space
    from ..execution_planes.seeder import seed_default_execution_planes
    from ..knowledge.seeder import seed_default_note_collections

    seed_system_memories_for_space(db, space_id)
    seed_default_execution_planes(db, space_id)
    seed_default_note_collections(db, space_id)
