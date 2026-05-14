"""
Workflow tests for ContextDigest integration with ContextSnapshotPopulator.

Tests verify:
- Active digest appears in stable_prefix text.
- ContextSnapshot source_refs_json includes context_digest entries.
- Digest source_refs include source_memory_ids and source_policy_ids.
- retrieval_trace_json records digest_used=True when digest is present.
- Missing digest falls back to MF5 MemoryRetriever behaviour (fallback_to_memory_retriever=True).
- Dirty digest is recorded in retrieval_trace.
- Digest load failure records digest_load_error / digest_fallback_reason in trace.
- compiler_version is "context_digest.v1" (format changed with digest injection).
- MF2 memory write governance regression: public write creates Proposal, not MemoryEntry.
- MF5 context snapshot audit regression: prefix_hash / tail_hash populated.
"""

from __future__ import annotations

import pytest
from ulid import ULID

from app.models import ContextDigest, ContextSnapshot, MemoryEntry, Policy, Proposal, Run
from app.runs.context_snapshot_populator import ContextSnapshotPopulator
from app.memory.digest_service import ContextDigestService
from app.runs.execution import RunExecutionService
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(ULID())


def _setup_execution(monkeypatch, db, tmp_path, *, space_id: str, user_id: str):
    from app.config import settings
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    fake = ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text="ok"))
    monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", lambda _t: fake)


def _active_policy(db, *, space_id, name="digest-pol") -> Policy:
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
# Digest appears in stable_prefix
# ---------------------------------------------------------------------------


def test_active_digest_appears_in_stable_prefix(monkeypatch, db, tmp_path, cross_space_pair):
    """When an active policy_bundle digest exists its content appears in compiled_prefix_text."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    pol = _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    assert digest.status == "active"

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "test digest in prefix"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    assert snap.compiled_prefix_text is not None
    assert "[digest:policy_bundle:" in snap.compiled_prefix_text, (
        "Active policy_bundle digest must appear in compiled_prefix_text"
    )


# ---------------------------------------------------------------------------
# ContextSnapshot source_refs includes context_digest
# ---------------------------------------------------------------------------


def test_context_snapshot_source_refs_includes_context_digest(monkeypatch, db, tmp_path, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "source refs digest test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    digest_refs = [r for r in snap.source_refs_json if r.get("source_type") == "context_digest"]
    assert len(digest_refs) >= 1, "source_refs_json must include context_digest entry when digest is used"
    ref = digest_refs[0]
    assert ref["source_id"] == digest.id
    assert ref["digest_type"] == "policy_bundle"
    assert ref["section"] == "stable_prefix"


def test_context_snapshot_source_refs_includes_source_memory_and_policy_ids(monkeypatch, db, tmp_path, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    pol = _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "traceability test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    digest_refs = [r for r in snap.source_refs_json if r.get("source_type") == "context_digest"]
    assert len(digest_refs) >= 1
    ref = digest_refs[0]
    # source_policy_ids must contain the actual policy id.
    assert pol.id in (ref.get("source_policy_ids") or []), (
        "context_digest source_ref must include source_policy_ids for auditability"
    )
    # source_memory_ids must be a list (may be empty for policy_bundle).
    assert isinstance(ref.get("source_memory_ids"), list)


# ---------------------------------------------------------------------------
# retrieval_trace records digest_used
# ---------------------------------------------------------------------------


def test_retrieval_trace_records_digest_used_true(monkeypatch, db, tmp_path, cross_space_pair):
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    svc.generate_policy_bundle_digest(space_id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "trace test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    trace = snap.retrieval_trace_json[0]
    assert trace.get("digest_used") is True, "retrieval_trace must record digest_used=True"
    assert trace.get("fallback_to_memory_retriever") is False


def test_missing_digest_falls_back_to_memory_retriever(monkeypatch, db, tmp_path, cross_space_pair):
    """When no digest exists, retrieval_trace records fallback_to_memory_retriever=True."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    # No digest generated.
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "no digest fallback"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    trace = snap.retrieval_trace_json[0]
    assert trace.get("digest_used") is False, "No digest → digest_used must be False"
    assert trace.get("fallback_to_memory_retriever") is True, (
        "No digest → fallback_to_memory_retriever must be True"
    )
    # No context_digest source refs when no digest.
    digest_refs = [r for r in snap.source_refs_json if r.get("source_type") == "context_digest"]
    assert len(digest_refs) == 0


