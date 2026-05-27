"""
Invariants: MemoryRetriever hard-filter and ranking guarantees.

Hard filter must hold regardless of retrieval stage:
  - Cross-space memory is never returned.
  - Private memory for another user is never returned.
  - archived / superseded / rejected / proposed memory is excluded by default.
  - deleted memory (deleted_at IS NOT NULL) is excluded.
  - keyword fallback cannot reintroduce forbidden memory.
  - graph expansion cannot reintroduce forbidden memory.

Ranking:
  - Symbol match outranks keyword fallback (symbol match ids appear in source_refs
    with stage='symbol_match').
  - Graph expansion produces stage='graph_expansion' entries.
  - Hard filter is applied after graph expansion.

Policy:
  - Active policies appear in source_refs with section='stable_prefix'.
  - Disabled / superseded policies are excluded.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ulid import ULID

from app.models import MemoryEntry, MemoryRelation, Policy
from app.memory.retriever import MemoryRetriever
from tests.support import factories


def _new_id() -> str:
    return str(ULID())


def _make_memory(
    db,
    *,
    space_id: str,
    user_id: str,
    content: str = "test content",
    scope_type: str = "user",
    status: str = "active",
    visibility: str = "space_shared",
    owner_user_id: str | None = None,
    subject_user_id: str | None = None,
    deleted_at=None,
    memory_type: str = "semantic",
    importance: float = 0.5,
) -> MemoryEntry:
    m = MemoryEntry(
        id=_new_id(),
        space_id=space_id,
        scope_type=scope_type,
        memory_type=memory_type,
        content=content,
        status=status,
        visibility=visibility,
        owner_user_id=owner_user_id or user_id,
        subject_user_id=subject_user_id or user_id,
        deleted_at=deleted_at,
        importance=importance,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Hard filter: cross-space
# ---------------------------------------------------------------------------


def test_cross_space_memory_never_returned(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    # Memory belongs to space B
    _make_memory(db, space_id=b, user_id=ub.id, content="space B secret")
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
    )
    ids = {m.id for m in result.memories}
    source_ids = {r["source_id"] for r in result.source_refs if r["source_type"] == "memory"}
    b_ids = {
        m.id
        for m in db.query(MemoryEntry).filter(MemoryEntry.space_id == b).all()
    }
    assert ids.isdisjoint(b_ids), "cross-space memory must never enter result set"
    assert source_ids.isdisjoint(b_ids), "cross-space memory must never appear in source_refs"


# ---------------------------------------------------------------------------
# Hard filter: private memory for another user
# ---------------------------------------------------------------------------


def test_private_other_user_memory_not_returned(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # Create a second member in space_a and give them a private memory.
    other_user = factories.create_test_user(db, space_id=a, display_name="other")
    other_user_id = other_user.id
    db.flush()  # ensure user FK is resolved before memory insert

    other_mem = MemoryEntry(
        id=_new_id(),
        space_id=a,
        scope_type="user",
        memory_type="semantic",
        content="other user private memory",
        status="active",
        visibility="private",
        owner_user_id=other_user_id,
        subject_user_id=other_user_id,
    )
    db.add(other_mem)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id)
    ids = {m.id for m in result.memories}
    assert other_mem.id not in ids, "private memory of another user must not be returned"


# ---------------------------------------------------------------------------
# Hard filter: archived / superseded / rejected memory excluded
# ---------------------------------------------------------------------------


def test_archived_memory_excluded_by_default(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    archived = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="archived content", status="archived",
    )
    active = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="active content", status="active",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query="content")
    ids = {m.id for m in result.memories}
    assert archived.id not in ids, "archived memory must be excluded"
    assert active.id in ids, "active memory must be included"


def test_superseded_memory_excluded_by_default(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    sup = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="superseded content", status="superseded",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query="superseded")
    ids = {m.id for m in result.memories}
    assert sup.id not in ids, "superseded memory must be excluded"


def test_rejected_and_proposed_memory_excluded(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    rejected = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="rejected content", status="rejected",
    )
    proposed = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="proposed content", status="proposed",
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query="content")
    ids = {m.id for m in result.memories}
    assert rejected.id not in ids, "rejected memory must be excluded"
    assert proposed.id not in ids, "proposed memory must be excluded"


# ---------------------------------------------------------------------------
# Hard filter: deleted memory
# ---------------------------------------------------------------------------


def test_deleted_memory_excluded(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    deleted = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="deleted content",
        deleted_at=datetime.now(UTC),
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query="deleted content")
    ids = {m.id for m in result.memories}
    assert deleted.id not in ids, "deleted memory must be excluded"


# ---------------------------------------------------------------------------
# Hard filter survives keyword fallback
# ---------------------------------------------------------------------------


def test_keyword_fallback_cannot_reintroduce_forbidden_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    ub = cross_space_pair_db["user_b"]

    # Cross-space memory that happens to match the keyword
    cross = MemoryEntry(
        id=_new_id(),
        space_id=b,
        scope_type="user",
        memory_type="semantic",
        content="forbidden keyword match",
        status="active",
        visibility="space_shared",
        owner_user_id=ub.id,
        subject_user_id=ub.id,
    )
    db.add(cross)
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
        query="forbidden keyword match",
    )
    ids = {m.id for m in result.memories}
    assert cross.id not in ids, "cross-space memory must not re-enter via keyword fallback"

    # Archived memory with matching keyword
    archived_kw = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="keyword match archived",
        status="archived",
    )
    db.commit()

    result2 = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
        query="keyword match archived",
    )
    ids2 = {m.id for m in result2.memories}
    assert archived_kw.id not in ids2, "archived memory must not re-enter via keyword fallback"


# ---------------------------------------------------------------------------
# Hard filter survives graph expansion
# ---------------------------------------------------------------------------


def test_graph_expansion_cannot_reintroduce_forbidden_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # Seed memory (active, passes hard filter)
    seed = _make_memory(db, space_id=a, user_id=ua.id, content="seed", importance=0.9)
    # Archived memory related to seed via graph
    archived_related = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="related but archived", status="archived",
    )
    relation = MemoryRelation(
        id=_new_id(),
        space_id=a,
        source_type="memory",
        source_id=seed.id,
        target_type="memory",
        target_id=archived_related.id,
        relation_type="related_to",
    )
    db.add(relation)
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
        workspace_id=None,
    )
    ids = {m.id for m in result.memories}
    assert archived_related.id not in ids, (
        "archived memory must not re-enter via graph expansion"
    )


# ---------------------------------------------------------------------------
# Ranking: symbol match outranks keyword fallback
# ---------------------------------------------------------------------------


def test_symbol_match_outranks_keyword_fallback(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # Symbol match: memory owned by user_a (subject_user_id match)
    symbol_mem = _make_memory(
        db, space_id=a, user_id=ua.id,
        content="symbol-and-keyword content",
        scope_type="user",
        importance=0.5,
    )
    db.commit()

    result = MemoryRetriever(db).retrieve(
        space_id=a,
        user_id=ua.id,
        query="symbol-and-keyword",
    )
    # The memory must be included
    ids = {m.id for m in result.memories}
    assert symbol_mem.id in ids

    # Its stage in source_refs should be 'symbol_match' (not 'keyword_fallback')
    ref = next((r for r in result.source_refs if r["source_id"] == symbol_mem.id), None)
    assert ref is not None, "Symbol-matched memory must appear in source_refs"
    assert ref["stage"] == "symbol_match", (
        f"Expected stage=symbol_match, got {ref['stage']!r}"
    )


# ---------------------------------------------------------------------------
# Graph expansion
# ---------------------------------------------------------------------------


def test_graph_expansion_includes_related_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    seed = _make_memory(db, space_id=a, user_id=ua.id, content="seed memory", importance=0.9)
    # "related" must NOT be found by symbol_match: no owner/subject match to ua.id.
    # space_shared visibility so it passes can_read_memory for any space member.
    related = MemoryEntry(
        id=_new_id(),
        space_id=a,
        scope_type="user",
        memory_type="semantic",
        content="related memory",
        status="active",
        visibility="space_shared",
        owner_user_id=None,
        subject_user_id=None,
        importance=0.5,
        namespace="user.default",
    )
    db.add(related)
    relation = MemoryRelation(
        id=_new_id(),
        space_id=a,
        source_type="memory",
        source_id=seed.id,
        target_type="memory",
        target_id=related.id,
        relation_type="related_to",
    )
    db.add(relation)
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id)
    ids = {m.id for m in result.memories}
    assert seed.id in ids, "seed memory must be in results"
    assert related.id in ids, "memory related via graph must be included"

    graph_ref = next(
        (r for r in result.source_refs if r.get("stage") == "graph_expansion"),
        None,
    )
    assert graph_ref is not None, "graph expansion must appear in source_refs"


def test_graph_expansion_respects_hop_limit(db, cross_space_pair_db):
    """Memory 3 hops from seed must not enter result set (max_hops=2)."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    # seed is found by symbol_match (owner matches ua.id).
    # hop1/hop2/hop3 have NO identity link to ua, so they're only reachable via graph.
    seed = _make_memory(db, space_id=a, user_id=ua.id, content="hop-0", importance=0.9)

    def _graph_only_mem(content: str) -> MemoryEntry:
        m = MemoryEntry(
            id=_new_id(),
            space_id=a,
            scope_type="user",
            memory_type="semantic",
            content=content,
            status="active",
            visibility="space_shared",
            owner_user_id=None,
            subject_user_id=None,
            namespace="user.default",
        )
        db.add(m)
        return m

    hop1 = _graph_only_mem("hop-1")
    hop2 = _graph_only_mem("hop-2")
    hop3 = _graph_only_mem("hop-3")
    db.flush()

    for src, tgt in [(seed, hop1), (hop1, hop2), (hop2, hop3)]:
        db.add(MemoryRelation(
            id=_new_id(),
            space_id=a,
            source_type="memory",
            source_id=src.id,
            target_type="memory",
            target_id=tgt.id,
            relation_type="related_to",
        ))
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id)
    ids = {m.id for m in result.memories}
    assert hop3.id not in ids, "memory 3 hops from seed must not enter result (max_hops=2)"


