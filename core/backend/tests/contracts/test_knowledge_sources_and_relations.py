"""Contract tests for the refactored RM Wiki knowledge foundation.

Covers:
  * KnowledgeItem type validation allows the 9 semantic types and rejects
    the removed ``source`` / ``answer`` types (API + proposal-apply layers).
  * Source is an independent provenance object (direct CRUD, not proposals).
  * KnowledgeItemSource links items to sources (derived_from / supported_by).
  * KnowledgeItemRelation links items to items (answers / summarizes / updates).
"""
from __future__ import annotations

import pytest
import sqlalchemy
from sqlalchemy import func

from app.models import KnowledgeItem, KnowledgeItemRelation, KnowledgeItemSource, Source
from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


SEMANTIC_ITEM_TYPES = [
    "knowledge",
    "idea",
    "experience",
    "reflection",
    "lesson",
    "procedure",
    "decision",
    "question",
    "summary",
]


# ---------------------------------------------------------------------------
# 1 + 2. KnowledgeItem type validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("item_type", SEMANTIC_ITEM_TYPES)
def test_create_proposal_accepts_each_semantic_type(db, same_space_pair, item_type):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(space),
        json={"item_type": item_type, "title": f"{item_type} item", "content": "body"},
    )
    assert r.status_code == 202, r.text
    accepted = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(space)
    )
    assert accepted.status_code == 200
    item_id = accepted.json()["result"]["knowledge_item"]["id"]
    db.expire_all()
    assert db.get(KnowledgeItem, item_id).item_type == item_type  # type: ignore[union-attr]
    del ua


@pytest.mark.parametrize("bad_type", ["source", "answer"])
def test_create_proposal_rejects_removed_types_at_api(db, same_space_pair, bad_type):
    space = same_space_pair["space_id"]
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(space),
        json={"item_type": bad_type, "title": "nope", "content": "body"},
    )
    assert r.status_code == 422
    db.expire_all()
    assert db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 0


@pytest.mark.parametrize("bad_type", ["source", "answer"])
def test_proposal_apply_rejects_removed_types_in_payload(db, same_space_pair, bad_type):
    """A hand-built proposal payload smuggling a removed type must fail on accept."""
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=space,
        proposal_type="knowledge_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "item_type": bad_type,
            "title": "smuggled",
            "content": "body",
            "content_format": "markdown",
            "visibility": "space_shared",
            "verification_status": "unverified",
            "reflection_status": "unreviewed",
        },
        commit=True,
    )
    accepted = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept", params=_params(space)
    )
    assert accepted.status_code == 422
    db.expire_all()
    assert db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 0


def test_db_check_constraint_rejects_removed_item_type(db, same_space_pair):
    space = same_space_pair["space_id"]
    row = KnowledgeItem(
        space_id=space,
        item_type="source",
        title="bad",
        content="body",
        content_format="markdown",
        status="active",
        visibility="space_shared",
        verification_status="unverified",
        reflection_status="unreviewed",
        tags_json=[],
        version=1,
    )
    db.add(row)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.flush()
    db.rollback()


# ---------------------------------------------------------------------------
# 3. Source is an independent provenance object
# ---------------------------------------------------------------------------


def test_source_can_be_created_and_fetched(db, same_space_pair):
    space = same_space_pair["space_id"]
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/sources",
        params=_params(space),
        json={"source_type": "webpage", "title": "Example", "uri": "https://example.com"},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    assert r.json()["status"] == "raw"

    got = same_space_pair["client_a"].get(f"/api/v1/knowledge/sources/{source_id}", params=_params(space))
    assert got.status_code == 200
    assert got.json()["source_type"] == "webpage"

    # Sources must not appear in the semantic KnowledgeItem list.
    items = same_space_pair["client_a"].get("/api/v1/knowledge/items", params=_params(space))
    assert items.status_code == 200
    assert items.json()["items"] == []


def test_source_archive_sets_status_archived(db, same_space_pair):
    space = same_space_pair["space_id"]
    source = factories.create_test_source(db, space_id=space, commit=True)
    r = same_space_pair["client_a"].delete(f"/api/v1/knowledge/sources/{source.id}", params=_params(space))
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    db.expire_all()
    assert db.get(Source, source.id).status == "archived"  # type: ignore[union-attr]


