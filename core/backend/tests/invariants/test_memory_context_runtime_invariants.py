"""
Invariant tests for the Memory / Context Runtime slice.

Tests verify:
1. condenser_cannot_create_active_memory_entry
   — SessionCondenser.condense() and .get_latest() never create MemoryEntry or Proposal rows.

2. strict_active_memory_write_boundary
   — MemoryStore.create() raises PermissionError directly (not internal path).
   — Active MemoryEntry only via ProposalApplyService.apply() with source_proposal_id set.
   — memory_update creates new active version, supersedes old, links to proposal.
   — memory_archive goes through ProposalApplyService, no hard-delete.
   — create_system_seed_memory() sets source_trust='internal_system' (bootstrap exception).

3. context_compiler_records_budget_trace
   — ContextCompiler returns a budget_trace with mandatory/capped/dropped keys.
   — CompiledContext.budget_trace["mandatory"] always contains "task".
   — ContextSnapshotPopulator.token_budget_json is the run-level stable_prefix/tail
     budget metric — distinct from ContextCompiler.budget_trace (not yet persisted).

4. dirty_digest_can_be_refreshed_explicitly
   — mark_digest_dirty() → status="dirty"; ContextDigestRefreshService.refresh() → status="active".

5. automation_not_implemented_in_this_slice
   — No AutomationTrigger or AutomationSchedule table exists in the ORM metadata.
"""

from __future__ import annotations
import uuid

import pytest

from app.memory.context_compiler import ContextCompiler, TargetFormat, _MANDATORY_SECTIONS
from app.memory.digest_refresh import ContextDigestRefreshService
from app.memory.digest_service import ContextDigestService
from app.models import ContextDigest, MemoryEntry, Policy, Proposal
from app.sessions.condenser import SessionCondenser
from tests.support import factories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _active_memory(db, *, space_id, scope_type="workspace", workspace_id=None, content="test") -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type=scope_type,
        memory_type="semantic",
        content=content,
        status="active",
        visibility="space_shared",
        workspace_id=workspace_id,
    )
    db.add(m)
    db.flush()
    return m


