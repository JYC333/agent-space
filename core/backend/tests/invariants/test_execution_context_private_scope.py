"""Invariant: the execution context (user_id) controls access to private memories.

ContextSnapshotPopulator resolves user_id as:
    user_id = run.instructed_by_user_id or "system"    (context_snapshot_populator.py:223)

These tests verify:
1. Owner's run in personal space: private memories ARE included.
2. Different user_id: private memories ARE excluded.
3. No instructed_by_user_id (→ "system"): private memories ARE excluded.
4. ContextSnapshotPopulator wires instructed_by_user_id into ContextBuilder correctly.

Cross-space personal private scope:
    A run in a shared space cannot access private memories from a personal space even
    if the same user instructed both runs.  There is no "include my personal memories
    in this shared-space run" mechanism.  The cross-space block is correct behavior;
    PersonalMemoryGrant is the explicit authorization mechanism for that feature.

See: .agent/reports/space-ownership-visibility-gap-analysis.md § Gap 6a
"""

from __future__ import annotations

from ulid import ULID

from app.memory.read_auth import can_read_memory
from app.memory.retriever import MemoryRetriever
from app.models import AgentVersion, MemoryEntry, SpaceMembership
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _personal_space(db, *, display_name: str = "Personal User"):
    """Create a personal space with one user; returns dict with space_id and user."""
    space_id = _new_id()
    factories.create_test_space(db, space_id=space_id, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=space_id, display_name=display_name)
    db.commit()
    return {"space_id": space_id, "user": user}


def _private_memory(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    content: str = "private-content",
) -> MemoryEntry:
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


def _all_context_memory_ids(pkg) -> set[str]:
    """Collect all memory IDs from all sections of a ContextPackage."""
    return {
        mo.id
        for section in (
            pkg.user_memory,
            pkg.agent_memory,
            pkg.workspace_memory,
            pkg.capability_memory,
            pkg.system_policy,
            pkg.relevant_episodes,
        )
        for mo in section
    }


# ---------------------------------------------------------------------------
# MemoryRetriever level: user_id controls private memory access
# ---------------------------------------------------------------------------


def test_retriever_owner_user_id_includes_private_memory(db):
    """Retriever includes private memories when user_id matches owner_user_id."""
    setup = _personal_space(db)
    private = _private_memory(
        db, space_id=setup["space_id"], owner_user_id=setup["user"].id, content="personal-private"
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=setup["space_id"],
        user_id=setup["user"].id,
    )
    assert private.id in {m.id for m in result.memories}, (
        "Owner's retrieval must include their own private memory"
    )


def test_retriever_mismatched_user_id_excludes_private_memory(db):
    """Retriever excludes private memories when user_id does not match owner_user_id."""
    setup = _personal_space(db)
    private = _private_memory(
        db, space_id=setup["space_id"], owner_user_id=setup["user"].id, content="personal-private"
    )
    db.commit()

    other_user_id = _new_id()
    result = MemoryRetriever(db).retrieve(
        space_id=setup["space_id"],
        user_id=other_user_id,
    )
    assert private.id not in {m.id for m in result.memories}, (
        "Retrieval with a mismatched user_id must exclude the private memory"
    )


def test_retriever_system_user_id_excludes_private_memory(db):
    """Retriever with user_id='system' excludes all private memories.

    'system' is the ContextSnapshotPopulator fallback when run.instructed_by_user_id is None.
    This test confirms that a run without an explicit user context cannot read private data.
    """
    setup = _personal_space(db)
    private = _private_memory(
        db,
        space_id=setup["space_id"],
        owner_user_id=setup["user"].id,
        content="private-for-system-test",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=setup["space_id"],
        user_id="system",  # the fallback value: run.instructed_by_user_id or "system"
    )
    assert private.id not in {m.id for m in result.memories}, (
        "user_id='system' must not include any user's private memories"
    )


# ---------------------------------------------------------------------------
# ContextSnapshotPopulator level: instructed_by_user_id flows into ContextBuilder
# ---------------------------------------------------------------------------


