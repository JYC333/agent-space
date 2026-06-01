"""Invariant: private memories in a shared/team space are not leaked to other space members.

Documents and verifies that MemoryRetriever's hard-filter correctly blocks non-owner
users from reading private memories via all retrieval paths (symbol match, keyword
fallback, graph expansion).

Key invariants asserted here:
- can_read_memory() returns False when user_id != owner_user_id for private visibility.
- MemoryRetriever excludes private memories for non-owner runs in shared spaces.
- A run with user_id='system' (→ instructed_by_user_id=None fallback) reads no private memory.
- Keyword fallback cannot re-introduce blocked private memory through ILIKE matching.
- Space-shared memories (legitimate shared content) are still accessible to all members.

Private placement defense-in-depth:
    The correctness of access control does NOT depend on placement enforcement, but
    placement enforcement is still needed as defense-in-depth for historical or direct
    database rows.

See: .agent/reports/space-ownership-visibility-gap-analysis.md § Gap 2c, Gap 10b
"""

from __future__ import annotations
import uuid


from app.memory.read_auth import can_read_memory
from app.memory.retriever import MemoryRetriever
from app.models import MemoryEntry, SpaceMembership
from tests.support import factories


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shared_space_with_two_users(db):
    """Create a household space with User A and User B as members.

    User A is the space owner; User B is an invited member from a separate
    personal space.  This mirrors the two-person dogfooding setup.
    """
    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Household", space_type="household")
    user_a = factories.create_test_user(db, space_id=shared_id, display_name="User A Team")

    # User B has a personal space as their primary space but is also a member of shared_id.
    personal_b_id = _new_id()
    factories.create_test_space(db, space_id=personal_b_id, name="Personal B", space_type="personal")
    user_b = factories.create_test_user(db, space_id=personal_b_id, display_name="User B Team")
    db.add(
        SpaceMembership(
            id=_new_id(),
            space_id=shared_id,
            user_id=user_b.id,
            role="member",
            status="active",
        )
    )
    db.commit()
    return {"shared_id": shared_id, "user_a": user_a, "user_b": user_b}


def _private_memory(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    content: str = "owner-private-content",
) -> MemoryEntry:
    """Insert a private MemoryEntry directly.  Caller must commit before MemoryRetriever queries."""
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
        subject_user_id=owner_user_id,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Unit: can_read_memory() visibility enforcement
# ---------------------------------------------------------------------------


def test_can_read_memory_blocks_non_owner_in_shared_space(db):
    """can_read_memory() returns False when user_id != owner_user_id and visibility=private."""
    pair = _shared_space_with_two_users(db)
    mem = _private_memory(db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id)

    assert can_read_memory(mem, user_id=pair["user_b"].id, space_id=pair["shared_id"]) is False, (
        "Private memory owned by user_a must not be readable by user_b"
    )


def test_can_read_memory_allows_owner_in_shared_space(db):
    """can_read_memory() returns True for the owner regardless of space type."""
    pair = _shared_space_with_two_users(db)
    mem = _private_memory(db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id)

    assert can_read_memory(mem, user_id=pair["user_a"].id, space_id=pair["shared_id"]) is True, (
        "Owner must be able to read their own private memory"
    )


def test_can_read_memory_blocks_system_user_id_for_private_memory(db):
    """can_read_memory() returns False when user_id='system' for private visibility.

    'system' is the fallback user_id used by ContextSnapshotPopulator when
    run.instructed_by_user_id is None:
        user_id = run.instructed_by_user_id or 'system'
    """
    pair = _shared_space_with_two_users(db)
    mem = _private_memory(db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id)

    assert can_read_memory(mem, user_id="system", space_id=pair["shared_id"]) is False, (
        "Private memory must not be readable via the 'system' fallback user_id"
    )


def test_can_read_memory_blocks_empty_string_user_id_for_private_memory(db):
    """can_read_memory() returns False for user_id='' (hypothetical empty user)."""
    pair = _shared_space_with_two_users(db)
    mem = _private_memory(db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id)

    assert can_read_memory(mem, user_id="", space_id=pair["shared_id"]) is False, (
        "Private memory must not be readable with an empty user_id"
    )


# ---------------------------------------------------------------------------
# MemoryRetriever: hard-filter blocks private memories for non-owners
# ---------------------------------------------------------------------------


def test_retriever_excludes_private_memory_for_non_owner_symbol_match(db):
    """MemoryRetriever symbol-match stage does not include private memories for non-owners."""
    pair = _shared_space_with_two_users(db)
    private_mem = _private_memory(
        db,
        space_id=pair["shared_id"],
        owner_user_id=pair["user_a"].id,
        content="user-a-private-symbol",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"],
        user_id=pair["user_b"].id,
    )
    ids = {m.id for m in result.memories}
    assert private_mem.id not in ids, (
        "Private memory owned by user_a must not appear in user_b's retrieval result"
    )
    source_ids = {r["source_id"] for r in result.source_refs if r.get("source_type") == "memory"}
    assert private_mem.id not in source_ids, (
        "Blocked private memory must not appear in source_refs"
    )