def test_dirty_digest_recorded_in_retrieval_trace(monkeypatch, db, tmp_path, cross_space_pair):
    """Dirty digest is used but retrieval_trace records dirty_digest_used=True."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    _active_policy(db, space_id=space_id)
    svc = ContextDigestService(db)
    digest = svc.generate_policy_bundle_digest(space_id)
    # Mark it dirty manually.
    svc.mark_digest_dirty(space_id, "space", None, "policy_bundle", reason="test-dirty")
    db.flush()
    db.expire_all()
    digest = svc.get_active_digest(space_id, "space", None, "policy_bundle")
    assert digest.status == "dirty"

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "dirty digest test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    trace = snap.retrieval_trace_json[0]
    # Dirty digest is still used (not blocked) but flagged in trace.
    assert trace.get("digest_used") is True
    assert trace.get("dirty_digest_used") is True, "Dirty digest usage must be flagged in retrieval_trace"


# ---------------------------------------------------------------------------
# Regression: MF2 memory write governance
# ---------------------------------------------------------------------------


def test_mf2_public_memory_write_creates_proposal_not_memory_entry(db, cross_space_pair):
    """MF2 regression: public memory write creates a pending Proposal, not an active MemoryEntry."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before_mem = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == space_id, MemoryEntry.status == "active"
    ).count()

    from app.memory.proposals import ProposalService

    svc = ProposalService(db)
    proposal = svc.create_proposal(
        space_id=space_id,
        user_id=ua.id,
        target_scope="user",
        target_namespace="user.default",
        memory_type="semantic",
        proposed_title="mf2-regression",
        proposed_content="regression check",
        rationale="test",
        target_visibility="space_shared",
    )
    assert proposal is not None
    assert proposal.status == "pending"
    assert proposal.proposal_type == "memory_create"

    after_mem = db.query(MemoryEntry).filter(
        MemoryEntry.space_id == space_id, MemoryEntry.status == "active"
    ).count()
    assert after_mem == before_mem, "Proposal creation must not create active MemoryEntry"


# ---------------------------------------------------------------------------
# Regression: MF5 context snapshot audit fields
# ---------------------------------------------------------------------------


def test_mf5_executed_run_has_prefix_and_tail_hash(monkeypatch, db, tmp_path, cross_space_pair):
    """MF5 regression: executed run still has prefix_hash and tail_hash."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "mf5 regression"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    assert snap.prefix_hash is not None and len(snap.prefix_hash) == 64
    assert snap.tail_hash is not None and len(snap.tail_hash) == 64
    assert snap.retrieval_trace_json is not None
    assert snap.token_budget_json is not None


# ---------------------------------------------------------------------------
# Fallback observability: digest load error
# ---------------------------------------------------------------------------


def test_digest_load_error_records_fallback_reason_in_retrieval_trace(monkeypatch, db, tmp_path, cross_space_pair):
    """Unexpected exception during digest load is recorded in retrieval_trace, not silently swallowed."""
    from app.runs import context_snapshot_populator as csp_mod

    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    def _exploding_load_bundle(db, **kwargs):
        raise RuntimeError("simulated digest storage failure")

    monkeypatch.setattr(csp_mod, "_load_digest_bundle", _exploding_load_bundle)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "error fallback test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    trace = snap.retrieval_trace_json[0]
    assert trace.get("digest_used") is False, "digest_used must be False on load error"
    assert trace.get("fallback_to_memory_retriever") is True, "must fall back to retriever on error"
    assert trace.get("digest_fallback_reason") == "load_error", "must record load_error reason"
    assert "RuntimeError" in (trace.get("digest_load_error") or ""), (
        "must record exception type in digest_load_error"
    )
    # No context_digest source refs when load failed.
    digest_refs = [r for r in snap.source_refs_json if r.get("source_type") == "context_digest"]
    assert len(digest_refs) == 0, "No digest source_refs on load failure"
    # Run must still succeed — load error is non-blocking.
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "succeeded", "Run must succeed despite digest load failure"


def test_missing_digest_records_fallback_reason_no_digest_available(monkeypatch, db, tmp_path, cross_space_pair):
    """When no digest exists, retrieval_trace records fallback_reason=no_digest_available (not an error)."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "no digest fallback reason"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    trace = snap.retrieval_trace_json[0]
    assert trace.get("digest_fallback_reason") == "no_digest_available"
    assert "digest_load_error" not in trace, "No load error key when digest simply does not exist"


# ---------------------------------------------------------------------------
# Compiler version
# ---------------------------------------------------------------------------


def test_compiler_version_is_context_digest_v1(monkeypatch, db, tmp_path, cross_space_pair):
    """compiler_version must be 'context_digest.v1' after digest integration."""
    space_id = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    _setup_execution(monkeypatch, db, tmp_path, space_id=space_id, user_id=ua.id)

    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=ua.id)
    run = factories.create_test_run(db, space_id=space_id, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "version test"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=space_id)
    db.expire_all()

    snap = (
        db.query(ContextSnapshot)
        .join(Run, Run.context_snapshot_id == ContextSnapshot.id)
        .filter(Run.id == run.id)
        .one()
    )
    assert snap.compiler_version == "context_digest.v1", (
        "compiler_version must reflect digest-aware format; "
        "stable_prefix now emits [digest:…] blocks when digests are present"
    )
