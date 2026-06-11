"""Invariant: Knowledge Base ingestion/review boundary.

Proves that:
1. Raw captures (user_capture) create ActivityRecord only — no KnowledgeItem.
2. Article inputs (web_capture) create ActivityRecord/Artifact only — no KnowledgeItem.
3. Agent-generated knowledge candidates create a pending Proposal only — no KnowledgeItem.
4. Accepting a knowledge_create proposal creates an active KnowledgeItem.
   (Canonical coverage lives in tests/contracts/test_knowledge_api.py; this file
   adds a service-level assertion as a cross-layer guard.)
5. Rejecting a knowledge_create proposal creates no KnowledgeItem.
6. Rejecting a knowledge_relation_create proposal creates no KnowledgeItemRelation.

These tests are distinct from tests/contracts/test_knowledge_api.py: they guard
the data-layer boundary (no object created before accept) rather than the API
contract. Tests 1–3 exercise non-knowledge input paths; tests 5–6 exercise the
reject path that has no coverage elsewhere.
"""

from __future__ import annotations

from sqlalchemy import func

from app.proposals import ProposalApplyService
from app.models import ActivityRecord, KnowledgeItem, KnowledgeItemRelation, MemoryEntry, Proposal
from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# 1. Raw capture creates ActivityRecord only — no KnowledgeItem
# ---------------------------------------------------------------------------


def test_raw_capture_creates_activity_record_only(api_client, db, cross_space_pair):
    """POST /activity with user_capture must create an ActivityRecord and no KnowledgeItem."""
    a = cross_space_pair["space_a_id"]
    before = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "user_capture",
            "content": "A raw thought I want to remember",
            "title": "raw thought",
        },
    )
    assert r.status_code == 200, r.text
    activity_id = r.json()["id"]

    db.expire_all()
    assert (
        db.query(ActivityRecord).filter(ActivityRecord.id == activity_id).first() is not None
    ), "ActivityRecord must be created for user_capture"

    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after == before, "raw user_capture must not create any KnowledgeItem"


# ---------------------------------------------------------------------------
# 2. Article input creates ActivityRecord / Artifact only — no KnowledgeItem
# ---------------------------------------------------------------------------


def test_article_input_creates_activity_record_only(api_client, db, cross_space_pair):
    """POST /activity with web_capture (article input) must not create any KnowledgeItem."""
    a = cross_space_pair["space_a_id"]
    before = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "web_capture",
            "content": "Full article body text captured from the web",
            "title": "Some article",
            "source_url": "https://example.com/article",
        },
    )
    assert r.status_code == 200, r.text
    activity_id = r.json()["id"]

    db.expire_all()
    rec = db.query(ActivityRecord).filter(ActivityRecord.id == activity_id).first()
    assert rec is not None, "ActivityRecord must be created for web_capture"
    assert rec.source_url == "https://example.com/article"

    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after == before, "web_capture (article input) must not create any KnowledgeItem"


def test_file_import_creates_activity_record_only(api_client, db, cross_space_pair):
    """POST /activity with file_import must not create any KnowledgeItem."""
    a = cross_space_pair["space_a_id"]
    before = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/activity",
        params=_params(a),
        json={
            "source_type": "file_import",
            "content": "Contents of an imported document",
            "title": "Imported document",
        },
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after == before, "file_import must not create any KnowledgeItem"


# ---------------------------------------------------------------------------
# 3. Agent-generated knowledge candidate creates pending Proposal only
# ---------------------------------------------------------------------------