# ---------------------------------------------------------------------------
# Policy inclusion
# ---------------------------------------------------------------------------


def test_active_policies_in_source_refs_stable_prefix(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    active_policy = Policy(
        id=_new_id(),
        space_id=a,
        name="active-policy",
        domain="runtime",
        policy_json={"rule": "allow_all"},
        enabled=True,
        status="active",
    )
    disabled_policy = Policy(
        id=_new_id(),
        space_id=a,
        name="disabled-policy",
        domain="runtime",
        policy_json={"rule": "deny_all"},
        enabled=False,
        status="active",
    )
    superseded_policy = Policy(
        id=_new_id(),
        space_id=a,
        name="superseded-policy",
        domain="runtime",
        policy_json={"rule": "old"},
        enabled=True,
        status="superseded",
    )
    db.add_all([active_policy, disabled_policy, superseded_policy])
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id)

    policy_ref_ids = {
        r["source_id"]
        for r in result.source_refs
        if r.get("source_type") == "policy"
    }
    assert active_policy.id in policy_ref_ids, "active policy must appear in source_refs"
    assert disabled_policy.id not in policy_ref_ids, "disabled policy must not appear"
    assert superseded_policy.id not in policy_ref_ids, "superseded policy must not appear"

    for ref in result.source_refs:
        if ref.get("source_type") == "policy":
            assert ref.get("section") == "stable_prefix", "all policy refs must be in stable_prefix"


# ---------------------------------------------------------------------------
# Retrieval trace structure
# ---------------------------------------------------------------------------


def test_retrieval_trace_contains_hard_filter_and_stages(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    db.commit()

    result = MemoryRetriever(db).retrieve(space_id=a, user_id=ua.id, query="anything")
    trace = result.retrieval_trace

    assert "hard_filter" in trace
    assert trace["hard_filter"]["cross_space_blocked"] is True
    assert trace["hard_filter"]["private_other_user_blocked"] is True

    assert "stages" in trace
    stage_names = [s["stage"] for s in trace["stages"]]
    assert "symbol_match" in stage_names
    assert "keyword_fallback" in stage_names
    assert "graph_expansion" in stage_names
