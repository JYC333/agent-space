"""Contracts: deterministic source monitoring gates proposal application."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from ulid import ULID

from app.memory.apply_service import ProposalApplyError, ProposalApplyService
from app.memory.proposals import ProposalService
from app.models import Proposal, ProvenanceLink
from tests.support import factories


def test_semantic_memory_create_without_provenance_rejects(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    now = datetime.now(UTC)
    prop = Proposal(
        id=str(ULID()),
        space_id=a,
        proposal_type="memory_create",
        status="pending",
        title="t",
        summary=None,
        payload_json={
            "operation": "create",
            "proposed_content": "x",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns",
            "target_visibility": "private",
            "sensitivity_level": "normal",
        },
        rationale="r",
        created_by_user_id=ua.id,
        risk_level="low",
        urgency="normal",
        review_deadline=now + timedelta(hours=48),
        expires_at=now + timedelta(days=14),
    )
    db.add(prop)
    db.commit()

    with pytest.raises(HTTPException) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.status_code == 422


def test_policy_change_without_trusted_provenance_rejects(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="p",
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "rule_json": {"effect": "allow_with_log"},
            "provenance_entries": [
                {
                    "source_type": "external_source",
                    "source_id": "00000000-0000-0000-0000-000000000099",
                    "source_trust": "agent_inferred",
                }
            ],
        },
        commit=True,
    )
    with pytest.raises(HTTPException):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)


def test_agent_inferred_only_semantic_rejects(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "proposed_content": "x",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns",
            "target_visibility": "private",
            "sensitivity_level": "normal",
            "provenance_entries": [
                {
                    "source_type": "external_source",
                    "source_id": "00000000-0000-0000-0000-000000000001",
                    "source_trust": "agent_inferred",
                }
            ],
        },
        commit=True,
    )
    with pytest.raises(HTTPException):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)


def test_untrusted_external_only_requires_explicit_accept(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "proposed_content": "x",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
            "provenance_entries": [
                {
                    "source_type": "external_source",
                    "source_id": "00000000-0000-0000-0000-000000000002",
                    "source_trust": "untrusted_external",
                    "evidence_json": {"url": "https://example.invalid/x"},
                }
            ],
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None
    db.refresh(prop)
    sm = (prop.payload_json or {}).get("source_monitoring_result") or {}
    assert sm.get("action") == "require_review"


def test_direct_apply_rejects_untrusted_without_explicit_context(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "proposed_content": "x",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns",
            "target_visibility": "private",
            "sensitivity_level": "normal",
            "provenance_entries": [
                {
                    "source_type": "external_source",
                    "source_id": "00000000-0000-0000-0000-000000000003",
                    "source_trust": "untrusted_external",
                }
            ],
        },
        commit=True,
    )
    with pytest.raises(ProposalApplyError):
        ProposalApplyService(db).apply(prop, user_id=ua.id, accept_context="direct_apply")


def test_internal_seed_bypasses_monitoring(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    now = datetime.now(UTC)
    prop = Proposal(
        id=str(ULID()),
        space_id=a,
        proposal_type="policy_change",
        status="pending",
        title="seed",
        summary=None,
        payload_json={
            "operation": "create",
            "domain": "memory.private_placement",
            "rule_json": {"effect": "allow_with_log"},
        },
        rationale="seed",
        created_by_user_id=ua.id,
        risk_level="low",
        urgency="normal",
        review_deadline=now + timedelta(hours=48),
        expires_at=now + timedelta(days=14),
    )
    db.add(prop)
    db.commit()
    res = ProposalApplyService(db).apply(prop, user_id=ua.id, accept_context="internal_seed")
    assert res.policy is not None


def test_trusted_external_preserves_identity_on_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        payload_json={
            "operation": "create",
            "proposed_content": "ext fact",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "ns",
            "target_visibility": "space_shared",
            "sensitivity_level": "normal",
            "provenance_entries": [
                {
                    "source_type": "external_source",
                    "source_id": "00000000-0000-0000-0000-000000000004",
                    "source_trust": "trusted_external",
                    "evidence_json": {"publisher": "ExampleOrg"},
                }
            ],
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out.memory is not None
    db.expire_all()
    row = (
        db.query(ProvenanceLink)
        .filter(
            ProvenanceLink.target_id == out.memory.id,
            ProvenanceLink.source_trust == "trusted_external",
        )
        .first()
    )
    assert row is not None
    assert row.source_trust == "trusted_external"
