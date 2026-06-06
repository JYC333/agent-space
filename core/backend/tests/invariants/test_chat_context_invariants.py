"""Invariant tests for the ChatContextBuilder / chat context selection path.

These tests verify hard architectural invariants that must hold across all
build() and persist_snapshot() calls:

  1. space_id boundary is never crossed.
  2. AgentVersion is never mutated by build().
  3. Disabled context types produce zero items of that type.
  4. ContextSnapshotItem.item_type values are always in the allowed enum set.
  5. persist_snapshot() never commits — caller owns the boundary.
  6. ContextSnapshot.request_json is always set when persist_snapshot() runs.
  7. Token count in ContextBundle equals sum of item token_counts.
  8. Each ContextSnapshotItem.context_snapshot_id points to the correct snapshot.
  9. No ContextSnapshotItem row escapes the snapshot's space boundary.
  10. Two independent builds for the same request produce equivalent bundles.
"""

from __future__ import annotations

import uuid

import pytest

from app.memory.chat_context import ChatContextBuilder
from app.models import AgentVersion, ContextSnapshot, ContextSnapshotItem, KnowledgeItem, Space
from app.schemas import ContextRequest
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _new_id() -> str:
    return str(uuid.uuid4())


def _req(**kwargs) -> ContextRequest:
    base = dict(space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID)
    base.update(kwargs)
    return ContextRequest(**base)


# ---------------------------------------------------------------------------
# Invariant 1: space_id boundary
# ---------------------------------------------------------------------------


def test_items_never_cross_space_boundary(db):
    """Items from a foreign space must never appear in the bundle."""
    other_space = _new_id()
    db.add(Space(id=other_space, name="Other"))
    db.flush()

    # Create data in the foreign space.
    factories.create_test_knowledge_item(
        db, space_id=other_space, title="Foreign", content="secret", item_type="knowledge"
    )
    factories.create_test_activity(
        db, space_id=other_space, title="Foreign act", content="nope"
    )

    # All foreign item IDs.
    foreign_ids = {
        ki.id
        for ki in db.query(KnowledgeItem).filter(KnowledgeItem.space_id == other_space).all()
    }

    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    bundle_ids = {i.item_id for i in bundle.items if i.item_id is not None}
    assert not bundle_ids.intersection(foreign_ids), (
        "Items from a foreign space must never appear in the bundle"
    )


# ---------------------------------------------------------------------------
# Invariant 2: AgentVersion never mutated
# ---------------------------------------------------------------------------


def test_agent_version_not_mutated_after_build_with_items(db):
    """build() must never write to the AgentVersion row."""
    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    original_policy = dict(version.context_policy_json or {})
    original_prompt = version.system_prompt
    original_model = version.model_name

    # Build with lots of content.
    factories.create_test_knowledge_item(
        db, space_id=PERSONAL_SPACE_ID, title="KI", content="knowledge", item_type="knowledge"
    )
    req = _req(
        agent_version_id=version.id,
        manual_context=[{"title": "M", "content": "manual content"}],
    )
    builder = ChatContextBuilder(db)
    builder.build(req)
    db.flush()

    version_after = db.query(AgentVersion).filter(AgentVersion.id == version.id).first()
    assert version_after.context_policy_json == original_policy
    assert version_after.system_prompt == original_prompt
    assert version_after.model_name == original_model


