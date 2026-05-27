"""Unit tests for PolicyGateway.enforce().

B. Unit tests for PolicyGateway.enforce:
  1. ALLOW audit_required action persists audit through durable writer.
  2. DENY raises PolicyGateBlocked.
  3. REQUIRE_APPROVAL raises PolicyGateBlocked.
  4. Unknown action raises PolicyGateBlocked fail-closed denial.
  5. Reserved action raises PolicyGateBlocked fail-closed denial.
  6. FAIL_CLOSED audit persistence failure raises PolicyAuditPersistError.
  7. BEST_EFFORT audit persistence failure logs but does not block an ALLOW decision.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.policy.gateway import PolicyGateway, PolicyCheckRequest
from app.policy.exceptions import PolicyGateBlocked, PolicyAuditPersistError
from app.models import PolicyDecisionRecord
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _make_req(**overrides) -> PolicyCheckRequest:
    defaults = dict(
        action="automation.create",
        actor_type="user",
        actor_id=DEFAULT_USER_ID,
        space_id=PERSONAL_SPACE_ID,
        resource_type="automation",
        context={"membership_role": "owner"},
    )
    # Allow overrides to replace context entirely if provided.
    defaults.update(overrides)
    return PolicyCheckRequest(**defaults)


def _count_records(db, action: str) -> int:
    return db.query(PolicyDecisionRecord).filter(PolicyDecisionRecord.action == action).count()


class TestEnforceAllowAuditRequired:
    """B1. ALLOW audit_required action persists audit through durable writer."""

    def test_allow_creates_durable_record(self, db):
        """automation.create for owner is ALLOW; audit_required=True → durable record written."""
        from app.db import SessionLocal

        # Owner policy allows automation.create
        req = _make_req()
        decision = PolicyGateway(db).enforce(req)
        assert decision.allowed

        # Record committed in independent session → visible from fresh session
        fresh = SessionLocal()
        try:
            records = fresh.query(PolicyDecisionRecord).filter(
                PolicyDecisionRecord.action == "automation.create",
                PolicyDecisionRecord.actor_id == DEFAULT_USER_ID,
                PolicyDecisionRecord.decision == "allow",
            ).all()
            assert len(records) >= 1
        finally:
            fresh.close()

    def test_allow_returns_decision(self, db):
        req = _make_req()
        decision = PolicyGateway(db).enforce(req)
        assert decision is not None
        assert decision.allowed


class TestEnforceDenyRaisesBlocked:
    """B2. DENY raises PolicyGateBlocked."""

    def _make_member_user(self, db, uid: str) -> None:
        from app.models import SpaceMembership, User
        if not db.query(User).filter(User.id == uid).first():
            db.add(User(id=uid, display_name="Member"))
        if not db.query(SpaceMembership).filter(
            SpaceMembership.space_id == PERSONAL_SPACE_ID,
            SpaceMembership.user_id == uid,
        ).first():
            db.add(SpaceMembership(
                id=f"sm_{uid}",
                space_id=PERSONAL_SPACE_ID,
                user_id=uid,
                role="member",
                status="active",
            ))
        db.flush()

    def test_deny_raises_policy_gate_blocked(self, db):
        self._make_member_user(db, "member_enforce_test")
        req = _make_req(actor_id="member_enforce_test", context={"membership_role": "member"})

        with pytest.raises(PolicyGateBlocked) as exc_info:
            PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.decision.denied
        assert exc.action == "automation.create"
        assert exc.error_code == "policy_denied"
        assert exc.http_status_code == 403

    def test_deny_raises_before_any_business_write(self, db):
        """PolicyGateBlocked must be raised without committing anything to db."""
        self._make_member_user(db, "member_enforce_test2")
        req = _make_req(actor_id="member_enforce_test2", context={"membership_role": "member"})

        db_committed = []
        original_commit = db.commit
        db.commit = lambda: db_committed.append(True) or original_commit()

        try:
            with pytest.raises(PolicyGateBlocked):
                PolicyGateway(db).enforce(req)
        finally:
            db.commit = original_commit

        assert db_committed == [], "Business session must not commit on blocking decision"


class TestEnforceRequireApprovalRaisesBlocked:
    """B3. REQUIRE_APPROVAL raises PolicyGateBlocked."""

    def test_require_approval_raises_policy_gate_blocked(self, db):
        """runtime.use_credential requires approval for automation-origin runs."""
        req = PolicyCheckRequest(
            action="runtime.use_credential",
            actor_type="run",
            actor_id="run-123",
            space_id=PERSONAL_SPACE_ID,
            resource_type="credential",
            resource_id="cred-123",
            resource_space_id=PERSONAL_SPACE_ID,
            run_id="run-123",
            context={"trigger_origin": "automation"},
        )

        with pytest.raises(PolicyGateBlocked) as exc_info:
            PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.decision.requires_approval
        assert exc.error_code == "policy_requires_approval"
        assert exc.http_status_code == 403


class TestEnforceUnknownAction:
    """B4. Unknown action raises PolicyGateBlocked (fail-closed denial)."""

    def test_unknown_action_raises_blocked(self, db):
        req = _make_req(action="totally.unknown.action.xyz")

        with pytest.raises(PolicyGateBlocked) as exc_info:
            PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.decision.denied
        assert exc.decision.reason_code == "unknown_policy_action"
        assert exc.error_code == "policy_denied"


class TestEnforceReservedAction:
    """B5. Reserved action raises PolicyGateBlocked (fail-closed denial)."""

    def test_reserved_action_raises_blocked(self, db):
        req = _make_req(action="deployment.propose")

        with pytest.raises(PolicyGateBlocked) as exc_info:
            PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.decision.denied
        assert exc.decision.reason_code == "policy_action_not_implemented"
        assert exc.error_code == "policy_denied"


class TestEnforceViaProposalOnlyAction:
    """WIRED_VIA_PROPOSAL actions must not be enforced directly."""

    def test_policy_change_direct_enforce_denies_via_proposal_only(self, db):
        req = _make_req(
            action="policy.change",
            resource_type="policy",
            context={"membership_role": "owner"},
        )

        with pytest.raises(PolicyGateBlocked) as exc_info:
            PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.decision.denied
        assert exc.decision.reason_code == "policy_action_via_proposal_only"
        assert exc.decision.audit_code == "policy_action_via_proposal_only"


class TestEnforceFailClosedAuditFailure:
    """B6. FAIL_CLOSED audit persistence failure raises PolicyAuditPersistError."""

    def test_fail_closed_audit_failure_raises_persist_error(self, db):
        """automation.create is FAIL_CLOSED; if DurablePolicyAuditWriter fails → PolicyAuditPersistError."""
        req = _make_req()

        with patch("app.policy.audit.DurablePolicyAuditWriter.write", side_effect=Exception("db down")):
            with pytest.raises(PolicyAuditPersistError) as exc_info:
                PolicyGateway(db).enforce(req)

        exc = exc_info.value
        assert exc.action == "automation.create"
        assert exc.audit_code == "policy_decision_record_persist_failed"


class TestEnforceBestEffortAuditFailure:
    """B7. BEST_EFFORT audit persistence failure logs but does not block an ALLOW decision."""

    def test_best_effort_failure_does_not_block_allow(self, db):
        """runtime.execute is BEST_EFFORT; audit write failure → decision still returned."""
        req = PolicyCheckRequest(
            action="runtime.execute",
            actor_type="run",
            actor_id="run-be-test",
            space_id=PERSONAL_SPACE_ID,
            resource_type="run",
            resource_id="run-be-test",
            run_id="run-be-test",
            context={
                "agent_status": "active",
                "trigger_origin": "manual",
                "risk_level": "low",
            },
        )

        with patch("app.policy.audit.DurablePolicyAuditWriter.write", side_effect=Exception("db down")):
            decision = PolicyGateway(db).enforce(req)

        # Decision is returned despite audit failure (BEST_EFFORT)
        assert decision is not None
        assert decision.allowed