def _active_policy(db, *, space_id, name="test-pol") -> Policy:
    p = Policy(
        id=_new_id(),
        space_id=space_id,
        name=name,
        domain="memory",
        policy_json={"allow": "all"},
        enabled=True,
        status="active",
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# 1. Condenser cannot create active MemoryEntry
# ---------------------------------------------------------------------------


def test_condenser_condense_creates_no_memory_entry(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # Create a session with messages via the factory
    from app.models import Session as SessionModel, Message
    session = SessionModel(
        id=_new_id(),
        space_id=space_id,
        user_id=ua.id,
        status="active",
    )
    db.add(session)
    db.flush()

    msg = Message(
        id=_new_id(),
        space_id=space_id,
        session_id=session.id,
        user_id=ua.id,
        role="user",
        content="Please summarise the architecture of this system.",
    )
    db.add(msg)
    db.flush()

    before_memory = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    before_proposal = db.query(Proposal).filter(Proposal.space_id == space_id).count()

    condenser = SessionCondenser(db)
    summary = condenser.condense(session.id, space_id, user_id=ua.id)

    after_memory = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    after_proposal = db.query(Proposal).filter(Proposal.space_id == space_id).count()

    assert summary is not None, "condense() must return a SessionSummary"
    assert summary.status == "active"
    assert after_memory == before_memory, "condense() must not create MemoryEntry rows"
    assert after_proposal == before_proposal, "condense() must not create Proposal rows"


def test_condenser_get_latest_creates_no_memory_entry(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    from app.models import Session as SessionModel
    session = SessionModel(
        id=_new_id(),
        space_id=space_id,
        user_id=ua.id,
        status="active",
    )
    db.add(session)
    db.flush()

    before_memory = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()

    condenser = SessionCondenser(db)
    result = condenser.get_latest(session.id, space_id)  # no summary yet

    after_memory = db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id).count()
    assert result is None, "get_latest() returns None when no summary exists"
    assert after_memory == before_memory, "get_latest() must not create MemoryEntry rows"


def test_condenser_versioning_supersedes_previous(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    from app.models import Session as SessionModel, Message
    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="hello"))
    db.flush()

    condenser = SessionCondenser(db)
    s1 = condenser.condense(session.id, space_id)
    assert s1.version == 1

    s2 = condenser.condense(session.id, space_id)
    assert s2.version == 2, "Second condense must bump version"
    assert s2.status == "active"

    db.expire_all()
    s1_row = db.query(__import__("app.models", fromlist=["SessionSummary"]).SessionSummary).filter_by(id=s1.id).one()
    assert s1_row.status == "superseded", "Previous summary must be superseded"


def test_condenser_filters_messages_by_space_id(db, cross_space_pair_db):
    """condense() queries messages scoped to space_id — messages from other spaces not included."""
    from app.models import Session as SessionModel, Message, SessionSummary

    space_a = cross_space_pair_db["space_a_id"]
    space_b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    session_a = SessionModel(id=_new_id(), space_id=space_a, user_id=ua.id, status="active")
    session_b = SessionModel(id=_new_id(), space_id=space_b, user_id=ub.id, status="active")
    db.add(session_a)
    db.add(session_b)
    db.flush()

    # Add messages to session_a only
    for i in range(3):
        db.add(Message(
            id=_new_id(), space_id=space_a, session_id=session_a.id,
            user_id=ua.id, role="user", content=f"space_a message {i}",
        ))
    db.flush()

    condenser = SessionCondenser(db)
    summary_a = condenser.condense(session_a.id, space_a, user_id=ua.id)

    assert summary_a.source_message_count == 3
    # Condensing session_b (different space, no messages) should not see space_a messages
    summary_b = condenser.condense(session_b.id, space_b, user_id=ub.id)
    assert summary_b.source_message_count == 0, (
        "condenser must filter messages by space_id — space_a messages must not appear in space_b summary"
    )


def test_condenser_populates_source_range_fields(db, cross_space_pair_db):
    """source_first_message_id, source_last_message_id, source_message_count are populated."""
    from app.models import Session as SessionModel, Message

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()

    msg1 = Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="first")
    msg2 = Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="assistant", content="second")
    msg3 = Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="third")
    db.add(msg1)
    db.add(msg2)
    db.add(msg3)
    db.flush()

    condenser = SessionCondenser(db)
    summary = condenser.condense(session.id, space_id, user_id=ua.id)

    assert summary.source_message_count == 3
    assert summary.source_first_message_id == msg1.id
    assert summary.source_last_message_id == msg3.id


def test_condenser_populates_summary_json(db, cross_space_pair_db):
    """summary_json is populated with structured metadata: role_counts, top_keywords, source_range."""
    from app.models import Session as SessionModel, Message

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()

    db.add(Message(
        id=_new_id(), space_id=space_id, session_id=session.id,
        user_id=ua.id, role="user", content="analyse memory architecture performance improvements",
    ))
    db.flush()

    condenser = SessionCondenser(db)
    summary = condenser.condense(session.id, space_id, user_id=ua.id)

    assert summary.summary_json is not None, "summary_json must be populated"
    sj = summary.summary_json
    assert "role_counts" in sj
    assert "top_keywords" in sj
    assert "source_range" in sj
    assert "condenser_version" in sj
    assert sj["role_counts"]["user"] == 1
    assert sj["role_counts"]["assistant"] == 0
    sr = sj["source_range"]
    assert sr["message_count"] == 1


