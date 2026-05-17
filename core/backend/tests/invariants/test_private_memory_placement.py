"""Invariant: private memory placement and access control.

Gap 2b (closed): MemoryStore.create() now rejects visibility=private writes to any
non-personal space (household, team).  The enforcement is at the lowest shared creation
path so all write routes are covered without requiring API-layer changes.

Test structure:
- PLACEMENT ENFORCEMENT tests: assert write-layer rejection for non-personal spaces.
- ACCESS CONTROL tests: verify read-time protection at can_read_memory / MemoryRetriever.
- CORRECT PATTERN tests: verify that personal-space private memory works as intended.

See: .agent/reports/space-ownership-visibility-gap-analysis.md § Gap 2b, Gap 2c
"""

from __future__ import annotations

import pytest
from ulid import ULID

from app.memory.read_auth import can_read_memory
from app.memory.retriever import MemoryRetriever
from app.models import MemoryEntry, Space, SpaceMembership
from app.memory.store import MemoryStore
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_space(db, *, space_type: str = "household"):
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name=f"test-{space_type}", space_type=space_type)
    user = factories.create_test_user(db, space_id=space_id, display_name=f"Owner {space_type}")
    db.commit()
    return {"space_id": space_id, "user": user}


def _add_member(db, *, space_id: str):
    """Add a second user as a member of space_id; returns the new user."""
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal Member", space_type="personal")
    other = factories.create_test_user(db, space_id=personal_id, display_name="Other Member")
    db.add(
        SpaceMembership(
            id=_new_id(), space_id=space_id, user_id=other.id, role="member", status="active"
        )
    )
    db.commit()
    return other


def _insert_private_memory(db, *, space_id: str, owner_user_id: str, content: str) -> MemoryEntry:
    """Insert a private MemoryEntry directly (bypasses store enforcement)."""
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type="user",
        memory_type="semantic",
        content=content,
        status="active",
        visibility="private",
        owner_user_id=owner_user_id,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# PLACEMENT ENFORCEMENT: MemoryStore.create() rejects private writes to non-personal spaces
# ---------------------------------------------------------------------------


def test_space_shared_memory_write_to_team_space_is_allowed(db):
    """MemoryStore.create() allows visibility=space_shared writes to team/household spaces."""
    from app.schemas import MemoryCreate

    setup = _make_space(db, space_type="team")
    mem = MemoryStore(db).create(
        MemoryCreate(
            title="Shared in team",
            space_id=setup["space_id"],
            scope="agent",
            type="semantic",
            content="team-shared",
            visibility="space_shared",
        ),
        acting_user_id=setup["user"].id,
    )
    assert mem.id is not None
    assert mem.visibility == "space_shared"


def test_private_memory_write_to_team_space_is_rejected(db):
    """MemoryStore.create() rejects visibility=private writes to team spaces.

    Phase 4.5 enforcement: private memories may only be stored in personal spaces.
    """
    from app.schemas import MemoryCreate

    setup = _make_space(db, space_type="team")
    space = db.query(Space).filter(Space.id == setup["space_id"]).first()
    assert space.type == "team", "Precondition: space must be non-personal"

    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="Private in team",
                space_id=setup["space_id"],
                scope="user",
                type="semantic",
                content="private-in-team",
                visibility="private",
                owner_user_id=setup["user"].id,
            ),
            acting_user_id=setup["user"].id,
        )


def test_private_memory_write_to_household_space_is_rejected(db):
    """MemoryStore.create() rejects visibility=private writes to household spaces."""
    from app.schemas import MemoryCreate

    setup = _make_space(db, space_type="household")
    space = db.query(Space).filter(Space.id == setup["space_id"]).first()
    assert space.type == "household", "Precondition: space must be non-personal"

    with pytest.raises(ValueError, match="personal"):
        MemoryStore(db).create(
            MemoryCreate(
                title="Private in household",
                space_id=setup["space_id"],
                scope="user",
                type="semantic",
                content="private-in-household",
                visibility="private",
                owner_user_id=setup["user"].id,
            ),
            acting_user_id=setup["user"].id,
        )


# ---------------------------------------------------------------------------
# ACCESS CONTROL: read-time protection holds even when placement is not enforced
# ---------------------------------------------------------------------------


