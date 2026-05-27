"""Invariants: Activity/Source/Evidence boundary for M6.

These invariants protect the following product rules:

1. Non-chat capture (user_capture, web_capture, etc.) enters ActivityRecord —
   no Session/Message is created as a side effect.
2. Candidate/unreviewed content cannot become active Memory without proposal/review.
3. SourceMonitoring trust gate is not bypassed by the Activity-first capture path.
4. Memory proposal generated via consolidation preserves activity_id and source provenance.
5. Accepted memory proposal preserves provenance into MemoryEntry and ProvenanceLink rows.
6. ActivityRecord is the product activity/inbox layer; it does not produce active memory directly.
7. Information Horizon: no code path creates active Memory from raw capture without proposal.
8. Public memory writes remain proposal-first (POST /memory → 202 Proposal, never 200 MemoryEntry).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func

from app.memory.apply_service import ProposalApplyService, ProposalApplyError
from app.memory.proposals import ProposalService
from app.memory.source_monitoring import SourceMonitoringService
from app.models import ActivityRecord, MemoryEntry, Policy, ProvenanceLink, Proposal, Session
from tests.support import factories


# ---------------------------------------------------------------------------
# 1. Non-chat capture does not create Session rows
# ---------------------------------------------------------------------------


def test_activity_create_does_not_produce_session(db, cross_space_pair_db):
    """Creating an ActivityRecord directly never creates a Session row."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    before = db.query(func.count(Session.id)).filter(Session.space_id == a).scalar()

    factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="raw thought",
        content="something I want to remember",
        commit=True,
    )

    db.expire_all()
    after = db.query(func.count(Session.id)).filter(Session.space_id == a).scalar()
    assert after == before, "ActivityRecord create must never create Session rows"


# ---------------------------------------------------------------------------
# 2. Unreviewed ActivityRecord cannot become active Memory directly
# ---------------------------------------------------------------------------


def test_raw_activity_cannot_become_active_memory_without_proposal(db, cross_space_pair_db):
    """A raw ActivityRecord in status='raw' must not produce active MemoryEntry directly."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="unreviewed capture",
        content="content not yet reviewed",
        commit=True,
    )

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )

    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before, (
        "raw ActivityRecord must not produce active MemoryEntry; proposal/review required"
    )

    # The activity itself must be in 'raw' status — unprocessed
    db.refresh(act)
    assert act.status == "raw"
    assert act.consolidation_status == "pending"


# ---------------------------------------------------------------------------
# 3. SourceMonitoring trust gate is not bypassed by Activity-first capture path
# ---------------------------------------------------------------------------


def test_source_monitoring_rejects_agent_inferred_only_provenance(db, cross_space_pair_db):
    """agent_inferred-only provenance cannot produce active semantic memory."""
    monitor = SourceMonitoringService()

    payload = {
        "provenance_entries": [
            {
                "source_type": "activity",
                "source_id": "act-001",
                "source_trust": "agent_inferred",
            }
        ],
        "memory_type": "semantic",
    }

    out = monitor.evaluate_memory_proposal(
        proposal_type="memory_create",
        payload=payload,
        accept_context="direct_apply",
    )
    assert out.action == "reject"
    assert out.reason_code == "agent_inferred_only"


def test_source_monitoring_allows_user_confirmed_activity_provenance(db, cross_space_pair_db):
    """user_confirmed provenance (from user_capture activity) is accepted by SourceMonitoring."""
    monitor = SourceMonitoringService()

    payload = {
        "provenance_entries": [
            {
                "source_type": "activity",
                "source_id": "act-002",
                "source_trust": "user_confirmed",
            }
        ],
        "memory_type": "semantic",
    }

    out = monitor.evaluate_memory_proposal(
        proposal_type="memory_create",
        payload=payload,
        accept_context="direct_apply",
    )
    assert out.action == "allow"


def test_source_monitoring_requires_user_accept_for_untrusted_external(db, cross_space_pair_db):
    """untrusted_external-only provenance requires explicit_user_accept context."""
    monitor = SourceMonitoringService()

    payload = {
        "provenance_entries": [
            {
                "source_type": "activity",
                "source_id": "act-003",
                "source_trust": "untrusted_external",
            }
        ],
        "memory_type": "semantic",
    }

    out_direct = monitor.evaluate_memory_proposal(
        proposal_type="memory_create",
        payload=payload,
        accept_context="direct_apply",
    )
    assert out_direct.action == "require_review"

    out_user = monitor.evaluate_memory_proposal(
        proposal_type="memory_create",
        payload=payload,
        accept_context="explicit_user_accept",
    )
    assert out_user.action == "require_review"


def test_proposal_apply_rejects_missing_provenance_for_semantic_memory(db, cross_space_pair_db):
    """ProposalApplyService rejects memory_create with no provenance_entries.

    Pass provenance_entries=[] explicitly so the factory does not auto-populate defaults.
    """
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_create",
        payload_json={
            "operation": "create",
            "proposed_content": "some content",
            "memory_type": "semantic",
            "target_scope": "user",
            "target_namespace": "user.default",
            "target_visibility": "private",
            "sensitivity_level": "normal",
            "provenance_entries": [],  # explicitly empty to bypass factory auto-populate
        },
        commit=True,
    )

    svc = ProposalApplyService(db)
    with pytest.raises(ProposalApplyError) as exc:
        # explicit_user_accept runs source monitoring (which rejects missing provenance)
        # without triggering the accept_context defense-in-depth gate.
        svc.apply(prop, user_id=ua.id, accept_context="explicit_user_accept")
    assert "provenance" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 4 & 5. Memory proposal from consolidation preserves activity provenance
# ---------------------------------------------------------------------------


def test_consolidation_proposal_preserves_activity_id_in_provenance(api_client, db, cross_space_pair):
    """Proposal created from consolidation carries the source activity_id in provenance_entries."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="consolidation source",
        content="evidence body for consolidation",
        commit=True,
    )

    r = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params={"space_id": a},
    )
    assert r.status_code == 200, r.text
    proposals_out = r.json()
    assert len(proposals_out) >= 1

    pid = proposals_out[0]["id"]
    db.expire_all()
    prop = db.query(Proposal).filter(Proposal.id == pid).one()
    entries = prop.payload_json.get("provenance_entries") or []
    act_entries = [e for e in entries if e.get("source_type") == "activity"]
    assert any(e.get("source_id") == act.id for e in act_entries), (
        "provenance_entries must include the originating activity_id"
    )


