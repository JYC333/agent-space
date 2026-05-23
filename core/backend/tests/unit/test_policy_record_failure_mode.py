"""Tests for PolicyDecisionRecord record_failure_mode behavior.

When record_failure_mode=FAIL_CLOSED and PolicyDecisionRecord persistence fails,
the gateway must raise PolicyDecisionRecordPersistError rather than silently continuing.
The sensitive action must not proceed.

When record_failure_mode=BEST_EFFORT and persistence fails, the gateway logs a
warning and continues — the action is not blocked.

Escalation rules (Task 1):
  - automation-origin + audit_required → fail_closed regardless of decision value
  - CRITICAL risk + audit_required → fail_closed regardless of decision value
  - automation-origin + non-ALLOW → fail_closed (legacy rule)
  - CRITICAL risk + non-ALLOW → fail_closed (legacy rule)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_that_raises_on_flush(exc: Exception | None = None) -> MagicMock:
    """Return a mock db whose flush() raises the given exception."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock(side_effect=exc or Exception("DB flush failure"))
    return db


def _mock_db_ok() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    return db


# ---------------------------------------------------------------------------
# PolicyDecisionRecordPersistError
# ---------------------------------------------------------------------------


class TestPolicyDecisionRecordPersistError:
    def test_importable(self):
        from app.policy.gateway import PolicyDecisionRecordPersistError
        assert PolicyDecisionRecordPersistError is not None

    def test_has_action_and_actor_id_attributes(self):
        from app.policy.gateway import PolicyDecisionRecordPersistError
        err = PolicyDecisionRecordPersistError(action="runtime.use_credential", actor_id="u1")
        assert err.action == "runtime.use_credential"
        assert err.actor_id == "u1"

    def test_message_contains_audit_code(self):
        from app.policy.gateway import PolicyDecisionRecordPersistError
        err = PolicyDecisionRecordPersistError(action="workspace.write_patch")
        assert "policy_decision_record_persist_failed" in str(err)

    def test_is_exception_subclass(self):
        from app.policy.gateway import PolicyDecisionRecordPersistError
        assert issubclass(PolicyDecisionRecordPersistError, Exception)


# ---------------------------------------------------------------------------
# _persist_record: best_effort vs fail_closed
# ---------------------------------------------------------------------------


class TestPersistRecordFailureMode:
    """_persist_record must raise PolicyDecisionRecordPersistError for fail_closed."""

    def _make_req_and_decision(self, action: str):
        from app.policy.gateway import PolicyCheckRequest
        from app.policy.decisions import Decision, PolicyDecision, RiskLevel
        req = PolicyCheckRequest(
            action=action,
            actor_type="user",
            actor_id="u1",
            space_id="s1",
        )
        decision = PolicyDecision(
            decision=Decision.DENY,
            message="test denial",
            risk_level=RiskLevel.HIGH,
            reason_code="test_deny",
            policy_rule_id="test_rule",
            policy_source="builtin",
            audit_code="test_deny",
        )
        return req, decision

    def test_best_effort_does_not_raise_on_db_failure(self):
        from app.policy.gateway import _persist_record, PolicyDecisionRecordPersistError

        db = _mock_db_that_raises_on_flush()
        req, decision = self._make_req_and_decision("runtime.execute")

        # Should not raise — just log a warning.
        _persist_record(db, req, decision, failure_mode="best_effort")

    def test_fail_closed_raises_on_db_failure(self):
        from app.policy.gateway import _persist_record, PolicyDecisionRecordPersistError

        db = _mock_db_that_raises_on_flush()
        req, decision = self._make_req_and_decision("runtime.use_credential")

        with pytest.raises(PolicyDecisionRecordPersistError) as exc_info:
            _persist_record(db, req, decision, failure_mode="fail_closed")

        assert exc_info.value.action == "runtime.use_credential"

    def test_fail_closed_does_not_raise_when_persist_succeeds(self):
        from app.policy.gateway import _persist_record

        db = _mock_db_ok()
        req, decision = self._make_req_and_decision("runtime.use_credential")

        # Should complete without raising.
        _persist_record(db, req, decision, failure_mode="fail_closed")


# ---------------------------------------------------------------------------
# _resolve_failure_mode: dynamic escalation rules
# ---------------------------------------------------------------------------


