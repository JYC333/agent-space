"""Phase C security invariant tests: concurrency, failure paths, and snapshot leak prevention.

These tests verify:
1. Concurrency: at most one resolver can consume an active grant (atomic transition).
2. Failure path: if resolver fails after cross-space read, grant becomes 'failed', not 'active'.
3. Snapshot leak: shared ContextSnapshot fields never contain personal memory raw text,
   generated summary, or personal memory IDs after a valid grant context build.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from ulid import ULID

from app.models import ContextSnapshot, MemoryEntry, PersonalMemoryGrant, SpaceMembership
from app.personal_memory_grants.resolver import (
    begin_consuming_grant,
    find_active_grant_for_run,
    mark_grant_failed,
    resolve_personal_memory_context_for_run,
    retrieve_eligible_memories,
)
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _personal_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=sid, display_name="Personal User")
    db.commit()
    return sid, user


def _team_space(db):
    sid = _new_id()
    factories.create_test_space(db, space_id=sid, name="Team", space_type="team")
    user = factories.create_test_user(db, space_id=sid, display_name="Team User")
    db.commit()
    return sid, user


def _add_member(db, *, space_id: str, user_id: str) -> None:
    db.add(SpaceMembership(
        id=_new_id(), space_id=space_id, user_id=user_id, role="member", status="active"
    ))


def _private_memory(
    db,
    *,
    space_id: str,
    owner_user_id: str,
    content: str = "private-content",
    sensitivity_level: str = "normal",
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
        sensitivity_level=sensitivity_level,
    )
    db.add(m)
    db.flush()
    return m


def _active_grant(
    db,
    *,
    granting_user_id: str,
    personal_space_id: str,
    target_space_id: str,
    target_run_id: str,
    expires_in_seconds: int = 3600,
) -> PersonalMemoryGrant:
    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=granting_user_id,
        personal_space_id=personal_space_id,
        target_space_id=target_space_id,
        target_run_id=target_run_id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=None,
        read_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )
    db.add(grant)
    db.flush()
    return grant


# ---------------------------------------------------------------------------
# C1: Concurrency — at most one caller can consume a grant
# ---------------------------------------------------------------------------


def test_concurrent_resolver_calls_at_most_one_consumes_grant(db):
    """Two sequential begin_consuming_grant calls on the same active grant: only one succeeds.

    Uses service-level (not HTTP) calls.  SQLite serializes writes, so we test the
    begin_consuming_grant conditional-UPDATE logic directly.  The first call must
    claim the grant (rowcount=1); the second must be rejected (rowcount=0).
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    now = datetime.now(UTC)

    # First attempt: should succeed
    claimed_first = begin_consuming_grant(db, grant_id=grant.id, now=now)
    db.commit()
    assert claimed_first is True, "First begin_consuming_grant call must succeed"

    # Second attempt on the same grant: status is now 'consuming', not 'active'
    claimed_second = begin_consuming_grant(db, grant_id=grant.id, now=now)
    assert claimed_second is False, (
        "Second begin_consuming_grant call must fail — grant is no longer 'active'"
    )

    db.refresh(grant)
    assert grant.status == "consuming", (
        "Grant should remain in 'consuming' state after second attempt"
    )


def test_two_resolve_calls_at_most_one_produces_personal_context(db):
    """Two sequential resolve_personal_memory_context_for_run calls: only first produces context.

    Simulates the race condition where two context builders try to consume the same grant.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    result1 = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()
    result2 = resolve_personal_memory_context_for_run(db, run=run)

    successes = sum(1 for r in (result1, result2) if r.has_personal_context)
    assert successes == 1, (
        f"Exactly one of two sequential resolver calls should produce personal context; "
        f"got {successes}"
    )


# ---------------------------------------------------------------------------
# C2: Failure path — grant must not return to 'active' after cross-space read
# ---------------------------------------------------------------------------


def test_grant_becomes_failed_after_summary_generation_failure(db):
    """If summary generation fails after cross-space memory read, grant becomes 'failed'.

    The grant must not return to 'active'.  We simulate this by directly calling
    begin_consuming_grant (claiming the grant) and then mark_grant_failed.
    """
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    now = datetime.now(UTC)

    # Claim the grant (simulates entering cross-space read path)
    claimed = begin_consuming_grant(db, grant_id=grant.id, now=now)
    db.commit()
    assert claimed

    # Simulate summary generation failure (after cross-space read)
    mark_grant_failed(
        db,
        grant_id=grant.id,
        run_id=run.id,
        failure_stage="summary_generation",
        source_space_id=grant.personal_space_id,
        target_space_id=grant.target_space_id,
    )
    db.commit()

    db.refresh(grant)
    assert grant.status == "failed", (
        f"Grant must be 'failed' after summary_generation failure; got {grant.status!r}"
    )
    assert grant.failure_stage == "summary_generation"
    assert grant.failed_at is not None

    # Grant must not be findable as active
    found = find_active_grant_for_run(
        db, run_id=run.id, granting_user_id=user.id,
        target_space_id=team_id, now=datetime.now(UTC),
    )
    assert found is None, "Failed grant must not be returned as active"


def test_resolve_returns_no_context_on_memory_retrieval_failure(db, monkeypatch):
    """If memory retrieval raises, resolver returns no context and marks grant failed."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(db, space_id=personal_id, owner_user_id=user.id)
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    grant = _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    import app.personal_memory_grants.resolver as resolver_mod

    def _failing_retrieve(*args, **kwargs):
        raise RuntimeError("simulated retrieval failure")

    monkeypatch.setattr(resolver_mod, "retrieve_eligible_memories", _failing_retrieve)

    result = resolve_personal_memory_context_for_run(db, run=run)
    db.commit()

    assert not result.has_personal_context, (
        "Resolver must return no personal context when memory retrieval fails"
    )

    db.refresh(grant)
    assert grant.status == "failed", (
        f"Grant must be 'failed' after retrieval failure; got {grant.status!r}"
    )
    assert grant.failure_stage == "memory_retrieval"

    # Grant must not be findable as active again
    found = find_active_grant_for_run(
        db, run_id=run.id, granting_user_id=user.id,
        target_space_id=team_id, now=datetime.now(UTC),
    )
    assert found is None


