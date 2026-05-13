"""System-scoped memory is space-owned (subject_user_id NULL); per-space seeds and ACL."""

from __future__ import annotations

import pytest

from app.memory.seeder import seed_system_memories_for_space
from app.memory.store import MemoryStore
from app.models import MemoryEntry
from app.schemas import MemoryCreate
from tests.conftest import SPACE, USER, ensure_space

pytestmark = pytest.mark.canonical


def test_two_spaces_each_get_distinct_system_memory_rows(db):
    """Same acting user can create two spaces; each gets its own three system policy rows."""
    s1, s2 = "space_sys_a", "space_sys_b"
    ensure_space(db, s1)
    ensure_space(db, s2)
    assert seed_system_memories_for_space(db, s1) == 3
    assert seed_system_memories_for_space(db, s2) == 3
    assert seed_system_memories_for_space(db, s1) == 0
    assert seed_system_memories_for_space(db, s2) == 0

    rows = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.scope == "system", MemoryEntry.deleted_at.is_(None))
        .all()
    )
    by_space: dict[str, set[str]] = {}
    for m in rows:
        if m.space_id in (s1, s2):
            by_space.setdefault(m.space_id, set()).add(m.namespace or "")
    assert by_space[s1] == {
        "system.memory_policy",
        "system.context_policy",
        "system.capability_policy",
    }
    assert by_space[s2] == by_space[s1]
    for m in rows:
        if m.space_id in (s1, s2):
            assert m.subject_user_id is None


def test_get_memory_denies_cross_space_for_user_row(client, db):
    """A memory row in space A must not be readable when the request context is space B."""
    ensure_space(db, "other_space_for_mem_acl")
    store = MemoryStore(db)
    mem = store.create(
        MemoryCreate(
            title="Space-shared user note",
            content="x",
            type="semantic",
            scope="user",
            namespace="user.acl_test_only",
            visibility="space_shared",
            space_id=SPACE,
            subject_user_id=None,
            owner_user_id=None,
        ),
        acting_user_id=USER,
    )
    qs_wrong = f"space_id=other_space_for_mem_acl&user_id={USER}"
    r = client.get(f"/api/v1/memory/{mem.id}?{qs_wrong}")
    assert r.status_code == 404

    qs_ok = f"space_id={SPACE}&user_id={USER}"
    r2 = client.get(f"/api/v1/memory/{mem.id}?{qs_ok}")
    assert r2.status_code == 200
    assert r2.json()["space_id"] == SPACE
