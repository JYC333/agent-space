"""Tests for rule_runtime_execute_risk_level and high-risk decision recording.

Part A-4 of Policy RC cleanup:
  - rule reflects context["risk_level"] in runtime.execute decisions
  - high-risk (and critical-risk) decisions are recorded in PolicyDecisionRecord
  - unknown or absent risk_level falls through (returns None)
"""
from __future__ import annotations

import pytest
from app.policy.rules import rule_runtime_execute_risk_level, BUILTIN_RULES
from app.policy.engine import PolicyEngine
from app.policy.decisions import Decision, RiskLevel


class TestRuleRuntimeExecuteRiskLevel:
    """Unit tests for rule_runtime_execute_risk_level."""

    def test_high_risk_level_sets_risk(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
            "risk_level": "high",
        })
        assert d is not None
        assert d.allowed
        assert d.risk_level == RiskLevel.HIGH
        assert d.policy_rule_id == "runtime_execute_risk_level"
        assert d.audit_code == "runtime_execute_risk_level"

    def test_critical_risk_level_sets_risk(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
            "risk_level": "critical",
        })
        assert d is not None
        assert d.allowed
        assert d.risk_level == RiskLevel.CRITICAL

    def test_medium_risk_level_sets_risk(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
            "risk_level": "medium",
        })
        assert d is not None
        assert d.allowed
        assert d.risk_level == RiskLevel.MEDIUM

    def test_low_risk_level_sets_risk(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
            "risk_level": "low",
        })
        assert d is not None
        assert d.allowed
        assert d.risk_level == RiskLevel.LOW

    def test_absent_risk_level_returns_none(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
        })
        assert d is None

    def test_unknown_risk_level_returns_none(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.execute",
            "risk_level": "extreme",
        })
        assert d is None

    def test_non_runtime_execute_action_returns_none(self):
        d = rule_runtime_execute_risk_level({
            "action": "runtime.use_credential",
            "risk_level": "high",
        })
        assert d is None

    def test_rule_is_last_in_builtin_rules(self):
        """risk_level rule must be last so space_boundary / agent_status still fire first."""
        assert BUILTIN_RULES[-1] is rule_runtime_execute_risk_level


class TestEngineRiskLevelPropagation:
    """PolicyEngine integration: risk_level is reflected in the decision."""

    def test_engine_reflects_high_risk_for_runtime_execute(self):
        engine = PolicyEngine()
        decision = engine.check({
            "action": "runtime.execute",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "agent_status": "active",
            "risk_level": "high",
        })
        assert decision.allowed
        assert decision.risk_level == RiskLevel.HIGH

    def test_engine_reflects_critical_risk_for_runtime_execute(self):
        engine = PolicyEngine()
        decision = engine.check({
            "action": "runtime.execute",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "agent_status": "active",
            "risk_level": "critical",
        })
        assert decision.allowed
        assert decision.risk_level == RiskLevel.CRITICAL

    def test_engine_risk_level_not_applied_to_other_actions(self):
        engine = PolicyEngine()
        decision = engine.check({
            "action": "artifact.persist",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "risk_level": "high",
        })
        # artifact.persist default_risk_level=LOW; risk_level from context
        # does not change it (only applies to runtime.execute rule)
        assert decision.risk_level != RiskLevel.HIGH


class TestHighRiskDecisionRecording:
    """PolicyGateway records high-risk and critical-risk runtime.execute decisions."""

    def test_high_risk_runtime_execute_is_recorded(self, db):
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest
        from app.models import PolicyDecisionRecord
        from app.db import SessionLocal

        gw = PolicyGateway(db)
        decision = gw.enforce(PolicyCheckRequest(
            action="runtime.execute",
            actor_type="user",
            actor_id="user_1",
            space_id="space_a",
            resource_type="run",
            resource_id="run_1",
            context={
                "agent_status": "active",
                "risk_level": "high",
            },
        ))

        assert decision.allowed
        assert decision.risk_level == RiskLevel.HIGH

        # audit_required=True for runtime.execute → record is written
        fresh = SessionLocal()
        try:
            record = (
                fresh.query(PolicyDecisionRecord)
                .filter(
                    PolicyDecisionRecord.action == "runtime.execute",
                    PolicyDecisionRecord.resource_id == "run_1",
                )
                .first()
            )
        finally:
            fresh.close()
        assert record is not None
        assert record.risk_level == "high"
        assert record.decision == "allow"

    def test_critical_risk_runtime_execute_is_recorded(self, db):
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest
        from app.models import PolicyDecisionRecord
        from app.db import SessionLocal

        gw = PolicyGateway(db)
        decision = gw.enforce(PolicyCheckRequest(
            action="runtime.execute",
            actor_type="user",
            actor_id="user_1",
            space_id="space_a",
            resource_type="run",
            resource_id="run_2",
            context={
                "agent_status": "active",
                "risk_level": "critical",
            },
        ))

        assert decision.allowed
        assert decision.risk_level == RiskLevel.CRITICAL

        fresh = SessionLocal()
        try:
            record = (
                fresh.query(PolicyDecisionRecord)
                .filter(
                    PolicyDecisionRecord.action == "runtime.execute",
                    PolicyDecisionRecord.resource_id == "run_2",
                )
                .first()
            )
        finally:
            fresh.close()
        assert record is not None
        assert record.risk_level == "critical"
        assert record.decision == "allow"