def test_populator_owner_run_includes_private_memory(db):
    """ContextSnapshotPopulator passes run.instructed_by_user_id as user_id to ContextBuilder.

    A run instructed by USER_A in USER_A's personal space must include USER_A's
    private memories in the compiled ContextPackage.
    """
    setup = _personal_space(db, display_name="Owner Run User")
    private = _private_memory(
        db,
        space_id=setup["space_id"],
        owner_user_id=setup["user"].id,
        content="owner-private-in-context",
    )
    run = factories.create_test_run(
        db, space_id=setup["space_id"], user_id=setup["user"].id, commit=True
    )
    assert run.instructed_by_user_id == setup["user"].id, (
        "Precondition: create_test_run must set instructed_by_user_id"
    )
    version = db.query(AgentVersion).filter_by(id=run.agent_version_id).first()

    pkg = ContextSnapshotPopulator(db).populate(run, version)

    assert private.id in _all_context_memory_ids(pkg), (
        "Owner's private memory must appear in the ContextPackage when "
        "run.instructed_by_user_id == owner_user_id"
    )


def test_populator_no_instructed_by_excludes_private_memory(db):
    """When run.instructed_by_user_id is None, private memories are excluded.

    ContextSnapshotPopulator uses "system" as the fallback, which cannot own
    any private memory and thus reads none.
    """
    setup = _personal_space(db, display_name="No Instructed By User")
    private = _private_memory(
        db,
        space_id=setup["space_id"],
        owner_user_id=setup["user"].id,
        content="private-no-instructed-by",
    )
    run = factories.create_test_run(
        db, space_id=setup["space_id"], user_id=setup["user"].id, commit=False
    )
    # Simulate a run with no explicit human instructed_by (system-initiated)
    run.instructed_by_user_id = None
    db.flush()
    db.commit()

    version = db.query(AgentVersion).filter_by(id=run.agent_version_id).first()
    pkg = ContextSnapshotPopulator(db).populate(run, version)

    assert private.id not in _all_context_memory_ids(pkg), (
        "When run.instructed_by_user_id is None (→ 'system'), private memories must "
        "not appear in the ContextPackage"
    )


# ---------------------------------------------------------------------------
# Gap 6a: documented behavior — cross-space private access is NOT possible
# ---------------------------------------------------------------------------


def test_shared_space_run_without_grant_cannot_access_personal_private_memory(db):
    """A run in a shared space cannot read the instructing user's personal-space private memories.

    Even when run.instructed_by_user_id == owner_user_id of a personal-space memory,
    the cross-space boundary in MemoryRetriever prevents inclusion.  The run reads
    only from run.space_id; personal-space memories from a different space are
    structurally inaccessible.

    This is the CORRECT behavior under the current model — it documents an intended
    constraint rather than a bug. PersonalMemoryGrant is the explicit authorization
    mechanism when personal-space private memory must be accessible in a shared-space run.

    See: space-ownership-visibility-gap-analysis.md § Gap 6a
    """
    # User A: personal space with private memory
    personal_id = _new_id()
    factories.create_test_space(db, space_id=personal_id, name="Personal A", space_type="personal")
    user_a = factories.create_test_user(db, space_id=personal_id, display_name="User A Gap6a")
    personal_private = _private_memory(
        db, space_id=personal_id, owner_user_id=user_a.id, content="personal-space-private"
    )

    # Shared space: User A is also a member
    shared_id = _new_id()
    factories.create_test_space(db, space_id=shared_id, name="Household", space_type="household")
    db.add(
        SpaceMembership(
            id=_new_id(), space_id=shared_id, user_id=user_a.id, role="member", status="active"
        )
    )
    db.commit()

    # Run in the SHARED space, instructed by User A
    result = MemoryRetriever(db).retrieve(
        space_id=shared_id,  # run's space
        user_id=user_a.id,   # same user who owns the personal-space private memory
    )
    assert personal_private.id not in {m.id for m in result.memories}, (
        "Expected boundary: a run in the shared space cannot read User A's "
        "personal-space private memory — cross-space boundary is enforced. "
        "This is intentional; PersonalMemoryGrant is the explicit cross-space authorization path."
    )


def test_retrieval_trace_hard_filter_is_populated(db):
    """Retrieval trace always documents the hard-filter configuration for auditability."""
    setup = _personal_space(db)
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=setup["space_id"],
        user_id=setup["user"].id,
    )
    hard_filter = result.retrieval_trace.get("hard_filter", {})
    assert hard_filter.get("cross_space_blocked") is True
    assert hard_filter.get("private_other_user_blocked") is True
    assert hard_filter.get("space_id") == setup["space_id"]
    assert hard_filter.get("user_id") == setup["user"].id