def test_source_can_reference_activity_record(db, same_space_pair):
    space = same_space_pair["space_id"]
    activity = factories.create_test_activity(db, space_id=space, commit=True)
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/sources",
        params=_params(space),
        json={
            "source_type": "activity_record",
            "title": "from activity",
            "source_activity_id": activity.id,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["source_activity_id"] == activity.id


# ---------------------------------------------------------------------------
# 4. KnowledgeItemSource evidence links
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relation_type", ["derived_from", "supported_by"])
def test_link_item_to_source(db, same_space_pair, relation_type):
    space = same_space_pair["space_id"]
    item = factories.create_test_knowledge_item(db, space_id=space, commit=False)
    source = factories.create_test_source(db, space_id=space, commit=True)
    r = same_space_pair["client_a"].post(
        f"/api/v1/knowledge/items/{item.id}/sources",
        params=_params(space),
        json={"source_id": source.id, "relation_type": relation_type, "quote": "evidence"},
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]

    listed = same_space_pair["client_a"].get(
        f"/api/v1/knowledge/items/{item.id}/sources", params=_params(space)
    )
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [link_id]

    # Trace back: the source lists the items it backs.
    back = same_space_pair["client_a"].get(
        f"/api/v1/knowledge/sources/{source.id}/items", params=_params(space)
    )
    assert back.status_code == 200
    assert {row["knowledge_item_id"] for row in back.json()} == {item.id}

    # Unlink removes the evidence link without touching the item or source.
    removed = same_space_pair["client_a"].delete(
        f"/api/v1/knowledge/items/{item.id}/sources/{link_id}", params=_params(space)
    )
    assert removed.status_code == 204
    db.expire_all()
    assert db.get(KnowledgeItemSource, link_id) is None
    assert db.get(KnowledgeItem, item.id) is not None
    assert db.get(Source, source.id) is not None


def test_duplicate_evidence_link_is_rejected(db, same_space_pair):
    space = same_space_pair["space_id"]
    item = factories.create_test_knowledge_item(db, space_id=space, commit=False)
    source = factories.create_test_source(db, space_id=space, commit=True)
    payload = {"source_id": source.id, "relation_type": "cites"}
    first = same_space_pair["client_a"].post(
        f"/api/v1/knowledge/items/{item.id}/sources", params=_params(space), json=payload
    )
    assert first.status_code == 201
    dup = same_space_pair["client_a"].post(
        f"/api/v1/knowledge/items/{item.id}/sources", params=_params(space), json=payload
    )
    assert dup.status_code == 422


# ---------------------------------------------------------------------------
# 5. KnowledgeItemRelation semantic item-to-item relations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relation_type", ["answers", "summarizes", "updates"])
def test_item_to_item_relation_types(db, same_space_pair, relation_type):
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    # e.g. a knowledge item --answers--> a question item.
    from_item = factories.create_test_knowledge_item(db, space_id=space, item_type="knowledge", commit=False)
    to_item = factories.create_test_knowledge_item(db, space_id=space, item_type="question", commit=True)

    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(space),
        json={
            "from_item_id": from_item.id,
            "to_item_id": to_item.id,
            "relation_type": relation_type,
            "status": "active",
            "note": "linked",
        },
    )
    assert r.status_code == 202, r.text
    accepted = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{r.json()['id']}/accept", params=_params(space)
    )
    assert accepted.status_code == 200
    relation_id = accepted.json()["result"]["knowledge_relation"]["id"]
    db.expire_all()
    relation = db.get(KnowledgeItemRelation, relation_id)
    assert relation is not None
    assert relation.relation_type == relation_type
    assert relation.note == "linked"
    del ua


def test_relation_proposal_rejects_removed_relation_type(db, same_space_pair):
    space = same_space_pair["space_id"]
    from_item = factories.create_test_knowledge_item(db, space_id=space, commit=False)
    to_item = factories.create_test_knowledge_item(db, space_id=space, commit=True)
    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(space),
        json={
            "from_item_id": from_item.id,
            "to_item_id": to_item.id,
            "relation_type": "example_of",  # removed from vocabulary
        },
    )
    assert r.status_code == 422
