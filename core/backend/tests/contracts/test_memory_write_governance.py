"""Contract: public memory write routes create Proposals, never direct MemoryEntry mutations.

- POST   /memory          → 202 + memory_create Proposal
- PATCH  /memory/{id}     → 202 + memory_update Proposal
- DELETE /memory/{id}     → 202 + memory_archive Proposal
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func

from app.models import MemoryEntry, Proposal
from app.memory.proposals import ProposalService
from app.policy.domains import MEMORY_PRIVATE_PLACEMENT
from app.policy.enforcement import check_private_memory_placement
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# POST /memory — memory_create proposal
# ---------------------------------------------------------------------------


def test_post_memory_creates_proposal_not_memory_entry(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()

    r = cross_space_pair["client_a"].post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "Governance test",
            "content": "No direct write allowed",
            "type": "semantic",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "space_shared",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_create"
    assert body["status"] == "pending"

    after = db.query(func.count(MemoryEntry.id)).filter(
        MemoryEntry.space_id == a, MemoryEntry.status == "active"
    ).scalar()
    assert after == before, "POST /memory must not create active MemoryEntry"


def test_post_memory_proposal_has_correct_payload(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    r = cross_space_pair["client_a"].post(
        "/api/v1/memory",
        params=_params(a, ua.id),
        json={
            "title": "Payload check",
            "content": "content body",
            "type": "preference",
            "scope": "user",
            "namespace": "user.prefs",
            "visibility": "private",
            "sensitivity_level": "normal",
        },
    )
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop is not None
    assert prop.proposal_type == "memory_create"
    payload = prop.payload_json
    assert payload["operation"] == "create"
    assert payload["proposed_content"] == "content body"
    assert payload["target_scope"] == "user"
    assert payload["memory_type"] == "preference"
    entries = payload.get("provenance_entries") or []
    assert any(e.get("source_type") == "user_confirmation" for e in entries)


def test_accepting_private_memory_proposal_in_team_space_is_rejected(db, cross_space_pair):
    """Proposal apply path enforces private placement — clear error for callers."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        title="Private in team",
        payload_json={
            "operation": "create",
            "proposed_content": "must not land",
            "target_scope": "user",
            "memory_type": "semantic",
            "target_visibility": "private",
            "owner_user_id": ua.id,
        },
        commit=True,
    )

    with pytest.raises(ValueError, match="personal"):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)


def test_accepting_private_memory_proposal_in_personal_space_allowed(db, test_space, test_user):
    a = test_space.id
    ua = test_user
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        title="Private in personal",
        payload_json={
            "operation": "create",
            "proposed_content": "personal ok",
            "target_scope": "user",
            "memory_type": "semantic",
            "target_visibility": "private",
            "owner_user_id": ua.id,
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.memory is not None
    assert result.memory.visibility == "private"


def test_allow_with_log_space_shared_store_write_traces_and_succeeds(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key=MEMORY_PRIVATE_PLACEMENT,
        enforcement_mode="allow_with_log",
        rule_json={"policy_domain": MEMORY_PRIVATE_PLACEMENT, "effect": "allow_with_log"},
        commit=True,
    )
    with patch("app.policy.enforcement.record_policy_decision_trace") as trace:
        check_private_memory_placement(db, space_id=a, visibility="space_shared", acting_user_id=ua.id)
    assert trace.called
    assert any(
        c.kwargs.get("domain") == MEMORY_PRIVATE_PLACEMENT and c.kwargs.get("outcome") == "allowed"
        for c in trace.call_args_list
    )


def test_deny_policy_rejects_private_placement_in_personal_space(db, test_space, test_user):
    factories.create_test_policy(
        db,
        space_id=test_space.id,
        domain="memory",
        policy_key=MEMORY_PRIVATE_PLACEMENT,
        enforcement_mode="deny",
        rule_json={"policy_domain": MEMORY_PRIVATE_PLACEMENT},
        commit=True,
    )
    with pytest.raises(ValueError, match="denied by active policy"):
        check_private_memory_placement(
            db,
            space_id=test_space.id,
            visibility="private",
            acting_user_id=test_user.id,
        )


def test_allow_policy_cannot_override_private_placement_in_team_space(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_policy(
        db,
        space_id=a,
        domain="memory",
        policy_key=MEMORY_PRIVATE_PLACEMENT,
        enforcement_mode="allow",
        rule_json={"policy_domain": MEMORY_PRIVATE_PLACEMENT},
        commit=True,
    )
    with pytest.raises(ValueError, match="personal"):
        check_private_memory_placement(db, space_id=a, visibility="private", acting_user_id=ua.id)


def test_accepting_space_shared_proposal_in_team_space_allowed(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        title="Shared in team",
        payload_json={
            "operation": "create",
            "proposed_content": "team shared ok",
            "target_scope": "agent",
            "memory_type": "semantic",
            "target_visibility": "space_shared",
            "owner_user_id": ua.id,
        },
        commit=True,
    )

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None
    assert result.memory is not None
    assert result.memory.visibility == "space_shared"


# ---------------------------------------------------------------------------
# PATCH /memory/{id} — memory_update proposal
# ---------------------------------------------------------------------------


def test_patch_memory_creates_proposal_not_mutation(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="unchanged", scope_type="agent", namespace="ns.c",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = cross_space_pair["client_a"].patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
        json={"content": "proposed new content"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_update"
    assert body["status"] == "pending"

    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_now.content == "unchanged", "PATCH /memory must not mutate MemoryEntry"


def test_patch_memory_proposal_contains_target_id(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="x", scope_type="agent", namespace="ns.tid",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = cross_space_pair["client_a"].patch(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
        json={"content": "y"},
    )
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop.payload_json["target_memory_id"] == mem.id
    assert prop.payload_json["operation"] == "update"


# ---------------------------------------------------------------------------
# DELETE /memory/{id} — memory_archive proposal
# ---------------------------------------------------------------------------


def test_delete_memory_creates_archive_proposal_not_deletion(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="survives", scope_type="agent", namespace="ns.del",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = cross_space_pair["client_a"].delete(
        f"/api/v1/memory/{mem.id}",
        params=_params(a, ua.id),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["proposal_type"] == "memory_archive"
    assert body["status"] == "pending"

    db.expire_all()
    mem_now = db.query(MemoryEntry).filter(MemoryEntry.id == mem.id).first()
    assert mem_now is not None, "DELETE /memory must not hard-delete MemoryEntry"
    assert mem_now.status == "active", "DELETE /memory must not archive MemoryEntry directly"
    assert mem_now.deleted_at is None


def test_delete_memory_proposal_contains_target_id(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db, space_id=a, content="x", scope_type="agent", namespace="ns.arc",
        owner_user_id=ua.id, commit=False,
    )
    mem.visibility = "space_shared"
    db.commit()

    r = cross_space_pair["client_a"].delete(f"/api/v1/memory/{mem.id}", params=_params(a, ua.id))
    assert r.status_code == 202
    proposal_id = r.json()["id"]

    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    assert prop.payload_json["target_memory_id"] == mem.id
    assert prop.payload_json["operation"] == "archive"