def test_agent_knowledge_candidate_creates_pending_proposal_only(db, cross_space_pair_db):
    """A knowledge_create Proposal attributed to an agent must stay pending; no KnowledgeItem is created."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)

    before = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()

    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        proposal_type="knowledge_create",
        created_by_user_id=ua.id,
        created_by_agent_id=agent.id,
        payload_json={
            "operation": "create",
            "item_type": "concept",
            "title": "Agent-derived insight",
            "content": "Agent observed a recurring pattern",
            "content_format": "markdown",
            "visibility": "space_shared",
            "verification_status": "unverified",
            "reflection_status": "unreviewed",
            "owner_user_id": ua.id,
            "tags": [],
            "source_refs": [],
        },
        commit=True,
    )

    db.expire_all()
    loaded = db.get(Proposal, proposal.id)
    assert loaded is not None
    assert loaded.status == "pending", "agent-generated proposal must start as pending"
    assert loaded.created_by_agent_id == agent.id, "proposal must carry agent attribution"

    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after == before, (
        "creating a knowledge_create proposal (even with agent attribution) "
        "must not directly create a KnowledgeItem"
    )


# ---------------------------------------------------------------------------
# 4. Accepting a proposal creates an active KnowledgeItem (service-layer guard)
# ---------------------------------------------------------------------------


def test_accepting_knowledge_create_proposal_creates_active_item(db, cross_space_pair_db):
    """Service-layer guard: ProposalApplyService.apply creates exactly one active KnowledgeItem."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        proposal_type="knowledge_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "item_type": "concept",
            "title": "Accepted knowledge",
            "content": "This content lands only on accept",
            "content_format": "markdown",
            "visibility": "space_shared",
            "verification_status": "unverified",
            "reflection_status": "unreviewed",
            "owner_user_id": ua.id,
            "tags": [],
            "source_refs": [],
        },
        commit=True,
    )

    before = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()

    result = ProposalApplyService(db).apply(
        proposal,
        user_id=ua.id,
        bypass_source_monitoring=True,
        accept_context="internal_seed",
    )
    db.commit()

    db.expire_all()
    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == a).scalar()
    assert after == before + 1, "accepting a knowledge_create proposal must create exactly one KnowledgeItem"
    assert result.knowledge_item is not None
    assert result.knowledge_item.status == "active"
    assert result.knowledge_item.title == "Accepted knowledge"
    assert result.knowledge_item.created_from_proposal_id == proposal.id


# ---------------------------------------------------------------------------
# 5. Rejecting a knowledge_create proposal creates no KnowledgeItem
# ---------------------------------------------------------------------------