def test_retriever_keyword_fallback_cannot_expose_private_memory_to_non_owner(db):
    """Keyword fallback (ILIKE content match) cannot expose private memory to non-owner.

    This is the most important regression test: even when the private memory content
    exactly matches the retrieval query, the hard-filter blocks it before it can
    re-enter the result set.
    """
    pair = _shared_space_with_two_users(db)
    unique_keyword = "unique-private-kw-a7f3e9"
    private_mem = _private_memory(
        db,
        space_id=pair["shared_id"],
        owner_user_id=pair["user_a"].id,
        content=f"content containing {unique_keyword}",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"],
        user_id=pair["user_b"].id,
        query=unique_keyword,  # deliberately matches private memory content via ILIKE
    )
    ids = {m.id for m in result.memories}
    assert private_mem.id not in ids, (
        "Keyword fallback must not re-introduce private memory blocked by hard-filter"
    )


def test_retriever_includes_private_memory_for_owner(db):
    """MemoryRetriever includes private memories when user_id matches owner_user_id.

    Counterpart to the above: confirms the security boundary does not accidentally
    block legitimate owner access.
    """
    pair = _shared_space_with_two_users(db)
    private_mem = _private_memory(
        db,
        space_id=pair["shared_id"],
        owner_user_id=pair["user_a"].id,
        content="user-a-private-owned",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"],
        user_id=pair["user_a"].id,
    )
    ids = {m.id for m in result.memories}
    assert private_mem.id in ids, (
        "Owner must be able to retrieve their own private memory"
    )


def test_retriever_with_system_user_id_excludes_all_private_memories(db):
    """MemoryRetriever with user_id='system' excludes all private memories.

    This corresponds to the ContextSnapshotPopulator path when
    run.instructed_by_user_id is None.  Both users' private memories must be
    excluded regardless of who owns them.
    """
    pair = _shared_space_with_two_users(db)
    private_a = _private_memory(
        db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id, content="a-private"
    )
    private_b = _private_memory(
        db, space_id=pair["shared_id"], owner_user_id=pair["user_b"].id, content="b-private"
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"],
        user_id="system",  # ContextSnapshotPopulator fallback when instructed_by_user_id is None
    )
    ids = {m.id for m in result.memories}
    assert private_a.id not in ids, "system user must not read user_a's private memory"
    assert private_b.id not in ids, "system user must not read user_b's private memory"


def test_retriever_multiple_private_owners_only_owner_reads_own(db):
    """Each user can only read their own private memories, not any other user's."""
    pair = _shared_space_with_two_users(db)
    private_a = _private_memory(
        db, space_id=pair["shared_id"], owner_user_id=pair["user_a"].id, content="a-only"
    )
    private_b = _private_memory(
        db, space_id=pair["shared_id"], owner_user_id=pair["user_b"].id, content="b-only"
    )
    db.commit()

    result_a = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"], user_id=pair["user_a"].id
    )
    ids_a = {m.id for m in result_a.memories}
    assert private_a.id in ids_a, "user_a should see their own private memory"
    assert private_b.id not in ids_a, "user_a must not see user_b's private memory"

    result_b = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"], user_id=pair["user_b"].id
    )
    ids_b = {m.id for m in result_b.memories}
    assert private_b.id in ids_b, "user_b should see their own private memory"
    assert private_a.id not in ids_b, "user_b must not see user_a's private memory"


def test_retriever_trace_confirms_hard_filter_private_blocked(db):
    """The retrieval_trace explicitly documents that private_other_user_blocked=True."""
    pair = _shared_space_with_two_users(db)

    result = MemoryRetriever(db).retrieve(
        space_id=pair["shared_id"],
        user_id=pair["user_b"].id,
    )
    hard_filter = result.retrieval_trace["hard_filter"]
    assert hard_filter["private_other_user_blocked"] is True, (
        "Retrieval trace must document private_other_user_blocked=True for auditability"
    )
    assert hard_filter["cross_space_blocked"] is True


# ---------------------------------------------------------------------------
# Positive test: space_shared memories are not over-blocked
# ---------------------------------------------------------------------------


def test_space_shared_memory_is_accessible_to_all_members(db):
    """space_shared visibility memories are accessible to all space members.

    Verifies that the hard-filter does not accidentally block legitimately
    shared content while correctly blocking private content.
    """
    pair = _shared_space_with_two_users(db)
    shared_mem = MemoryEntry(
        id=_new_id(),
        space_id=pair["shared_id"],
        scope_type="space",
        memory_type="semantic",
        content="shared-team-fact",
        status="active",
        visibility="space_shared",
        owner_user_id=pair["user_a"].id,
    )
    db.add(shared_mem)
    db.commit()

    # Both user_a and user_b should see the shared memory
    for user, label in [(pair["user_a"], "user_a"), (pair["user_b"], "user_b")]:
        result = MemoryRetriever(db).retrieve(
            space_id=pair["shared_id"],
            user_id=user.id,
            query="shared-team-fact",
        )
        ids = {m.id for m in result.memories}
        assert shared_mem.id in ids, (
            f"{label}: space_shared memory must be accessible to all space members"
        )