# ---------------------------------------------------------------------------
# C3: Snapshot leak — personal content must not appear in shared ContextSnapshot
# ---------------------------------------------------------------------------


def test_snapshot_compiled_prefix_does_not_contain_personal_memory_content(db):
    """After a valid grant context build, compiled_prefix_text must not contain personal memory."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="UNIQUE_PERSONAL_SECRET_ALPHA_12345",
    )
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    from app.models import AgentVersion
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    assert version is not None

    pkg = ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).first()
    assert snap is not None

    secret = "UNIQUE_PERSONAL_SECRET_ALPHA_12345"
    assert secret not in (snap.compiled_prefix_text or ""), (
        "compiled_prefix_text must not contain personal memory raw content"
    )
    assert secret not in (snap.compiled_tail_text or ""), (
        "compiled_tail_text must not contain personal memory raw content"
    )

    # Also verify personal_context_block is in the ephemeral pkg but NOT in snapshot
    assert pkg.personal_context_block, "pkg should have a non-empty personal_context_block"
    assert pkg.personal_context_block not in (snap.compiled_prefix_text or "")
    assert pkg.personal_context_block not in (snap.compiled_tail_text or "")


def test_snapshot_source_refs_do_not_contain_personal_memory_ids(db):
    """After a valid grant context build, source_refs_json must not contain personal memory IDs."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)

    private_mem = _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
    )
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    from app.models import AgentVersion
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).first()
    source_refs_str = str(snap.source_refs_json or [])

    assert private_mem.id not in source_refs_str, (
        "source_refs_json must not contain personal memory IDs"
    )

    # Safe grant metadata should be present
    grant_refs = [
        r for r in (snap.source_refs_json or [])
        if r.get("source_type") == "personal_memory_grant"
    ]
    assert len(grant_refs) == 1
    ref = grant_refs[0]
    assert ref["raw_memory_included"] is False
    assert ref["personal_summary_persisted"] is False


def test_snapshot_retrieval_trace_does_not_contain_personal_summary(db):
    """After a valid grant context build, retrieval_trace_json contains only safe grant metadata."""
    personal_id, user = _personal_space(db)
    team_id, _team_user = _team_space(db)
    _add_member(db, space_id=team_id, user_id=user.id)
    _private_memory(
        db, space_id=personal_id, owner_user_id=user.id,
        content="TRACE_LEAK_CHECK_SENTINEL_XYZ",
    )
    db.commit()

    run = factories.create_test_run(db, space_id=team_id, user_id=user.id, commit=True)
    _active_grant(
        db,
        granting_user_id=user.id,
        personal_space_id=personal_id,
        target_space_id=team_id,
        target_run_id=run.id,
    )
    db.commit()

    from app.models import AgentVersion
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).first()
    trace_str = str(snap.retrieval_trace_json or [])

    assert "TRACE_LEAK_CHECK_SENTINEL_XYZ" not in trace_str, (
        "retrieval_trace_json must not contain personal memory raw content"
    )

    # Grant trace should be present with safe fields
    traces = snap.retrieval_trace_json or []
    assert len(traces) >= 1
    trace = traces[0]
    grant_trace = trace.get("personal_memory_grant")
    assert grant_trace is not None, "retrieval_trace should include personal_memory_grant metadata"
    assert grant_trace["raw_memory_included"] is False
    assert grant_trace["personal_summary_persisted"] is False
    assert grant_trace["memory_count"] >= 1