def test_reject_knowledge_create_proposal_creates_no_knowledge_item(api_client, db, same_space_pair):
    """Rejecting a knowledge_create proposal must leave no KnowledgeItem in the DB."""
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]

    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/items/proposals",
        params=_params(space),
        json={
            "item_type": "concept",
            "title": "Knowledge to be rejected",
            "content": "This must never become active",
            "content_format": "markdown",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, r.text
    proposal_id = r.json()["id"]

    db.expire_all()
    assert (
        db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar() == 0
    ), "proposal creation must not create KnowledgeItem"

    rejected = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{proposal_id}/reject",
        params=_params(space),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    db.expire_all()
    after = db.query(func.count(KnowledgeItem.id)).filter(KnowledgeItem.space_id == space).scalar()
    assert after == 0, "rejecting a knowledge_create proposal must create no KnowledgeItem"


# ---------------------------------------------------------------------------
# 6. Rejecting a knowledge_relation_create proposal creates no KnowledgeItemRelation
# ---------------------------------------------------------------------------


def test_reject_knowledge_relation_proposal_creates_no_relation(api_client, db, same_space_pair):
    """Rejecting a knowledge_relation_create proposal must leave no KnowledgeItemRelation in the DB."""
    space = same_space_pair["space_id"]
    ua = same_space_pair["user_a"]
    from_item = factories.create_test_knowledge_item(db, space_id=space, title="Source", commit=False)
    to_item = factories.create_test_knowledge_item(db, space_id=space, title="Target", commit=True)

    r = same_space_pair["client_a"].post(
        "/api/v1/knowledge/relations/proposals",
        params=_params(space),
        json={
            "from_item_id": from_item.id,
            "to_item_id": to_item.id,
            "relation_type": "related_to",
        },
    )
    assert r.status_code == 202, r.text
    proposal_id = r.json()["id"]

    db.expire_all()
    assert (
        db.query(func.count(KnowledgeItemRelation.id)).filter(KnowledgeItemRelation.space_id == space).scalar() == 0
    ), "relation proposal creation must not create KnowledgeItemRelation"

    rejected = same_space_pair["client_a"].post(
        f"/api/v1/proposals/{proposal_id}/reject",
        params=_params(space),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    db.expire_all()
    after = db.query(func.count(KnowledgeItemRelation.id)).filter(KnowledgeItemRelation.space_id == space).scalar()
    assert after == 0, "rejecting a knowledge_relation_create proposal must create no KnowledgeItemRelation"


# ---------------------------------------------------------------------------
# 7. Accepted KnowledgeItem does not create a MemoryEntry (no auto-injection)
# ---------------------------------------------------------------------------


def test_accepted_knowledge_item_does_not_create_memory_entry(db, cross_space_pair_db):
    """Service-layer guard: applying a knowledge_create proposal must not create any MemoryEntry.

    KnowledgeItem must not be auto-injected into Memory or ContextBuilder.
    Promotion into Memory is a future explicit proposal flow.
    """
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    before_memory = db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar()

    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        proposal_type="knowledge_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "item_type": "lesson",
            "title": "A lesson that must not become memory",
            "content": "Lesson content stays in knowledge, not injected into agent context",
            "content_format": "markdown",
            "visibility": "space_shared",
            "verification_status": "unverified",
            "reflection_status": "unreviewed",
            "owner_user_id": ua.id,
            "tags": [],
            "source_refs": [],
        },
        commit=True,
    )

    result = ProposalApplyService(db).apply(
        proposal,
        user_id=ua.id,
        bypass_source_monitoring=True,
        accept_context="internal_seed",
    )
    db.commit()

    db.expire_all()
    assert result.knowledge_item is not None, "apply must return a KnowledgeItem"
    assert result.knowledge_item.status == "active"
    assert result.memory is None, "knowledge_create must not produce a MemoryEntry result"

    after_memory = db.query(func.count(MemoryEntry.id)).filter(MemoryEntry.space_id == a).scalar()
    assert after_memory == before_memory, (
        "accepting a knowledge_create proposal must not create any MemoryEntry — "
        "KnowledgeItem is not automatically injected into agent context"
    )


# ---------------------------------------------------------------------------
# 8. KnowledgeItemRelation creation requires proposal accept (service-layer guard)
# ---------------------------------------------------------------------------


def test_knowledge_relation_create_requires_proposal_accept(db, cross_space_pair_db):
    """Service-layer guard: a pending knowledge_relation_create proposal creates no KnowledgeItemRelation
    until ProposalApplyService.apply() is called (i.e., until the proposal is accepted).
    """
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    from_item = factories.create_test_knowledge_item(db, space_id=a, title="From", commit=False)
    to_item = factories.create_test_knowledge_item(db, space_id=a, title="To", commit=False)

    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        proposal_type="knowledge_relation_create",
        created_by_user_id=ua.id,
        payload_json={
            "operation": "relation_create",
            "from_item_id": from_item.id,
            "to_item_id": to_item.id,
            "relation_type": "derived_from",
            "status": "active",
        },
        commit=True,
    )

    db.expire_all()
    before = db.query(func.count(KnowledgeItemRelation.id)).filter(KnowledgeItemRelation.space_id == a).scalar()
    assert before == 0, "pending proposal must not create any KnowledgeItemRelation"

    result = ProposalApplyService(db).apply(
        proposal,
        user_id=ua.id,
        bypass_source_monitoring=True,
        accept_context="internal_seed",
    )
    db.commit()

    db.expire_all()
    after = db.query(func.count(KnowledgeItemRelation.id)).filter(KnowledgeItemRelation.space_id == a).scalar()
    assert after == 1, "accepting a knowledge_relation_create proposal must create exactly one KnowledgeItemRelation"
    assert result.knowledge_relation is not None
    assert result.knowledge_relation.status == "active"
    assert result.knowledge_relation.relation_type == "derived_from"
    assert result.knowledge_relation.source_proposal_id == proposal.id
