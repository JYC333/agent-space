"""Unit tests for built-in policy rules (app/policy/rules.py).

Covers current built-in policy rules:
  - rule_use_credential: same-space manual allow, cross-space deny, automation require_approval
"""
from __future__ import annotations

import pytest
from app.policy.rules import (
    rule_use_credential,
    rule_space_boundary,
    rule_agent_status,
    rule_tool_permission,
    rule_workspace_write_patch,
    BUILTIN_RULES,
)
from app.policy.engine import PolicyEngine
from app.policy.decisions import Decision, RiskLevel


class TestRuleUseCredential:
    """rule_use_credential enforces credential space and trigger-origin policy."""

    def test_same_space_manual_run_is_allowed(self):
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "trigger_origin": "manual",
        })
        assert d is not None
        assert d.allowed
        assert d.policy_rule_id == "credential_same_space_manual_allow"

    def test_same_space_api_run_is_allowed(self):
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "trigger_origin": "api",
        })
        assert d is not None
        assert d.allowed

    def test_same_space_no_trigger_origin_is_allowed(self):
        """Absent trigger_origin defaults to manual allow."""
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_a",
        })
        assert d is not None
        assert d.allowed

    def test_cross_space_credential_is_denied(self):
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_b",
            "trigger_origin": "manual",
        })
        assert d is not None
        assert d.denied
        assert d.risk_level == RiskLevel.CRITICAL
        assert d.policy_rule_id == "credential_cross_space_deny"
        assert d.audit_code == "credential_cross_space"

    def test_automation_origin_requires_approval(self):
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "trigger_origin": "automation",
        })
        assert d is not None
        assert d.requires_approval
        assert d.policy_rule_id == "credential_automation_require_approval"
        assert d.audit_code == "credential_automation_origin"

    def test_non_credential_action_returns_none(self):
        """Rule only applies to runtime.use_credential."""
        assert rule_use_credential({"action": "runtime.execute", "space_id": "s1"}) is None
        assert rule_use_credential({"action": "memory.create", "space_id": "s1"}) is None

    def test_unknown_trigger_origin_falls_through(self):
        """Unknown trigger_origin falls through to registry default (returns None)."""
        d = rule_use_credential({
            "action": "runtime.use_credential",
            "space_id": "space_a",
            "resource_space_id": "space_a",
            "trigger_origin": "webhook_unknown_origin",
        })
        assert d is None


class TestBuiltinRuleOrder:
    """BUILTIN_RULES contains rule_use_credential in correct position."""

    def test_rule_use_credential_in_builtin_rules(self):
        rule_names = [r.__name__ for r in BUILTIN_RULES]
        assert "rule_use_credential" in rule_names

    def test_space_boundary_before_use_credential(self):
        """Space boundary fires before credential rule."""
        names = [r.__name__ for r in BUILTIN_RULES]
        assert names.index("rule_space_boundary") < names.index("rule_use_credential")

    def test_use_credential_before_tool_permission(self):
        """Credential rule fires before tool permission rule."""
        names = [r.__name__ for r in BUILTIN_RULES]
        assert names.index("rule_use_credential") < names.index("rule_tool_permission")


class TestEngineUnknownActionDenies:
    """Engine denies unknown (unregistered) actions with audit_code='unknown_policy_action'."""

    def _engine(self):
        return PolicyEngine()

    def test_unknown_action_is_denied(self):
        d = self._engine().check({"action": "future.unknown_action", "space_id": "s1"})
        assert d.denied
        assert d.audit_code == "unknown_policy_action"
        assert d.policy_rule_id == "unknown_action_deny"

    def test_empty_action_is_denied(self):
        d = self._engine().check({"action": ""})
        assert d.denied

    def test_missing_action_key_is_denied(self):
        d = self._engine().check({})
        assert d.denied
