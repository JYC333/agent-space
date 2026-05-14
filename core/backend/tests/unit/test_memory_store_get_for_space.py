"""Unit checks for MemoryStore space-scoped lookup (Phase 5.1)."""

from __future__ import annotations

from app.memory.store import MemoryStore
from tests.support import factories


def test_get_for_space_returns_none_when_space_mismatch(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="x",
        owner_user_id=ua.id,
        commit=False,
    )
    db.flush()
    store = MemoryStore(db)
    assert store.get_for_space(b, mem.id) is None
    assert store.get_for_space(a, mem.id) is not None
