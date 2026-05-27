"""Policy enforcement invariants for proposal.create."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.main import policy_gate_blocked_handler
from app.memory.proposals import ProposalService
from app.models import PolicyDecisionRecord, Proposal
from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.exceptions import PolicyGateBlocked
from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
from tests.support import factories


def _blocked_exc(
    *,
    actor_type: str,
    actor_id: str,
    space_id: str = "proposal-policy-space",
    run_id: str | None = None,
    proposal_type: str | None = None,
) -> PolicyGateBlocked:
    decision = PolicyDecision(
        decision=Decision.DENY,
        message="test proposal create block",
        risk_level=RiskLevel.HIGH,
        reason_code="test_proposal_create_deny",
        policy_rule_id="test_rule",
        policy_source="test",
        audit_code="test_proposal_create_deny",
    )
    return PolicyGateBlocked(
        decision=decision,
        action="proposal.create",
        actor_type=actor_type,
        actor_id=actor_id,
        actor_ref=None,
        space_id=space_id,
        resource_type="proposal",
        resource_id=None,
        run_id=run_id,
        proposal_id=None,
        metadata_json={"proposal_type": proposal_type or ("memory_create" if actor_type == "user" else "code_patch")},
        http_status_code=403,
    )


def _fresh_count(**filters: str | None) -> int:
    from app.db import SessionLocal

    fresh = SessionLocal()
    try:
        query = fresh.query(PolicyDecisionRecord)
        for field, value in filters.items():
            if value is not None:
                query = query.filter(getattr(PolicyDecisionRecord, field) == value)
        return query.count()
    finally:
        fresh.close()


def _make_user_context(db, *, space_id: str = "proposal-policy-space"):
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    return user


def _create_memory_proposal(db, *, space_id: str, user_id: str):
    return ProposalService(db).create_proposal(
        space_id=space_id,
        user_id=user_id,
        target_scope="space",
        target_namespace="notes",
        memory_type="semantic",
        proposed_title="Policy test",
        proposed_content="content stays out of policy metadata",
        rationale="rationale stays out of policy metadata",
    )


def _make_run_context(db, *, space_id: str = "proposal-policy-space"):
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.workspace_id = ws.id
    db.commit()
    return run


def test_user_memory_proposal_create_allow_creates_row_without_duplicate_audit(db):
    user = _make_user_context(db)
    before = _fresh_count(action="proposal.create", actor_id=user.id)

    proposal = _create_memory_proposal(db, space_id="proposal-policy-space", user_id=user.id)

    assert proposal.id is not None
    assert db.query(Proposal).filter(Proposal.id == proposal.id).count() == 1
    after = _fresh_count(action="proposal.create", actor_id=user.id)
    assert after - before <= 1


def test_public_memory_create_policy_deny_returns_403_and_no_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before_rows = db.query(Proposal).count()
    blocked = _blocked_exc(actor_type="user", actor_id=ua.id, space_id=a, proposal_type="memory_create")

    with patch("app.memory.proposals.PolicyGateway") as gateway:
        gateway.return_value.enforce.side_effect = blocked
        resp = cross_space_pair["client_a"].post(
            "/api/v1/memory",
            params={"space_id": a},
            json={
                "title": "policy blocked",
                "content": "RAW_MEMORY_SECRET",
                "type": "semantic",
                "scope": "user",
                "namespace": "user.default",
            },
        )

    assert resp.status_code == 403
    assert resp.json()["error"] == "policy_denied"
    assert "RAW_MEMORY_SECRET" not in resp.text
    assert db.query(Proposal).count() == before_rows


def test_public_memory_update_policy_deny_returns_403_and_no_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        scope_type="user",
        scope_id=ua.id,
        owner_user_id=ua.id,
        subject_user_id=ua.id,
        content="existing content",
        commit=True,
    )
    before_rows = db.query(Proposal).count()
    blocked = _blocked_exc(actor_type="user", actor_id=ua.id, space_id=a, proposal_type="memory_update")

    with patch("app.memory.proposals.PolicyGateway") as gateway:
        gateway.return_value.enforce.side_effect = blocked
        resp = cross_space_pair["client_a"].patch(
            f"/api/v1/memory/{mem.id}",
            params={"space_id": a},
            json={"content": "UPDATED_RAW_MEMORY_SECRET"},
        )

    assert resp.status_code == 403
    assert resp.json()["error"] == "policy_denied"
    assert "UPDATED_RAW_MEMORY_SECRET" not in resp.text
    assert db.query(Proposal).count() == before_rows


def test_public_memory_delete_policy_deny_returns_403_and_no_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem = factories.create_test_memory_entry(
        db,
        space_id=a,
        scope_type="user",
        scope_id=ua.id,
        owner_user_id=ua.id,
        subject_user_id=ua.id,
        content="DELETE_RAW_MEMORY_SECRET",
        commit=True,
    )
    before_rows = db.query(Proposal).count()
    blocked = _blocked_exc(actor_type="user", actor_id=ua.id, space_id=a, proposal_type="memory_archive")

    with patch("app.memory.proposals.PolicyGateway") as gateway:
        gateway.return_value.enforce.side_effect = blocked
        resp = cross_space_pair["client_a"].delete(
            f"/api/v1/memory/{mem.id}",
            params={"space_id": a},
        )

    assert resp.status_code == 403
    assert resp.json()["error"] == "policy_denied"
    assert "DELETE_RAW_MEMORY_SECRET" not in resp.text
    assert db.query(Proposal).count() == before_rows


def test_policy_gate_blocked_handler_persists_proposal_create_denial(db):
    """Handler-level coverage for proposal.create DENY durable audit.

    TODO: Replace with a full HTTP contract when TestClient lifespan startup is stable.
    """
    user = _make_user_context(db)
    space_id = "proposal-policy-space"
    before_records = _fresh_count(action="proposal.create", decision="deny", actor_id=user.id)
    before_rows = db.query(Proposal).count()
    blocked = _blocked_exc(actor_type="user", actor_id=user.id, space_id=space_id)

    with patch("app.memory.proposals.PolicyGateway") as gateway:
        gateway.return_value.enforce.side_effect = blocked
        with pytest.raises(PolicyGateBlocked) as exc_info:
            _create_memory_proposal(db, space_id=space_id, user_id=user.id)

    request = SimpleNamespace(state=SimpleNamespace(db=db))
    response = asyncio.run(policy_gate_blocked_handler(request, exc_info.value))
    assert response.status_code == 403
    body = json.loads(response.body)
    assert body["error"] == "policy_denied"
    assert body["reason_code"] == "test_proposal_create_deny"
    assert body["audit_code"] == "test_proposal_create_deny"
    assert body["action"] == "proposal.create"
    assert body["policy_decision_record_id"]

    assert _fresh_count(action="proposal.create", decision="deny", actor_id=user.id) == before_records + 1
    assert db.query(Proposal).count() == before_rows


def test_code_patch_proposal_create_force_record_allow_creates_one_durable_audit(db, tmp_path):
    run = _make_run_context(db)
    before = _fresh_count(action="proposal.create", decision="allow", run_id=run.id)
    ops = [{"op": "replace_file", "path": "a.txt", "content": "new"}]

    with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, [])):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=Path(tmp_path))

    assert result.proposal_created is True
    assert _fresh_count(action="proposal.create", decision="allow", run_id=run.id) == before + 1


def test_code_patch_proposal_create_deny_writes_durable_audit_and_no_row(db, tmp_path):
    run = _make_run_context(db)
    before_records = _fresh_count(action="proposal.create", decision="deny", run_id=run.id)
    before_rows = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count()
    ops = [{"op": "replace_file", "path": "a.txt", "content": "new"}]
    blocked = _blocked_exc(actor_type="run", actor_id=run.id, run_id=run.id)

    with (
        patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, [])),
        patch("app.runs.code_patch_collector.PolicyGateway") as gateway,
    ):
        gateway.return_value.enforce.side_effect = blocked
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=Path(tmp_path))

    assert result.proposal_created is False
    assert "code_patch proposal.create denied by policy" in (result.no_op_reason or "")
    assert _fresh_count(action="proposal.create", decision="deny", run_id=run.id) == before_records + 1
    assert db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count() == before_rows


def test_code_patch_proposal_create_audit_failure_blocks_proposal_creation(db, tmp_path):
    run = _make_run_context(db)
    before_rows = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count()
    ops = [{"op": "replace_file", "path": "a.txt", "content": "new"}]

    with (
        patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, [])),
        patch("app.policy.audit.DurablePolicyAuditWriter.write", side_effect=RuntimeError("audit down")),
    ):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=Path(tmp_path))

    assert result.proposal_created is False
    assert result.no_op_reason == (
        "policy_decision_record_persist_failed: policy audit record persistence "
        "failed for proposal.create. No proposal created."
    )
    assert db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count() == before_rows