class TestResolveFailureMode:
    """_resolve_failure_mode escalation: per-action, automation, critical risk."""

    def _decision(self, decision_val="deny", risk="high"):
        from app.policy.decisions import Decision, PolicyDecision, RiskLevel
        d_map = {"allow": Decision.ALLOW, "deny": Decision.DENY, "require_approval": Decision.REQUIRE_APPROVAL}
        r_map = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM, "high": RiskLevel.HIGH, "critical": RiskLevel.CRITICAL}
        return PolicyDecision(
            decision=d_map[decision_val],
            message="test decision",
            risk_level=r_map[risk],
            reason_code="x",
            policy_rule_id="x",
            policy_source="builtin",
            audit_code="x",
        )

    def _req(self, trigger_origin="manual"):
        from app.policy.gateway import PolicyCheckRequest
        return PolicyCheckRequest(
            action="runtime.execute",
            space_id="s1",
            context={"trigger_origin": trigger_origin} if trigger_origin else {},
        )

    def _defn(self, record_failure_mode="best_effort", audit_required=False):
        from app.policy.actions import RecordFailureMode
        defn = MagicMock()
        defn.record_failure_mode = RecordFailureMode(record_failure_mode)
        defn.audit_required = audit_required
        return defn

    def test_defn_fail_closed_returns_fail_closed(self):
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("fail_closed")
        decision = self._decision("deny", "high")
        req = self._req("manual")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_defn_best_effort_non_allow_manual_high_is_best_effort(self):
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        decision = self._decision("deny", "high")
        req = self._req("manual")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.BEST_EFFORT

    def test_automation_origin_deny_escalates_to_fail_closed(self):
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        decision = self._decision("deny", "medium")
        req = self._req("automation")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_automation_origin_allow_with_audit_required_escalates_to_fail_closed(self):
        """automation + audit_required + ALLOW → fail_closed (new rule)."""
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = True
        decision = self._decision("allow", "medium")
        req = self._req("automation")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_automation_origin_allow_without_audit_required_stays_best_effort(self):
        """automation + non-audit-required + ALLOW → best_effort."""
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = False
        decision = self._decision("allow", "medium")
        req = self._req("automation")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.BEST_EFFORT

    def test_critical_risk_deny_escalates_to_fail_closed(self):
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = False
        decision = self._decision("deny", "critical")
        req = self._req("manual")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_critical_risk_allow_with_audit_required_escalates_to_fail_closed(self):
        """CRITICAL + audit_required + ALLOW → fail_closed (new rule)."""
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = True
        decision = self._decision("allow", "critical")
        req = self._req("manual")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_critical_risk_allow_without_audit_required_stays_best_effort(self):
        """CRITICAL + non-audit-required + ALLOW → best_effort."""
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = False
        decision = self._decision("allow", "critical")
        req = self._req("manual")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.BEST_EFFORT

    def test_require_approval_with_automation_origin_escalates(self):
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode
        defn = self._defn("best_effort")
        defn.audit_required = False
        decision = self._decision("require_approval", "medium")
        req = self._req("automation")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED

    def test_runtime_execute_automation_allow_audit_required_escalates(self):
        """runtime.execute has audit_required=True; automation + ALLOW → fail_closed."""
        from app.policy.gateway import _resolve_failure_mode
        from app.policy.actions import RecordFailureMode, get_action_definition
        defn = get_action_definition("runtime.execute")
        assert defn is not None and defn.audit_required
        decision = self._decision("allow", "medium")
        req = self._req("automation")
        assert _resolve_failure_mode(defn, decision, req) == RecordFailureMode.FAIL_CLOSED


# ---------------------------------------------------------------------------
# PolicyGateway.check_and_record: fail_closed actions raise on DB failure
# ---------------------------------------------------------------------------


class TestGatewayCheckAndRecordFailClosed:
    """When a fail_closed action's record persistence fails, check_and_record must raise."""

    def _gateway_with_failing_db(self):
        from app.policy.gateway import PolicyGateway
        db = _mock_db_that_raises_on_flush()
        return PolicyGateway(db)

    def test_runtime_use_credential_with_db_failure_raises(self):
        from app.policy.gateway import PolicyCheckRequest, PolicyDecisionRecordPersistError

        gateway = self._gateway_with_failing_db()

        # runtime.use_credential is fail_closed and audit_required — will always try to persist.
        with pytest.raises(PolicyDecisionRecordPersistError):
            gateway.check_and_record(PolicyCheckRequest(
                action="runtime.use_credential",
                actor_type="user",
                actor_id="u1",
                space_id="s1",
                context={"trigger_origin": "manual"},
            ))

    def test_workspace_write_patch_with_db_failure_raises(self):
        from app.policy.gateway import PolicyCheckRequest, PolicyDecisionRecordPersistError

        gateway = self._gateway_with_failing_db()

        with pytest.raises(PolicyDecisionRecordPersistError):
            gateway.check_and_record(PolicyCheckRequest(
                action="workspace.write_patch",
                actor_type="user",
                actor_id="u1",
                space_id="s1",
                context={"proposal_apply_allowed": True},
            ))

    def test_best_effort_action_with_db_failure_does_not_raise(self):
        from app.policy.gateway import PolicyCheckRequest

        gateway = self._gateway_with_failing_db()

        # runtime.execute is best_effort — db failure must not block the action.
        decision = gateway.check_and_record(PolicyCheckRequest(
            action="runtime.execute",
            actor_type="user",
            actor_id="u1",
            space_id="s1",
            context={"agent_status": "active", "trigger_origin": "manual"},
        ))
        assert decision is not None