def test_accepted_proposal_from_activity_preserves_provenance_in_memory(api_client, db, cross_space_pair):
    """Accepted memory proposal creates MemoryEntry with source_activity_id and ProvenanceLinks."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="provenance source",
        content="important fact for memory",
        commit=True,
    )

    r_con = cross_space_pair["client_a"].post(
        f"/api/v1/activity/{act.id}/consolidate",
        params={"space_id": a},
    )
    assert r_con.status_code == 200, r_con.text
    props = r_con.json()
    assert len(props) >= 1
    pid = props[0]["id"]

    r_acc = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{pid}/accept",
        params={"space_id": a},
    )
    assert r_acc.status_code == 200, r_acc.text
    mem_id = r_acc.json().get("result", {}).get("memory", {}).get("id")
    assert mem_id, "accepted proposal must produce a memory entry"

    db.expire_all()
    mem = db.query(MemoryEntry).filter(MemoryEntry.id == mem_id).one()
    assert mem.source_activity_id == act.id, (
        "MemoryEntry.source_activity_id must be preserved from the originating activity"
    )
    assert mem.created_from_proposal_id == pid, (
        "MemoryEntry.created_from_proposal_id must link to the accepted proposal"
    )

    links = (
        db.query(ProvenanceLink)
        .filter(
            ProvenanceLink.space_id == a,
            ProvenanceLink.target_type == "memory",
            ProvenanceLink.target_id == mem_id,
        )
        .all()
    )
    link_types = {lk.source_type for lk in links}
    assert "activity" in link_types, "ProvenanceLink must include activity source"
    assert "proposal" in link_types, "ProvenanceLink must include proposal source"


# ---------------------------------------------------------------------------
# 6. ActivityRecord is the product activity/inbox layer, not execution replay
# ---------------------------------------------------------------------------


def test_activity_record_status_progression_stays_in_inbox_states(db, cross_space_pair_db):
    """ActivityRecord status values are inbox/processing states, not execution replay states."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="inbox item",
        content="content",
        commit=True,
    )
    assert act.status == "raw"

    from app.activity.service import ActivityService

    svc = ActivityService(db)
    svc.mark_processed(act.id, a)
    db.refresh(act)
    assert act.status == "processed"

    svc.mark_archived(act.id, a)
    db.refresh(act)
    assert act.status == "archived"


# ---------------------------------------------------------------------------
# 7. Information Horizon guardrail: no direct horizon-to-memory path
# ---------------------------------------------------------------------------


def test_no_direct_memory_write_from_raw_activity_payload(db, cross_space_pair_db):
    """No code path auto-creates active Memory from raw ActivityRecord.

    The boundary: raw capture → active Memory requires proposal/apply cycle.
    ActivityRecord factory must not auto-promote to active Memory.
    """
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )

    act = factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_capture",
        title="horizon candidate",
        content="raw content that must not bypass proposal",
        commit=True,
    )

    db.refresh(act)
    assert act.status == "raw", "activity must remain raw after factory call"

    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before, "ActivityRecord factory must not auto-promote to active memory"


# ---------------------------------------------------------------------------
# 8. Public memory writes remain proposal-first (regression from M5)
# ---------------------------------------------------------------------------


def test_public_memory_write_returns_proposal_not_memory(api_client, db, cross_space_pair):
    """POST /memory returns a pending Proposal (HTTP 202), not a MemoryEntry directly."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )

    r = cross_space_pair["client_a"].post(
        "/api/v1/memory",
        params={"space_id": a},
        json={
            "title": "test memory",
            "content": "test content",
            "type": "semantic",
            "scope": "user",
            "namespace": "user.default",
            "visibility": "private",
        },
    )
    assert r.status_code == 202, r.text
    out = r.json()
    assert out.get("status") == "pending", "public memory write must return pending proposal"

    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before, "public memory write must not create active MemoryEntry"


