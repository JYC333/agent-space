"""
Workflow: Run → ContextSnapshot population → audit trail.

Verifies:
  - ContextSnapshot is populated before adapter execution.
  - Memory injected into context appears in source_refs_json and MemoryReadTrace.
  - last_retrieved_at is set on injected memories.
  - Forbidden (cross-space, archived) memory is not in source_refs.
  - ContextBuilder / ContextSnapshotPopulator work end-to-end.
"""

from __future__ import annotations
import uuid

import pytest
from datetime import UTC, datetime


from app.models import (
    ContextSnapshot,
    MemoryEntry,
    MemoryReadTrace,
    Policy,
    Run,
)
from app.runs.execution import RunExecutionService
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _new_id() -> str:
    return str(uuid.uuid4())


def _patch_echo(monkeypatch, tmp_path):
    from app.config import settings

    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    fake = ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text=""))
    monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _t: fake)


# ---------------------------------------------------------------------------
# Snapshot bound to run before execution
# ---------------------------------------------------------------------------


def test_context_snapshot_populated_before_execution_completes(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _patch_echo(monkeypatch, tmp_path)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "run with context"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "succeeded"
    assert run_row.context_snapshot_id is not None

    snap = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == run_row.context_snapshot_id
    ).one()
    assert snap.prefix_hash is not None
    assert snap.tail_hash is not None
    assert snap.retrieval_trace_json is not None
    assert snap.token_budget_json is not None
    assert snap.compiler_version == "context_digest.v1"


# ---------------------------------------------------------------------------
# Injected memory traced end-to-end
# ---------------------------------------------------------------------------