def test_context_builder_loads_only_active_session_summary(db, cross_space_pair_db):
    """ContextBuilder loads only the latest active SessionSummary, not superseded ones."""
    from app.models import Session as SessionModel, Message, SessionSummary
    from app.memory.context_builder import ContextBuilder

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="hello world"))
    db.flush()

    condenser = SessionCondenser(db)
    s1 = condenser.condense(session.id, space_id, user_id=ua.id)
    s2 = condenser.condense(session.id, space_id, user_id=ua.id)  # supersedes s1

    db.expire_all()

    pkg = ContextBuilder(db).build(
        space_id=space_id,
        user_id=ua.id,
        session_id=session.id,
    )

    # Only the latest active summary should be in the package.
    assert len(pkg.recent_session_summary) == 1
    loaded = pkg.recent_session_summary[0]
    assert loaded["version"] == s2.version, "ContextBuilder must load the active (latest) summary"

    # The dynamic_tail source_ref should point to the active summary.
    summary_refs = [r for r in pkg.dynamic_tail_refs if r.get("source_type") == "session_summary"]
    assert len(summary_refs) == 1
    assert summary_refs[0]["source_id"] == s2.id
    assert summary_refs[0]["version"] == s2.version
    assert summary_refs[0]["derived_context"] is True


def test_context_builder_retrieval_trace_records_session_summary_metadata(db, cross_space_pair_db):
    """ContextBuilder retrieval_trace includes session_summary used/id/version when loaded."""
    from app.models import Session as SessionModel, Message
    from app.memory.context_builder import ContextBuilder

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="trace test"))
    db.flush()

    condenser = SessionCondenser(db)
    summary = condenser.condense(session.id, space_id, user_id=ua.id)

    pkg = ContextBuilder(db).build(
        space_id=space_id,
        user_id=ua.id,
        session_id=session.id,
    )

    trace = pkg.retrieval_trace or {}
    ss_trace = trace.get("session_summary", {})
    assert ss_trace.get("session_summary_used") is True
    assert ss_trace.get("session_summary_id") == summary.id
    assert ss_trace.get("session_summary_version") == summary.version
    assert ss_trace.get("session_summary_fallback_reason") is None


def test_context_builder_no_session_id_reports_fallback_reason(db, cross_space_pair_db):
    """When no session_id is provided, retrieval_trace records session_summary_used=False."""
    from app.memory.context_builder import ContextBuilder

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    pkg = ContextBuilder(db).build(
        space_id=space_id,
        user_id=ua.id,
    )

    trace = pkg.retrieval_trace or {}
    ss_trace = trace.get("session_summary", {})
    assert ss_trace.get("session_summary_used") is False


def test_context_builder_session_summary_appears_in_source_refs(db, cross_space_pair_db):
    """ContextBuilder includes session_summary in source_refs, not just dynamic_tail_refs."""
    from app.models import Session as SessionModel, Message
    from app.memory.context_builder import ContextBuilder

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="source refs test"))
    db.flush()

    summary = SessionCondenser(db).condense(session.id, space_id, user_id=ua.id)

    pkg = ContextBuilder(db).build(space_id=space_id, user_id=ua.id, session_id=session.id)

    # Must appear in source_refs
    source_summary_refs = [r for r in (pkg.source_refs or []) if r.get("source_type") == "session_summary"]
    assert len(source_summary_refs) == 1, "session_summary must appear in source_refs"
    assert source_summary_refs[0]["source_id"] == summary.id
    assert source_summary_refs[0]["derived_context"] is True

    # Must also appear in dynamic_tail_refs
    tail_summary_refs = [r for r in (pkg.dynamic_tail_refs or []) if r.get("source_type") == "session_summary"]
    assert len(tail_summary_refs) == 1, "session_summary must appear in dynamic_tail_refs"
    assert tail_summary_refs[0]["source_id"] == summary.id


