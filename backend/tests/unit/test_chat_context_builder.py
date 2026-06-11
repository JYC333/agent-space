"""Unit tests for ChatContextBuilder — Personal Assistant / contextual chat path.

Verifies:
1. Existing ContextBuilder + MemoryRetriever are reused, not duplicated.
2. context_policy_json.sources controls which source types are allowed.
3. Explicit / manual context is always prioritised first.
4. Memory, knowledge items, sources, and activity records are included when available.
5. Disabled context types are excluded even if rows exist.
6. ContextSnapshot and ContextSnapshotItem rows are persisted by persist_snapshot().
7. Token budget and max_items truncation work correctly.
8. AgentVersion context_policy_json is the boundary — AgentVersion is never mutated.
9. No embeddings / vector / graph dependency is imported or called.
"""

from __future__ import annotations

import uuid

import pytest

from app.memory.chat_context import ChatContextBuilder, _ALL_SOURCES
from app.models import AgentVersion, ContextSnapshot, ContextSnapshotItem
from app.schemas import ContextBundle, ContextBundleItem, ContextRequest
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _new_id() -> str:
    return str(uuid.uuid4())


def _req(**kwargs) -> ContextRequest:
    base = dict(space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID)
    base.update(kwargs)
    return ContextRequest(**base)


# ---------------------------------------------------------------------------
# Reuse guard — no duplicate context infrastructure
# ---------------------------------------------------------------------------


def test_chat_context_builder_reuses_memory_retriever():
    """ChatContextBuilder delegates memory reads to the existing MemoryRetriever."""
    from app.memory.retriever import MemoryRetriever
    import inspect

    src = inspect.getsource(ChatContextBuilder._select_memory)
    assert "MemoryRetriever" in src, (
        "ChatContextBuilder._select_memory must delegate to MemoryRetriever, not reimplement retrieval"
    )


def test_no_embeddings_or_vector_import():
    """ChatContextBuilder must not import embeddings, vector DB, or graph traversal."""
    import app.memory.chat_context as mod
    import inspect

    src = inspect.getsource(mod)
    forbidden = ["numpy", "faiss", "pgvector", "sentence_transformers", "openai.embeddings"]
    for lib in forbidden:
        assert lib not in src, (
            f"chat_context.py must not import or reference {lib!r} — "
            "advanced retrieval is future scope"
        )


# ---------------------------------------------------------------------------
# ContextRequest / ContextBundle schema
# ---------------------------------------------------------------------------


def test_context_request_defaults():
    req = _req()
    assert req.space_id == PERSONAL_SPACE_ID
    assert req.user_id == DEFAULT_USER_ID
    assert req.manual_context == []
    assert req.max_tokens == 4000
    assert req.max_items == 20


def test_context_bundle_defaults():
    bundle = ContextBundle()
    assert bundle.items == []
    assert bundle.token_count == 0
    assert bundle.truncated is False
    assert bundle.snapshot_id is None


# ---------------------------------------------------------------------------
# Policy boundary — context_policy_json.sources
# ---------------------------------------------------------------------------


