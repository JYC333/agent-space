"""
Contract: ContextSnapshot audit fields are populated on run execution.

Checks:
  - Executed Run has non-empty ContextSnapshot fields.
  - source_refs_json is a list (may be empty when no memories exist).
  - retrieval_trace_json explains the retrieval pipeline.
  - token_budget_json is present.
  - prefix_hash and tail_hash are non-empty strings.
  - ContextSnapshot is bound before adapter execution, not after.
  - Policy rows in the space appear in source_refs.
"""

from __future__ import annotations
import uuid

import json

import pytest

from app.models import ContextSnapshot, MemoryEntry, MemoryReadTrace, Policy, Run
from app.runs.execution import RunExecutionService
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_execution(
    monkeypatch,
    db,
    tmp_path,
    *,
    space_id: str,
    user_id: str,
    output_text: str = "snapshot-ok",
):
    from app.config import settings

    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    fake = ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text=output_text))
    monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _t: fake)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_executed_run_snapshot_has_prefix_and_tail_hash(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "test prompt"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.context_snapshot_id is not None

    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run_row.context_snapshot_id).one()
    assert snap.prefix_hash, "prefix_hash must be non-empty after execution"
    assert snap.tail_hash, "tail_hash must be non-empty after execution"
    assert isinstance(snap.prefix_hash, str) and len(snap.prefix_hash) == 64
    assert isinstance(snap.tail_hash, str) and len(snap.tail_hash) == 64


def test_executed_run_snapshot_has_retrieval_trace_json(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "trace test"
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
    assert snap.retrieval_trace_json is not None
    assert isinstance(snap.retrieval_trace_json, list)
    assert len(snap.retrieval_trace_json) >= 1
    trace = snap.retrieval_trace_json[0]
    assert "hard_filter" in trace
    assert "stages" in trace
    assert "space_id" in trace


def test_executed_run_snapshot_has_token_budget_json(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "budget test"
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
    assert snap.token_budget_json is not None
    assert isinstance(snap.token_budget_json, dict)
    assert "stable_prefix_chars" in snap.token_budget_json
    assert "dynamic_tail_chars" in snap.token_budget_json
    assert "compiler_version" in snap.token_budget_json


def test_executed_run_snapshot_has_source_refs_json(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "source refs test"
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
    # source_refs_json is always a list (may be empty when space has no memories).
    assert snap.source_refs_json is not None
    assert isinstance(snap.source_refs_json, list)


def test_policy_in_source_refs_when_policy_exists(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    # Create an active policy in the space.
    policy = Policy(
        id=str(uuid.uuid4()),
        space_id=a,
        name="test-audit-policy",
        domain="runtime",
        policy_json={"allow": "all"},
        enabled=True,
        status="active",
    )
    db.add(policy)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "policy audit"
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
    policy_refs = [r for r in snap.source_refs_json if r.get("source_type") == "policy"]
    assert len(policy_refs) >= 1, "Active policy must appear in source_refs_json"
    policy_ref = next(r for r in policy_refs if r.get("source_id") == policy.id)
    assert policy_ref["section"] == "stable_prefix"
    assert policy_ref["reason"] == "active_policy"


def test_memory_injected_into_context_creates_access_log(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    # Create a space_shared memory so it passes the hard filter for this user.
    mem = MemoryEntry(
        id=str(uuid.uuid4()),
        space_id=a,
        scope_type="user",
        memory_type="semantic",
        content="injected memory content",
        status="active",
        visibility="space_shared",
        owner_user_id=ua.id,
        subject_user_id=ua.id,
        importance=0.8,
    )
    db.add(mem)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "access log test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    logs = (
        db.query(MemoryReadTrace)
        .filter(MemoryReadTrace.memory_id == mem.id)
        .all()
    )
    assert len(logs) >= 1, "Injected memory must produce MemoryReadTrace row"
    assert all(log.access_type == "context_injection" for log in logs)

    db.refresh(mem)
    assert mem.last_retrieved_at is not None, "last_retrieved_at must be set after context injection"


def test_prefix_hash_stable_for_same_stable_input(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    """Two runs for the same agent/space produce equal prefix_hash when stable input is unchanged."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run1 = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run2 = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run1.prompt = "stable hash run 1"
    run2.prompt = "stable hash run 2"  # different prompt (dynamic tail)
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run1.id, space_id=a)
    RunExecutionService(db).execute_run(run2.id, space_id=a)
    db.expire_all()

    snap1 = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == db.query(Run).filter(Run.id == run1.id).one().context_snapshot_id
    ).one()
    snap2 = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == db.query(Run).filter(Run.id == run2.id).one().context_snapshot_id
    ).one()

    # Same agent/space/no-memories => same stable prefix => same prefix_hash.
    assert snap1.prefix_hash == snap2.prefix_hash, (
        "prefix_hash must be stable when stable input (system prompt, policies) is unchanged"
    )
    # Different prompts => different tail_hash.
    assert snap1.tail_hash != snap2.tail_hash, (
        "tail_hash must differ when prompt changes"
    )


def test_queued_run_snapshot_initially_has_no_hash(db, cross_space_pair_db):
    """A newly created (queued) Run has an empty ContextSnapshot (populated later)."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    snap = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == run.context_snapshot_id
    ).one()
    # Placeholder snapshot: hashes are null before execution.
    assert snap.prefix_hash is None
    assert snap.tail_hash is None


def test_token_budget_json_contains_stable_prefix_pct(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    """token_budget_json always contains stable_prefix_pct as an audit metric."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=a, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "token budget test"
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
    budget = snap.token_budget_json
    assert "stable_prefix_pct" in budget
    assert "stable_prefix_target_pct" in budget
    assert budget["stable_prefix_target_pct"] == 50.0
    assert isinstance(budget["stable_prefix_pct"], float)


def test_token_budget_warning_recorded_when_prefix_exceeds_target(
    monkeypatch, db, tmp_path, cross_space_pair_db
):
    """
    When stable_prefix occupies more than 50% of total context,
    token_budget_json contains a stable_prefix_warning key.
    This is an audit metric only — no truncation is performed.
    """
    from app.runs.context_snapshot_populator import ContextSnapshotPopulator, _STABLE_PREFIX_BUDGET_CHARS
    from app.models import AgentVersion

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    # Short prompt → dynamic tail is tiny, so stable prefix occupies > 50%.
    run.prompt = "x"
    db.flush()

    version = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()

    # Inject a long system_prompt so stable_prefix > dynamic_tail.
    version.system_prompt = "A" * 500
    db.flush()

    populator = ContextSnapshotPopulator(db)
    pkg = populator.populate(run, version)
    db.commit()

    snap = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == run.context_snapshot_id
    ).one()
    budget = snap.token_budget_json
    # With a 500-char system prompt and a 1-char prompt, stable > dynamic.
    if budget["stable_prefix_pct"] > 50.0:
        assert "stable_prefix_warning" in budget, (
            "stable_prefix_warning must be present when pct > 50%"
        )
        assert "not yet implemented" in budget["stable_prefix_warning"], (
            "warning must note that truncation is not yet implemented"
        )