def test_session_condenser_second_condense_supersedes_first(db, cross_space_pair_db):
    """SessionCondenser.condense() marks the previous active summary as superseded."""
    from app.models import Session as SessionModel, Message, SessionSummary

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=space_id, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=space_id, session_id=session.id, user_id=ua.id, role="user", content="test message"))
    db.flush()

    condenser = SessionCondenser(db)
    s1 = condenser.condense(session.id, space_id, user_id=ua.id)
    assert s1.status == "active"

    s2 = condenser.condense(session.id, space_id, user_id=ua.id)
    assert s2.status == "active"
    assert s2.version > s1.version

    db.expire_all()
    s1_refreshed = db.query(SessionSummary).filter(SessionSummary.id == s1.id).first()
    assert s1_refreshed.status == "superseded", "Previous active summary must be superseded"

    active_count = (
        db.query(SessionSummary)
        .filter(SessionSummary.session_id == session.id, SessionSummary.status == "active")
        .count()
    )
    assert active_count == 1, "Exactly one active summary must exist per session"


# ---------------------------------------------------------------------------
# 2. Strict active memory write boundary
# ---------------------------------------------------------------------------


def test_memory_store_rejects_direct_active_memory_create(db, cross_space_pair_db):
    """MemoryStore.create() must raise PermissionError — not silently create active memory."""
    from app.memory.store import MemoryStore
    from app.schemas import MemoryCreate

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    mc = MemoryCreate(
        space_id=space_id,
        title="attempted direct write",
        type="semantic",
        content="should be rejected",
        scope="workspace",
        visibility="space_shared",
    )
    store = MemoryStore(db)
    with pytest.raises(PermissionError, match="MemoryStore.create"):
        store.create(mc, acting_user_id=ua.id)


def test_proposal_apply_service_creates_active_memory_with_source_proposal_id(db, cross_space_pair_db):
    """ProposalApplyService.apply() creates active MemoryEntry with source_proposal_id set."""
    from app.memory.apply_service import ProposalApplyService

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)

    prop = Proposal(
        id=_new_id(),
        space_id=space_id,
        workspace_id=ws.id,
        proposal_type="memory_create",
        status="pending",
        title="test memory via proposal",
        payload_json={
            "target_scope": "workspace",
            "proposed_content": "approved knowledge",
            "visibility": "space_shared",
            "provenance_entries": [
                {"source_type": "user_confirmed", "source_id": ua.id, "source_trust": "user_confirmed"}
            ],
        },
    )
    db.add(prop)
    db.flush()

    result = ProposalApplyService(db).apply(prop, user_id=ua.id, bypass_source_monitoring=True)
    db.flush()

    assert result.memory is not None
    assert result.memory.status == "active"
    assert result.memory.source_proposal_id == prop.id, (
        "ProposalApplyService.apply() must set source_proposal_id on the created MemoryEntry"
    )