def test_empty_policy_allows_all_sources(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    # context_policy_json defaults to {} so all sources are allowed.
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    assert version.context_policy_json == {}

    builder = ChatContextBuilder(db)
    allowed, policy = builder._load_policy(version.id)
    assert allowed == _ALL_SOURCES
    assert policy == {}


def test_sources_list_restricts_allowed_types(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory", "workspace"]}
    db.flush()

    builder = ChatContextBuilder(db)
    allowed, policy = builder._load_policy(version.id)
    assert allowed == frozenset({"memory", "workspace"})


def test_unknown_sources_in_policy_are_silently_dropped(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory", "nonexistent_source"]}
    db.flush()

    builder = ChatContextBuilder(db)
    allowed, _ = builder._load_policy(version.id)
    assert "memory" in allowed
    assert "nonexistent_source" not in allowed


def test_absent_agent_version_id_allows_all_sources(db):
    builder = ChatContextBuilder(db)
    allowed, policy = builder._load_policy(None)
    assert allowed == _ALL_SOURCES
    assert policy == {}


def test_nonexistent_agent_version_id_allows_all_sources(db):
    builder = ChatContextBuilder(db)
    allowed, policy = builder._load_policy(_new_id())
    assert allowed == _ALL_SOURCES
    assert policy == {}


# ---------------------------------------------------------------------------
# Manual / explicit context priority
# ---------------------------------------------------------------------------


def test_manual_context_is_first_in_bundle(db):
    manual = [{"id": _new_id(), "title": "Pinned note", "content": "Remember this."}]
    req = _req(manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert len(bundle.items) >= 1
    first = bundle.items[0]
    assert first.item_type == "manual_context"
    assert first.reason == "explicit_selection"
    assert first.score == 1.0


def test_manual_context_score_highest(db):
    manual = [{"title": "A", "content": "content A"}, {"title": "B", "content": "content B"}]
    req = _req(manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    manual_items = [i for i in bundle.items if i.item_type == "manual_context"]
    assert len(manual_items) == 2
    assert all(i.score == 1.0 for i in manual_items)


def test_manual_context_disabled_by_policy(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    # Explicitly exclude manual_context from allowed sources.
    version.context_policy_json = {"sources": ["memory"]}
    db.flush()

    manual = [{"title": "should be excluded", "content": "top secret"}]
    req = _req(agent_version_id=version.id, manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    types = [i.item_type for i in bundle.items]
    assert "manual_context" not in types


# ---------------------------------------------------------------------------
# Workspace and project metadata
# ---------------------------------------------------------------------------


def test_workspace_metadata_included_when_workspace_id_present(db):
    ws = factories.create_test_workspace(db, space_id=PERSONAL_SPACE_ID)
    req = _req(workspace_id=ws.id)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    ws_items = [i for i in bundle.items if i.item_type == "workspace"]
    assert len(ws_items) == 1
    assert ws_items[0].item_id == ws.id
    assert ws_items[0].reason == "current_workspace"


def test_project_metadata_included_when_project_id_present(db):
    proj = factories.create_test_project(
        db, space_id=PERSONAL_SPACE_ID, description="Goal description"
    )
    req = _req(project_id=proj.id)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    proj_items = [i for i in bundle.items if i.item_type == "project"]
    assert len(proj_items) == 1
    assert proj_items[0].item_id == proj.id
    assert proj_items[0].reason == "current_project"


def test_workspace_not_included_when_policy_excludes_it(db):
    ws = factories.create_test_workspace(db, space_id=PERSONAL_SPACE_ID)
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory"]}
    db.flush()

    req = _req(agent_version_id=version.id, workspace_id=ws.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert not any(i.item_type == "workspace" for i in bundle.items)


def test_workspace_not_included_when_workspace_id_absent(db):
    req = _req()  # No workspace_id.
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert not any(i.item_type == "workspace" for i in bundle.items)


# ---------------------------------------------------------------------------
# Knowledge items
# ---------------------------------------------------------------------------


def test_knowledge_items_included_when_available(db):
    ki = factories.create_test_knowledge_item(
        db,
        space_id=PERSONAL_SPACE_ID,
        title="How to deploy",
        content="Run ./ops/scripts/start.sh to deploy.",
        item_type="concept",
    )

    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    ki_items = [i for i in bundle.items if i.item_type == "knowledge_item"]
    assert any(i.item_id == ki.id for i in ki_items)


def test_knowledge_items_excluded_when_policy_disables_them(db):
    factories.create_test_knowledge_item(
        db,
        space_id=PERSONAL_SPACE_ID,
        title="Excluded doc",
        content="Should not appear.",
        item_type="concept",
    )
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory", "workspace"]}
    db.flush()

    req = _req(agent_version_id=version.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert not any(i.item_type == "knowledge_item" for i in bundle.items)


# ---------------------------------------------------------------------------
# Activity records
# ---------------------------------------------------------------------------


def test_activity_records_included_when_available(db):
    act = factories.create_test_activity(
        db,
        space_id=PERSONAL_SPACE_ID,
        title="User action",
        content="Deployed to prod.",
    )

    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    act_items = [i for i in bundle.items if i.item_type == "activity_record"]
    assert any(i.item_id == act.id for i in act_items)


def test_activity_records_excluded_when_policy_disables_them(db):
    factories.create_test_activity(
        db, space_id=PERSONAL_SPACE_ID, title="Should be excluded", content="nope"
    )
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory"]}
    db.flush()

    req = _req(agent_version_id=version.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert not any(i.item_type == "activity_record" for i in bundle.items)


# ---------------------------------------------------------------------------
# Token budget and max_items truncation
# ---------------------------------------------------------------------------


def test_max_items_truncation(db):
    for i in range(5):
        factories.create_test_knowledge_item(
            db, space_id=PERSONAL_SPACE_ID, title=f"Doc {i}", content="x" * 100, item_type="concept"
        )
    for i in range(5):
        factories.create_test_activity(
            db, space_id=PERSONAL_SPACE_ID, title=f"Act {i}", content="y" * 100
        )

    req = _req(max_items=3)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert len(bundle.items) <= 3
    assert bundle.truncated is True


def test_max_tokens_truncation(db):
    # Each knowledge item has ~200 chars → ~50 tokens; set budget to 60 tokens.
    for i in range(5):
        factories.create_test_knowledge_item(
            db,
            space_id=PERSONAL_SPACE_ID,
            title=f"Big doc {i}",
            content="x" * 200,
            item_type="concept",
        )

    req = _req(max_tokens=60, max_items=100)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert bundle.truncated is True
    assert bundle.token_count <= 60 + 50  # allow one-item overshoot


def test_policy_max_items_overrides_request_max_items(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"max_items": 2}
    db.flush()

    for i in range(5):
        factories.create_test_activity(
            db, space_id=PERSONAL_SPACE_ID, title=f"Act {i}", content="body"
        )

    req = _req(agent_version_id=version.id, max_items=50)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    assert len(bundle.items) <= 2


def test_deduplication_of_repeated_items(db):
    manual = [
        {"id": "same-id", "title": "Dup A", "content": "first"},
        {"id": "same-id", "title": "Dup B", "content": "second"},
    ]
    req = _req(manual_context=manual)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    manual_items = [i for i in bundle.items if i.item_type == "manual_context"]
    # Only the first occurrence of ("manual_context", "same-id") is kept.
    assert len(manual_items) == 1


# ---------------------------------------------------------------------------
# ContextSnapshot and ContextSnapshotItem persistence
# ---------------------------------------------------------------------------


def test_persist_snapshot_creates_context_snapshot(db):
    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    assert snap is not None
    assert snap.space_id == PERSONAL_SPACE_ID
    assert snap.request_json is not None
    assert bundle.snapshot_id == snap.id

    # Row is visible in the same session.
    fetched = db.query(ContextSnapshot).filter(ContextSnapshot.id == snap.id).first()
    assert fetched is not None


def test_persist_snapshot_creates_snapshot_items(db):
    ws = factories.create_test_workspace(db, space_id=PERSONAL_SPACE_ID)
    manual = [{"title": "Note", "content": "Important detail."}]
    req = _req(workspace_id=ws.id, manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    items = db.query(ContextSnapshotItem).filter(
        ContextSnapshotItem.context_snapshot_id == snap.id
    ).all()
    assert len(items) == len(bundle.items)

    types = {i.item_type for i in items}
    assert "manual_context" in types
    assert "workspace" in types


def test_persist_snapshot_stores_item_fields(db):
    manual = [{"id": "manual-ref", "title": "My note", "content": "Remember to test."}]
    req = _req(manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    sni = (
        db.query(ContextSnapshotItem)
        .filter(
            ContextSnapshotItem.context_snapshot_id == snap.id,
            ContextSnapshotItem.item_type == "manual_context",
        )
        .first()
    )
    assert sni is not None
    assert sni.title == "My note"
    assert sni.excerpt is not None
    assert sni.score == 1.0
    assert sni.reason == "explicit_selection"


def test_persist_snapshot_session_and_run_absent_when_not_provided(db):
    """When session_id and run_id are absent from ContextRequest, snapshot fields are None."""
    req = _req()

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    # session_id and run_id default to None and are stored as null on the snapshot.
    assert snap.session_id is None
    assert snap.run_id is None


def test_persist_snapshot_stores_token_estimate(db):
    manual = [{"title": "X", "content": "abc"}]
    req = _req(manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    assert snap.token_estimate == bundle.token_count


def test_persist_snapshot_derives_agent_id_from_version(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()

    req = _req(agent_version_id=version.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    assert snap.agent_id == agent.id


def test_persist_snapshot_update_existing(db):
    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    snap_id = snap.id
    # Build again with different content and update the same snapshot.
    req2 = _req(manual_context=[{"title": "Updated", "content": "new content"}])
    bundle2 = builder.build(req2)
    snap2 = builder.persist_snapshot(bundle2, req2, context_snapshot_id=snap_id)

    assert snap2.id == snap_id
    assert snap2.token_estimate == bundle2.token_count


def test_list_snapshot_items_returns_items_in_order(db):
    manual = [{"title": "A", "content": "first"}, {"title": "B", "content": "second"}]
    req = _req(manual_context=manual)

    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    items = builder.list_snapshot_items(snap.id)
    assert len(items) == len(bundle.items)


# ---------------------------------------------------------------------------
# AgentVersion immutability — build() must not mutate the version row
# ---------------------------------------------------------------------------


def test_build_does_not_mutate_agent_version(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    original_policy = dict(version.context_policy_json)
    original_version_id = version.id

    req = _req(agent_version_id=version.id, manual_context=[{"title": "X", "content": "Y"}])
    builder = ChatContextBuilder(db)
    builder.build(req)
    db.flush()

    # Reload from DB to confirm no mutation.
    version_after = db.query(AgentVersion).filter(AgentVersion.id == original_version_id).first()
    assert version_after.context_policy_json == original_policy


# ---------------------------------------------------------------------------
# Space boundary — items from a different space are excluded
# ---------------------------------------------------------------------------


def test_knowledge_items_from_other_space_excluded(db):
    other_space = _new_id()
    from app.models import Space, SpaceMembership

    db.add(Space(id=other_space, name="Other"))
    db.flush()

    factories.create_test_knowledge_item(
        db, space_id=other_space, title="Foreign doc", content="Secret.", item_type="concept"
    )

    req = _req()  # Uses PERSONAL_SPACE_ID.
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    ki_ids = {i.item_id for i in bundle.items if i.item_type == "knowledge_item"}
    # No knowledge items from other_space should appear.
    all_ki = db.query(__import__("app.models", fromlist=["KnowledgeItem"]).KnowledgeItem).filter(
        __import__("app.models", fromlist=["KnowledgeItem"]).KnowledgeItem.space_id == other_space
    ).all()
    other_ids = {ki.id for ki in all_ki}
    assert not ki_ids.intersection(other_ids)


# ---------------------------------------------------------------------------
# Retrieval trace
# ---------------------------------------------------------------------------


def test_bundle_retrieval_trace_contains_allowed_sources(db):
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    version.context_policy_json = {"sources": ["memory", "knowledge_item"]}
    db.flush()

    req = _req(agent_version_id=version.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    trace = bundle.retrieval_trace
    assert "allowed_sources" in trace
    assert set(trace["allowed_sources"]) == {"memory", "knowledge_item"}
    assert trace["context_policy_applied"] is True


def test_bundle_retrieval_trace_shows_no_policy_when_no_version(db):
    req = _req()  # No agent_version_id.
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    trace = bundle.retrieval_trace
    assert trace["context_policy_applied"] is False