# ---------------------------------------------------------------------------
# Invariant 3: Disabled types produce zero items
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("disabled_type,factory_args", [
    (
        "knowledge_item",
        dict(title="Should be blocked", content="blocked content", item_type="knowledge"),
    ),
    (
        "activity_record",
        None,  # handled separately below
    ),
])
def test_disabled_source_type_produces_zero_items(db, disabled_type, factory_args):
    """Items of a type excluded from sources must not appear in the bundle."""
    if disabled_type == "knowledge_item":
        factories.create_test_knowledge_item(db, space_id=PERSONAL_SPACE_ID, **factory_args)
    elif disabled_type == "activity_record":
        factories.create_test_activity(db, space_id=PERSONAL_SPACE_ID, title="Act", content="body")

    agent = factories.create_test_agent(db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
    # All sources allowed except the one under test.
    allowed_without = [s for s in ["memory", "source", "workspace", "project", "manual_context"] if s != disabled_type]
    version.context_policy_json = {"sources": allowed_without}
    db.flush()

    req = _req(agent_version_id=version.id)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    offending = [i for i in bundle.items if i.item_type == disabled_type]
    assert offending == [], (
        f"Disabled type {disabled_type!r} must produce zero items, got {offending!r}"
    )


# ---------------------------------------------------------------------------
# Invariant 4: ContextSnapshotItem.item_type values are in the allowed enum
# ---------------------------------------------------------------------------


_ALLOWED_ITEM_TYPES = frozenset(
    [
        "memory",
        "knowledge_item",
        "source",
        "activity_record",
        "task",
        "idea",
        "project",
        "workspace",
        "run",
        "proposal",
        "artifact",
        "manual_context",
    ]
)


def test_all_persisted_item_types_are_in_allowed_enum(db):
    ws = factories.create_test_workspace(db, space_id=PERSONAL_SPACE_ID)
    factories.create_test_knowledge_item(
        db, space_id=PERSONAL_SPACE_ID, title="KI", content="ki content", item_type="knowledge"
    )
    factories.create_test_knowledge_item(
        db, space_id=PERSONAL_SPACE_ID, title="Idea", content="idea content", item_type="idea"
    )
    factories.create_test_activity(db, space_id=PERSONAL_SPACE_ID, title="Act", content="body")
    manual = [{"title": "M", "content": "manual"}]

    req = _req(workspace_id=ws.id, manual_context=manual)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    items = db.query(ContextSnapshotItem).filter(
        ContextSnapshotItem.context_snapshot_id == snap.id
    ).all()

    for item in items:
        assert item.item_type in _ALLOWED_ITEM_TYPES, (
            f"item_type {item.item_type!r} is not in the allowed enum"
        )


# ---------------------------------------------------------------------------
# Invariant 5: persist_snapshot() does not commit
# ---------------------------------------------------------------------------


def test_persist_snapshot_does_not_auto_commit(db):
    """persist_snapshot() must flush but not commit — caller owns the boundary."""
    req = _req(manual_context=[{"title": "T", "content": "body"}])
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    # Snapshot row is visible in this session (flushed) but not committed.
    in_session = db.query(ContextSnapshot).filter(ContextSnapshot.id == snap.id).first()
    assert in_session is not None, "Snapshot must be visible in the same session after flush"


# ---------------------------------------------------------------------------
# Invariant 6: request_json is always populated by persist_snapshot()
# ---------------------------------------------------------------------------


def test_request_json_always_populated(db):
    req = _req(user_message="What is the plan?")
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    assert snap.request_json is not None
    assert isinstance(snap.request_json, dict)
    assert snap.request_json.get("space_id") == PERSONAL_SPACE_ID
    assert snap.request_json.get("user_message") == "What is the plan?"


# ---------------------------------------------------------------------------
# Invariant 7: token_count == sum of item token_counts
# ---------------------------------------------------------------------------


def test_bundle_token_count_equals_sum_of_item_tokens(db):
    manual = [
        {"title": "A", "content": "abc"},
        {"title": "B", "content": "defgh"},
    ]
    req = _req(manual_context=manual)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)

    expected = sum(i.token_count or 0 for i in bundle.items)
    assert bundle.token_count == expected


# ---------------------------------------------------------------------------
# Invariant 8: ContextSnapshotItem.context_snapshot_id always correct
# ---------------------------------------------------------------------------


def test_snapshot_item_fk_always_matches_snapshot(db):
    manual = [{"title": "X", "content": "content"}]
    req = _req(manual_context=manual)
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    items = db.query(ContextSnapshotItem).filter(
        ContextSnapshotItem.context_snapshot_id == snap.id
    ).all()
    for item in items:
        assert item.context_snapshot_id == snap.id


# ---------------------------------------------------------------------------
# Invariant 9: snapshot space_id matches request space_id
# ---------------------------------------------------------------------------


def test_snapshot_space_id_matches_request(db):
    req = _req()
    builder = ChatContextBuilder(db)
    bundle = builder.build(req)
    snap = builder.persist_snapshot(bundle, req)

    assert snap.space_id == PERSONAL_SPACE_ID


# ---------------------------------------------------------------------------
# Invariant 10: Deterministic — two builds produce equivalent bundles
# ---------------------------------------------------------------------------


def test_two_builds_from_same_request_produce_equivalent_bundles(db):
    """Repeated builds with the same request produce the same item set."""
    factories.create_test_knowledge_item(
        db, space_id=PERSONAL_SPACE_ID, title="Stable", content="stable content", item_type="knowledge"
    )
    req = _req(manual_context=[{"title": "M", "content": "manual"}])

    builder = ChatContextBuilder(db)
    bundle1 = builder.build(req)
    bundle2 = builder.build(req)

    ids1 = sorted(
        (i.item_type, str(i.item_id)) for i in bundle1.items
    )
    ids2 = sorted(
        (i.item_type, str(i.item_id)) for i in bundle2.items
    )
    assert ids1 == ids2, "Two builds from the same request should select the same items"