def test_memory_update_supersedes_old_memory_and_sets_source_proposal_id(db, cross_space_pair_db):
    """memory_update creates a new active version, supersedes old, and links new row to proposal."""
    from app.memory.proposals import ProposalService

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    original = factories.create_test_memory_entry(
        db, space_id=space_id, content="original content", scope_type="user",
        owner_user_id=ua.id, commit=True,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space_id,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={
            "target_memory_id": original.id,
            "proposed_content": "updated content",
            "memory_type": "semantic",
            "target_scope": "user",
            "target_namespace": "user.default",
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=space_id, user_id=ua.id)
    assert result is not None
    new_mem = result.memory
    assert new_mem is not None
    assert new_mem.id != original.id
    assert new_mem.status == "active"
    assert new_mem.source_proposal_id == prop.id, (
        "memory_update must link new row to source proposal via source_proposal_id"
    )
    assert new_mem.supersedes_memory_id == original.id

    db.expire_all()
    old_row = db.query(MemoryEntry).filter(MemoryEntry.id == original.id).first()
    assert old_row.status == "superseded"
    assert old_row.deleted_at is None


def test_memory_archive_requires_proposal_apply(db, cross_space_pair_db):
    """Normal archive path goes through ProposalApplyService and does not hard-delete."""
    from app.memory.proposals import ProposalService

    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    target = factories.create_test_memory_entry(
        db, space_id=space_id, content="to be archived", scope_type="user",
        owner_user_id=ua.id, commit=True,
    )
    prop = factories.create_test_proposal(
        db,
        space_id=space_id,
        created_by_user_id=ua.id,
        proposal_type="memory_archive",
        payload_json={"target_memory_id": target.id},
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=space_id, user_id=ua.id)
    assert result is not None

    db.expire_all()
    row = db.query(MemoryEntry).filter(MemoryEntry.id == target.id).first()
    assert row.status == "archived"
    assert row.deleted_at is None, "archive must not hard-delete"


def test_system_seed_writer_is_explicit_and_not_public_memory_store_path(db, cross_space_pair_db):
    """Seed-created active memory is only possible through create_system_seed_memory()
    and carries source_trust='internal_system' provenance."""
    from app.memory.internal_writer import MemoryInternalWriter
    from app.schemas import MemoryCreate

    space_id = cross_space_pair_db["space_a_id"]

    seed_data = MemoryCreate(
        space_id=space_id,
        title="System seed",
        type="semantic",
        content="system bootstrap content",
        scope="system",
        namespace="system.test_seed",
        visibility="space_shared",
        importance=1.0,
    )
    writer = MemoryInternalWriter(db)
    mem = writer.create_system_seed_memory(seed_data, created_by="system_seed", commit=False)
    db.flush()

    assert mem.status == "active"
    assert mem.source_trust == "internal_system", (
        "create_system_seed_memory() must set source_trust='internal_system'"
    )
    assert mem.created_by == "system_seed"


# ---------------------------------------------------------------------------
# 3. ContextCompiler records source refs and budget trace
# ---------------------------------------------------------------------------


def test_context_compiler_budget_trace_contains_mandatory():
    """budget_trace always lists mandatory sections even when budget is tight."""
    compiler = ContextCompiler()
    context = {
        "system_policy": [],
        "user_memory": [],
        "workspace_memory": [],
        "capability_memory": [],
        "agent_memory": [],
        "relevant_episodes": [],
        "recent_session_summary": [],
    }
    result = compiler.compile(
        context=context,
        target=TargetFormat.generic,
        task_goal="Do something important",
    )
    assert "budget_trace" in result.__dict__ or hasattr(result, "budget_trace")
    trace = result.budget_trace
    assert "mandatory" in trace, "budget_trace must have 'mandatory' key"
    assert "task" in trace["mandatory"], "task section must always appear in mandatory"
    assert "capped" in trace, "budget_trace must have 'capped' key"
    assert "dropped" in trace, "budget_trace must have 'dropped' key"


def test_context_compiler_mandatory_section_not_dropped_under_tight_budget():
    """task section is never dropped even when budget is extremely tight."""
    compiler = ContextCompiler()
    context = {
        "system_policy": [{"title": "p", "content": "a" * 20_000}],
        "user_memory": [],
        "workspace_memory": [],
        "capability_memory": [],
        "agent_memory": [],
        "relevant_episodes": [],
        "recent_session_summary": [],
    }
    # Budget so small that most sections would be dropped
    result = compiler.compile(
        context=context,
        target=TargetFormat.generic,
        task_goal="Critical task goal",
        budget_chars=100,
    )
    assert "task" not in result.dropped_sections, "task (mandatory) must never be dropped"
    assert "task" in result.budget_trace.get("mandatory", [])


def test_context_compiler_per_section_cap_recorded_in_trace():
    """Sections exceeding their cap appear in budget_trace['capped']."""
    compiler = ContextCompiler()
    long_content = "x" * 30_000  # exceeds system_policy cap of 16_000
    context = {
        "system_policy": [{"title": "big policy", "content": long_content}],
        "user_memory": [],
        "workspace_memory": [],
        "capability_memory": [],
        "agent_memory": [],
        "relevant_episodes": [],
        "recent_session_summary": [],
    }
    result = compiler.compile(
        context=context,
        target=TargetFormat.generic,
        task_goal="Task with large policy",
        budget_chars=500_000,
    )
    capped = result.budget_trace.get("capped", [])
    capped_names = [c["section"] for c in capped]
    assert "system_policy" in capped_names, (
        "system_policy section exceeding its cap must appear in budget_trace['capped']"
    )


def test_mandatory_sections_constant_includes_task():
    """_MANDATORY_SECTIONS is defined and contains 'task'."""
    assert "task" in _MANDATORY_SECTIONS


# ---------------------------------------------------------------------------
# 4. Dirty digest can be refreshed explicitly
# ---------------------------------------------------------------------------


def test_dirty_digest_refreshed_to_active_via_refresh_service(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id)

    digest_svc = ContextDigestService(db)
    digest = digest_svc.generate_workspace_digest(space_id, ws.id)
    assert digest.status == "active"

    # Mark dirty
    digest_svc.mark_digest_dirty(space_id, "workspace", ws.id, "workspace", reason="test-dirty")
    db.flush()
    db.expire_all()

    dirty = digest_svc.get_active_digest(space_id, "workspace", ws.id, "workspace")
    assert dirty is not None
    assert dirty.status == "dirty"

    # Explicit refresh
    refresh_svc = ContextDigestRefreshService(db)
    refreshed = refresh_svc.refresh(space_id, "workspace", ws.id, "workspace")

    assert refreshed is not None
    assert refreshed.status == "active", "Refreshed digest must be active"
    assert refreshed.dirty_since is None, "dirty_since must be cleared after refresh"


def test_refresh_all_dirty_clears_all_dirty_digests(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=space_id, created_by_user_id=ua.id)
    _active_policy(db, space_id=space_id)
    _active_memory(db, space_id=space_id, scope_type="workspace", workspace_id=ws.id)

    digest_svc = ContextDigestService(db)
    digest_svc.generate_policy_bundle_digest(space_id)
    digest_svc.generate_workspace_digest(space_id, ws.id)

    # Mark both dirty
    digest_svc.mark_digest_dirty(space_id, "space", None, "policy_bundle", reason="bulk-test")
    digest_svc.mark_digest_dirty(space_id, "workspace", ws.id, "workspace", reason="bulk-test")
    db.flush()

    refresh_svc = ContextDigestRefreshService(db)
    assert refresh_svc.get_dirty_count(space_id) == 2

    refreshed = refresh_svc.refresh_all_dirty(space_id)
    assert len(refreshed) == 2, "Both dirty digests must be refreshed"
    assert refresh_svc.get_dirty_count(space_id) == 0


def test_refresh_noop_when_source_unchanged(db, cross_space_pair_db):
    """Refreshing an active (non-dirty) digest with unchanged sources returns same digest."""
    space_id = cross_space_pair_db["space_a_id"]
    _active_policy(db, space_id=space_id)

    digest_svc = ContextDigestService(db)
    d1 = digest_svc.generate_policy_bundle_digest(space_id)

    refresh_svc = ContextDigestRefreshService(db)
    d2 = refresh_svc.refresh(space_id, "space", None, "policy_bundle")

    assert d1.id == d2.id, "No new digest row created when source_hash is unchanged"
    assert d2.version == 1


# ---------------------------------------------------------------------------
# 5. Automation is deferred
# ---------------------------------------------------------------------------


def test_no_automation_trigger_table_in_orm():
    """AutomationTrigger is not yet implemented — table must not exist."""
    from app.db import Base

    table_names = {t.lower() for t in Base.metadata.tables}
    assert "automation_triggers" not in table_names, (
        "AutomationTrigger table must not exist — automation is deferred"
    )


def test_no_automation_schedule_table_in_orm():
    """AutomationSchedule is not yet implemented — table must not exist."""
    from app.db import Base

    table_names = {t.lower() for t in Base.metadata.tables}
    assert "automation_schedules" not in table_names, (
        "AutomationSchedule table must not exist — automation is deferred"
    )


def test_automation_run_table_exists_in_orm():
    """AutomationRun is implemented — table must exist."""
    from app.db import Base

    table_names = {t.lower() for t in Base.metadata.tables}
    assert "automation_runs" in table_names, (
        "AutomationRun table must exist — automation skeleton is now implemented"
    )