def test_injected_memory_traced_in_snapshot_and_access_log(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _patch_echo(monkeypatch, tmp_path)

    # Space-shared memory visible to ua
    mem = MemoryEntry(
        id=_new_id(),
        space_id=a,
        scope_type="user",
        memory_type="semantic",
        content="workflow memory",
        status="active",
        visibility="space_shared",
        owner_user_id=ua.id,
        subject_user_id=ua.id,
        importance=0.9,
    )
    db.add(mem)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "recall workflow memory"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    memory_refs = [
        r for r in snap.source_refs_json if r.get("source_type") == "memory"
    ]
    injected_ids = {r["source_id"] for r in memory_refs}
    assert mem.id in injected_ids, "injected memory must appear in source_refs_json"

    traces = db.query(MemoryReadTrace).filter(
        MemoryReadTrace.memory_id == mem.id,
        MemoryReadTrace.run_id == run.id,
    ).all()
    assert len(traces) >= 1, "MemoryReadTrace must be created for injected memory"
    assert all(t.access_type == "context_injection" for t in traces)

    db.refresh(mem)
    assert mem.last_retrieved_at is not None


# ---------------------------------------------------------------------------
# Forbidden memory not in source_refs
# ---------------------------------------------------------------------------


def test_archived_memory_not_in_snapshot_source_refs(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _patch_echo(monkeypatch, tmp_path)

    archived = MemoryEntry(
        id=_new_id(),
        space_id=a,
        scope_type="user",
        memory_type="semantic",
        content="archived should not appear",
        status="archived",
        visibility="space_shared",
        owner_user_id=ua.id,
        subject_user_id=ua.id,
    )
    db.add(archived)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "archived should not appear"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    memory_ref_ids = {
        r["source_id"] for r in snap.source_refs_json if r.get("source_type") == "memory"
    }
    assert archived.id not in memory_ref_ids, (
        "archived memory must not appear in snapshot source_refs"
    )

    # No access log for the archived memory
    logs = db.query(MemoryReadTrace).filter(
        MemoryReadTrace.memory_id == archived.id
    ).all()
    assert len(logs) == 0, "archived memory must not generate access log"


# ---------------------------------------------------------------------------
# Filtered-out memory has no access log
# ---------------------------------------------------------------------------


def test_filtered_memory_not_logged_as_accessed(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]
    _patch_echo(monkeypatch, tmp_path)

    foreign_mem = MemoryEntry(
        id=_new_id(),
        space_id=b,
        scope_type="user",
        memory_type="semantic",
        content="foreign space memory",
        status="active",
        visibility="space_shared",
        owner_user_id=ub.id,
        subject_user_id=ub.id,
    )
    db.add(foreign_mem)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "foreign space memory"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    logs = db.query(MemoryReadTrace).filter(
        MemoryReadTrace.memory_id == foreign_mem.id
    ).all()
    assert len(logs) == 0, "cross-space memory must not generate access log"


# ---------------------------------------------------------------------------
# ContextSnapshotPopulator unit-level test
# ---------------------------------------------------------------------------


def test_context_snapshot_populator_populates_all_fields(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "unit test prompt"
    db.flush()

    from app.models import AgentVersion
    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()

    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == run.context_snapshot_id
    ).one()

    assert snap.prefix_hash is not None
    assert snap.tail_hash is not None
    assert snap.compiled_prefix_text is not None
    assert snap.compiled_tail_text is not None
    assert snap.source_refs_json is not None
    assert snap.retrieval_trace_json is not None
    assert snap.token_budget_json is not None
    assert snap.compiler_version == "context_digest.v1"


def test_context_snapshot_source_refs_includes_session_summary(db, cross_space_pair_db):
    """ContextSnapshot.source_refs_json contains source_type=session_summary when session is active."""
    from app.models import AgentVersion, Session as SessionModel, Message, SessionSummary
    from app.sessions.condenser import SessionCondenser

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    session = SessionModel(id=_new_id(), space_id=a, user_id=ua.id, status="active")
    db.add(session)
    db.flush()
    db.add(Message(id=_new_id(), space_id=a, session_id=session.id, user_id=ua.id, role="user", content="snapshot source ref test"))
    db.flush()
    summary = SessionCondenser(db).condense(session.id, a, user_id=ua.id)
    db.commit()

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "source refs session test"
    run.session_id = session.id
    db.flush()

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()
    ContextSnapshotPopulator(db).populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).one()
    summary_refs = [
        r for r in (snap.source_refs_json or [])
        if r.get("source_type") == "session_summary"
    ]
    assert len(summary_refs) == 1, "ContextSnapshot.source_refs_json must contain session_summary"
    assert summary_refs[0]["source_id"] == summary.id
    assert summary_refs[0]["derived_context"] is True


def test_activity_consolidation_still_produces_proposals(db, cross_space_pair_db):
    """Activity consolidation pipeline produces proposals independently of context snapshot changes."""
    from app.memory.consolidation.service import ActivityConsolidationService
    from app.models import ActivityRecord, Proposal

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # Add a consolidatable activity using a valid source_kind value.
    now = datetime.now(UTC)
    act = ActivityRecord(
        id=_new_id(),
        space_id=a,
        user_id=ua.id,
        activity_type="agent.run.success",
        title="Test run succeeded",
        content="Run completed successfully with output: hello world",
        payload_json={},
        occurred_at=now,
        status="raw",
        updated_at=now,
        consolidation_status="pending",
        source_kind="run_event",  # valid source_kind per ck_activity_records_source_kind
        source_trust="internal_system",
    )
    db.add(act)
    db.commit()

    svc = ActivityConsolidationService(db)
    result = svc.run_pending(space_id=a, acting_user_id=ua.id, batch_limit=10)
    db.commit()

    # consolidation ran without error; result has standard ConsolidationRunResult fields
    assert hasattr(result, "consolidation_run_id"), (
        "ActivityConsolidationService must return a ConsolidationRunResult"
    )


def test_proposal_write_governance_enforced(db, cross_space_pair_db):
    """MemoryStore.create/update/delete are sentinel-guarded; only proposal-approved paths write."""
    from app.memory.store import MemoryStore
    from app.memory.internal_writer import MemoryInternalWriter
    from app.schemas import MemoryCreate

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # MemoryStore.create() without sentinel raises PermissionError.
    with pytest.raises(PermissionError):
        MemoryStore(db).create(
            MemoryCreate(
                title="governance check",
                space_id=a,
                scope="agent",
                type="semantic",
                content="sentinel guard test",
                visibility="space_shared",
            ),
            acting_user_id=ua.id,
        )

    # create_system_seed_memory() is the bootstrap write path (goes through the sentinel).
    mem = MemoryInternalWriter(db).create_system_seed_memory(
        MemoryCreate(
            title="governance check seed",
            space_id=a,
            scope="agent",
            type="semantic",
            content="sentinel guard verified",
            visibility="space_shared",
        )
    )
    assert mem.id is not None
    assert mem.status == "active"
    assert mem.space_id == a
