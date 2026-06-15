"""Domain invariant: durable objects in space A are not visible or mutable as space B."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func

from app.activity.service import ActivityService
from app.proposals import ProposalService
from app.memory.store import MemoryStore
from app.models import (
    ActivityRecord,
    Agent,
    Artifact,
    Credential,
    MemoryEntry,
    ModelProvider,
    Policy,
    Proposal,
    Run,
    Workspace,
)
from app.runs.run_service import RunService
from tests.support import factories


def test_memory_list_scoped_to_space_query(db, cross_space_pair_db):
    """MemoryStore list/search only considers rows for the requested space_id."""
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]
    factories.create_test_memory_entry(
        db,
        space_id=a,
        content="secret-a",
        scope_type="space",
        namespace="ns.a",
        owner_user_id=ua.id,
        commit=False,
    )
    db.flush()
    store = MemoryStore(db)
    rows_b = store.list(space_id=b, user_id=ub.id, limit=50)
    assert not any(m.content == "secret-a" for m in rows_b)
    assert store.count(space_id=b, user_id=ub.id) == 0


def test_memory_get_for_space_denies_cross_space(db, cross_space_pair_db):
    """``MemoryStore.get_for_space`` never returns a row from another ``space_id``."""
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="orphan-read",
        owner_user_id=ua.id,
        commit=False,
    )
    db.flush()
    store = MemoryStore(db)
    assert store.get_for_space(b, mem.id) is None
    assert store.get_for_space(a, mem.id) is not None


def test_activity_get_requires_matching_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        title="A-only",
        commit=False,
    )
    db.flush()
    assert ActivityService(db).get(act.id, b) is None
    assert ActivityService(db).get(act.id, a).id == act.id


def test_run_get_run_rejects_other_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=False)
    db.flush()
    with pytest.raises(HTTPException) as ei:
        RunService(db).get_run(run.id, b)
    assert ei.value.status_code == 404


def test_proposal_accept_rejects_wrong_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=False,
    )
    db.flush()
    assert ProposalService(db).accept(prop.id, space_id=b, user_id=ua.id) is None
    db.refresh(prop)
    assert prop.status == "pending"


def test_workspace_row_not_found_when_filtered_by_other_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=False)
    db.flush()
    assert (
        db.query(Workspace)
        .filter(Workspace.id == ws.id, Workspace.space_id == b)
        .first()
    ) is None


def test_agent_query_scoped_by_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ag = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    db.flush()
    assert db.query(Agent).filter(Agent.id == ag.id, Agent.space_id == b).first() is None


def test_policy_runtime_row_isolated_by_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    pol = factories.create_test_policy(db, space_id=a, name="pol-a", commit=False)
    cred = factories.create_test_credential_stub(db, space_id=a, commit=False)
    mp = factories.create_test_model_provider(db, space_id=a, commit=False)
    db.flush()
    assert db.query(Policy).filter(Policy.id == pol.id, Policy.space_id == b).first() is None
    assert db.query(Credential).filter(Credential.id == cred.id, Credential.space_id == b).first() is None
    assert db.query(ModelProvider).filter(ModelProvider.id == mp.id, ModelProvider.space_id == b).first() is None


def test_artifact_and_proposal_counts_other_space_empty(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=False)
    art = factories.create_test_artifact(db, space_id=a, run_id=run.id, commit=False)
    prop = factories.create_test_proposal(db, space_id=a, run_id=run.id, created_by_user_id=ua.id, commit=False)
    db.flush()
    assert (
        db.query(func.count(Artifact.id))
        .filter(Artifact.space_id == b, Artifact.id == art.id)
        .scalar()
        == 0
    )
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == b, Proposal.id == prop.id)
        .scalar()
        == 0
    )


def test_cross_space_memory_not_included_in_context_retrieval(db, cross_space_pair_db):
    """MemoryRetriever for space A cannot include space_shared memories from space B.

    Even when space B has space_shared memories (maximum visibility), the cross-space
    hard-filter prevents them from entering the context for a run in space A.
    """
    from app.memory.retriever import MemoryRetriever

    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    # Memory in space B with maximum visibility — deliberately matches keyword
    b_mem = factories.create_test_memory_entry(
        db,
        space_id=b,
        content="cross-space-shared-context-sentinel",
        scope_type="space",
        owner_user_id=ub.id,
        commit=False,
    )
    b_mem.visibility = "space_shared"
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
        query="cross-space-shared-context-sentinel",
    )
    ids = {m.id for m in result.memories}
    assert b_mem.id not in ids, (
        "space_shared memory from space B must not appear in context retrieval for space A "
        "even via keyword fallback"
    )
    source_ids = {r["source_id"] for r in result.source_refs if r.get("source_type") == "memory"}
    assert b_mem.id not in source_ids, (
        "Cross-space memory must not appear in source_refs"
    )


def test_context_space_boundary_preserves_same_space_memories(db, cross_space_pair_db):
    """Context retrieval for space A includes same-space memories and excludes other-space ones."""
    from app.memory.retriever import MemoryRetriever

    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    sentinel = "isolation-context-sentinel-zq9"
    a_mem = factories.create_test_memory_entry(
        db, space_id=a, content=sentinel, scope_type="space", owner_user_id=ua.id, commit=False
    )
    a_mem.visibility = "space_shared"
    b_mem = factories.create_test_memory_entry(
        db, space_id=b, content=sentinel, scope_type="space", owner_user_id=ub.id, commit=False
    )
    b_mem.visibility = "space_shared"
    db.commit()

    result_a = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query=sentinel)
    ids_a = {m.id for m in result_a.memories}
    assert a_mem.id in ids_a, "Same-space memory must be included in context retrieval"
    assert b_mem.id not in ids_a, "Cross-space memory must be excluded"

    result_b = MemoryRetriever(db).retrieve(space_id=b, user_id=ub.id, query=sentinel)
    ids_b = {m.id for m in result_b.memories}
    assert b_mem.id in ids_b, "Same-space memory must be included for space B retrieval"
    assert a_mem.id not in ids_b, "Space A memory must not appear in space B retrieval"


def test_run_list_only_returns_same_space(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]
    r_a = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=False)
    factories.create_test_run(db, space_id=b, user_id=ub.id, commit=False)
    db.flush()
    rows = RunService(db).list_runs(space_id=a)
    ids = {r.id for r in rows}
    assert r_a.id in ids
    assert not any(r.space_id != a for r in rows)