def test_private_memory_in_shared_space_blocked_at_read_time_for_non_owner(db):
    """Access control blocks non-owner reads of misplaced private memory.

    Even when Gap 2b allows a private memory to be stored in a shared space,
    can_read_memory() correctly blocks non-owner reads.  The read-time access
    control is the safety net until write-layer enforcement is added.
    """
    setup = _make_space(db, space_type="household")
    other = _add_member(db, space_id=setup["space_id"])

    mem = _insert_private_memory(
        db,
        space_id=setup["space_id"],
        owner_user_id=setup["user"].id,
        content="shared-space-private",
    )

    # Owner can still read their own memory
    assert can_read_memory(
        mem, user_id=setup["user"].id, space_id=setup["space_id"]
    ) is True, "Owner must be able to read their own private memory"

    # Non-owner is blocked at read time
    assert can_read_memory(
        mem, user_id=other.id, space_id=setup["space_id"]
    ) is False, "Non-owner must be blocked from reading private memory in shared space"


def test_misplaced_private_memory_excluded_from_non_owner_retrieval(db):
    """MemoryRetriever's hard-filter excludes misplaced private memory for non-owners.

    This verifies that the retrieval pipeline (used by ContextBuilder / run context)
    does not expose private memories even when they were written to a shared space.
    """
    setup = _make_space(db, space_type="household")
    other = _add_member(db, space_id=setup["space_id"])

    unique_kw = "placement-gap-kw-9b4d"
    private_mem = _insert_private_memory(
        db,
        space_id=setup["space_id"],
        owner_user_id=setup["user"].id,
        content=f"private content with {unique_kw}",
    )
    db.commit()

    # Non-owner's retrieval (including keyword fallback) must exclude it
    result = MemoryRetriever(db).retrieve(
        space_id=setup["space_id"],
        user_id=other.id,
        query=unique_kw,
    )
    assert private_mem.id not in {m.id for m in result.memories}, (
        "Misplaced private memory must be excluded from non-owner's retrieval result "
        "even via keyword fallback"
    )


# ---------------------------------------------------------------------------
# MemoryStore enforcement: owner_user_id is required for private visibility
# ---------------------------------------------------------------------------


def test_memory_store_requires_owner_user_id_for_private_visibility(db):
    """MemoryStore.create() raises ValueError when visibility=private has no owner.

    This is partial write-layer protection: ensures private memories always have
    an identifiable owner even though placement (space type) is not enforced.
    """
    from app.schemas import MemoryCreate

    setup = _make_space(db, space_type="household")

    with pytest.raises(ValueError, match="owner_user_id"):
        MemoryStore(db).create(
            MemoryCreate(
                space_id=setup["space_id"],
                scope="user",
                type="semantic",
                content="orphan-private",
                visibility="private",
                owner_user_id=None,
            ),
            acting_user_id=None,  # no user context either
        )


# ---------------------------------------------------------------------------
# CORRECT PATTERN: private memory in personal space
# ---------------------------------------------------------------------------


def test_private_memory_in_personal_space_is_accessible_to_owner(db):
    """Private memory in a personal space (correct pattern) is accessible to its owner.

    This test verifies the intended workflow that Phase 4.5 will enforce as
    the only permitted placement for private memories.
    """
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=personal_id, display_name="Personal Owner")
    db.commit()

    space = db.query(Space).filter(Space.id == personal_id).first()
    assert space.type == "personal", "Correct pattern requires personal-type space"

    mem = _insert_private_memory(
        db, space_id=personal_id, owner_user_id=user.id, content="personal-private-correct"
    )
    db.commit()

    assert can_read_memory(mem, user_id=user.id, space_id=personal_id) is True, (
        "Owner must be able to read private memory in personal space"
    )

    result = MemoryRetriever(db).retrieve(space_id=personal_id, user_id=user.id)
    assert mem.id in {m.id for m in result.memories}, (
        "Personal-space private memory must appear in owner's retrieval result"
    )


def test_personal_space_private_memory_not_in_other_space_retrieval(db):
    """Personal-space private memory does not appear in retrieval for a different space.

    This is both the cross-space boundary test and the 'correct pattern' verification:
    when private memory is correctly placed in a personal space, it is invisible
    to all other spaces regardless of user context.
    """
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=personal_id, display_name="Personal Owner X")

    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Shared X", space_type="household")
    db.add(
        SpaceMembership(
            id=_new_id(), space_id=shared_id, user_id=user.id, role="member", status="active"
        )
    )
    db.commit()

    personal_private = _insert_private_memory(
        db, space_id=personal_id, owner_user_id=user.id, content="personal-correct-private"
    )
    db.commit()

    # Even with user.id as user_id, the shared-space retrieval must not include
    # personal-space memory (cross-space hard filter)
    result = MemoryRetriever(db).retrieve(space_id=shared_id, user_id=user.id)
    assert personal_private.id not in {m.id for m in result.memories}, (
        "Personal-space private memory must not appear in shared-space retrieval "
        "even when user_id matches the owner"
    )
