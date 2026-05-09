"""
SystemMemorySeeder — seeds system-scope policies into the database on first run.

These are the ground rules the context builder injects into every agent context.
They are seeded once; subsequent startups skip already-existing entries.
"""

from __future__ import annotations
from sqlalchemy.orm import Session
from ..models import Memory
from .store import MemoryStore
from ..schemas import MemoryCreate
from ..config import settings

_SYSTEM_SEEDS = [
    MemoryCreate(
        title="Memory Policy",
        content=(
            "Core memory rules:\n"
            "1. Agents may NOT write to long-term memory directly.\n"
            "2. All long-term memory writes must go through the proposal → approval workflow.\n"
            "3. Proposals must include a rationale.\n"
            "4. Users must explicitly accept or reject each proposal.\n"
            "5. Rejected proposals are never promoted to active memory.\n"
            "6. Memory scopes: system > space > user > workspace > capability > agent.\n"
            "7. Private memories are visible only to their owner.\n"
            "8. workspace_shared memories are visible within the same workspace.\n"
            "9. space_shared memories are visible to all users in the same space.\n"
            "10. Memory never crosses space boundaries."
        ),
        type="semantic",
        scope="system",
        namespace="system.memory_policy",
        visibility="space_shared",
        importance=1.0,
        confidence=1.0,
        space_id=settings.default_space_id,
        owner_user_id="system",
    ),
    MemoryCreate(
        title="Context Policy",
        content=(
            "Context builder rules:\n"
            "1. Context must be scoped — never dump all memories.\n"
            "2. Sort by importance, confidence, then recency.\n"
            "3. Respect space, user, and workspace boundaries.\n"
            "4. Episodic memories are capped separately from semantic/preference.\n"
            "5. System policy is always included.\n"
            "6. Context packages are read-only snapshots — agents cannot modify them.\n"
            "7. space_id and user_id are always required to build context."
        ),
        type="semantic",
        scope="system",
        namespace="system.context_policy",
        visibility="space_shared",
        importance=1.0,
        confidence=1.0,
        space_id=settings.default_space_id,
        owner_user_id="system",
    ),
    MemoryCreate(
        title="Capability Policy",
        content=(
            "Capability rules:\n"
            "1. Capabilities are code-defined and version-controlled.\n"
            "2. Each capability declares its memory access (read/write scopes and types).\n"
            "3. Capability writes always require proposals unless scope is 'agent'.\n"
            "4. Capabilities may not access memories outside their declared access.\n"
            "5. New capabilities must be registered before they can be executed.\n"
            "6. Disabled capabilities cannot be run."
        ),
        type="semantic",
        scope="system",
        namespace="system.capability_policy",
        visibility="space_shared",
        importance=0.9,
        confidence=1.0,
        space_id=settings.default_space_id,
        owner_user_id="system",
    ),
]


def seed_system_memories(db: Session) -> int:
    """Insert system seed memories if they don't already exist. Returns count inserted."""
    store = MemoryStore(db)
    inserted = 0
    for seed in _SYSTEM_SEEDS:
        exists = (
            db.query(Memory)
            .filter(
                Memory.namespace == seed.namespace,
                Memory.scope == "system",
                Memory.deleted_at.is_(None),
            )
            .first()
        )
        if not exists:
            store.create(seed, created_by="system")
            inserted += 1
    return inserted