# ---------------------------------------------------------------------------
# PolicyGateway.check_proposal_apply: proposal.apply is always fail_closed
# ---------------------------------------------------------------------------


class TestCheckProposalApplyFailClosed:
    """proposal.apply check_proposal_apply must raise on DB failure."""

    def test_proposal_apply_with_db_failure_raises(self):
        from app.policy.gateway import PolicyGateway, PolicyDecisionRecordPersistError

        db = _mock_db_that_raises_on_flush()
        gateway = PolicyGateway(db)

        proposal = MagicMock()
        proposal.id = "prop-1"
        proposal.proposal_type = "memory_change"
        proposal.space_id = "s1"
        proposal.payload_json = {}
        proposal.risk_level = "medium"

        # DB failure during record persistence must raise rather than silently continue.
        with pytest.raises(PolicyDecisionRecordPersistError):
            gateway.check_proposal_apply(
                user_id="u1",
                space_id="s1",
                proposal=proposal,
            )


# ---------------------------------------------------------------------------
# Task 1: automation+audit_required ALLOW → fail_closed via gateway
# ---------------------------------------------------------------------------


class TestGatewayAutomationAuditRequiredAllow:
    """automation-origin + audit_required + ALLOW decisions must be fail_closed."""

    def test_runtime_execute_automation_allow_db_failure_raises(self):
        """runtime.execute is audit_required=True; automation+ALLOW+db_failure → raises."""
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest, PolicyDecisionRecordPersistError

        db = _mock_db_that_raises_on_flush()
        gateway = PolicyGateway(db)

        with pytest.raises(PolicyDecisionRecordPersistError):
            gateway.check_and_record(PolicyCheckRequest(
                action="runtime.execute",
                actor_type="run",
                actor_id="run-1",
                space_id="s1",
                context={
                    "trigger_origin": "automation",
                    "agent_status": "active",
                },
            ))

    def test_artifact_persist_automation_allow_db_failure_raises(self):
        """artifact.persist is audit_required=True; automation+ALLOW+db_failure → raises."""
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest, PolicyDecisionRecordPersistError

        db = _mock_db_that_raises_on_flush()
        gateway = PolicyGateway(db)

        with pytest.raises(PolicyDecisionRecordPersistError):
            gateway.check_and_record(PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id="run-1",
                space_id="s1",
                context={
                    "trigger_origin": "automation",
                    "target_space_id": "s1",
                    "derived_from_personal_memory_grant": False,
                    "raw_private_memory_included": False,
                },
            ))

    def test_runtime_execute_manual_non_audit_allow_db_failure_does_not_raise(self):
        """manual + non-audit-required action (context.inject_memory) + ALLOW → best_effort."""
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest

        db = _mock_db_that_raises_on_flush()
        gateway = PolicyGateway(db)

        # context.inject_memory: audit_required=False, manual → best_effort
        decision = gateway.check_and_record(PolicyCheckRequest(
            action="context.inject_memory",
            actor_type="run",
            actor_id="run-1",
            space_id="s1",
            resource_space_id="s1",
            context={"trigger_origin": "manual"},
        ))
        assert decision is not None


# ---------------------------------------------------------------------------
# Task 6: Registry typed enum check
# ---------------------------------------------------------------------------


class TestRecordFailureModeTyped:
    """record_failure_mode must be a RecordFailureMode enum, not an arbitrary string."""

    def test_all_action_definitions_use_enum(self):
        from app.policy.actions import RecordFailureMode, list_action_definitions
        for defn in list_action_definitions():
            assert isinstance(defn.record_failure_mode, RecordFailureMode), (
                f"Action {defn.action!r} has record_failure_mode={defn.record_failure_mode!r} "
                f"which is not a RecordFailureMode enum value"
            )

    def test_fail_closed_actions_have_correct_enum(self):
        from app.policy.actions import RecordFailureMode, get_action_definition
        for action in ("runtime.use_credential", "workspace.write_patch", "proposal.apply", "policy.change"):
            defn = get_action_definition(action)
            assert defn is not None
            assert defn.record_failure_mode == RecordFailureMode.FAIL_CLOSED, (
                f"{action} must have record_failure_mode=FAIL_CLOSED"
            )

    def test_best_effort_actions_have_correct_enum(self):
        from app.policy.actions import RecordFailureMode, get_action_definition
        for action in ("runtime.execute", "context.inject_memory", "artifact.persist"):
            defn = get_action_definition(action)
            assert defn is not None
            assert defn.record_failure_mode == RecordFailureMode.BEST_EFFORT, (
                f"{action} must have record_failure_mode=BEST_EFFORT"
            )
