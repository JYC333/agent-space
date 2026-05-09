"""
Tests for PolicyEngine and all built-in policy rules.
"""
import pytest
from app.policy.engine import PolicyEngine
from app.policy.rules import (
    rule_space_boundary,
    rule_agent_status,
    rule_memory_scope,
    rule_tool_permission,
    rule_delegation_depth,
)
from app.policy.decisions import Decision, RiskLevel


# ---------------------------------------------------------------------------
# rule_space_boundary
# ---------------------------------------------------------------------------

def test_space_boundary_allows_same_space():
    result = rule_space_boundary({"space_id": "personal", "resource_space_id": "personal"})
    assert result is None  # rule does not fire


def test_space_boundary_denies_cross_space():
    result = rule_space_boundary({"space_id": "personal", "resource_space_id": "work"})
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.policy_rule_id == "space_boundary"


def test_space_boundary_skips_when_no_resource_space():
    result = rule_space_boundary({"space_id": "personal"})
    assert result is None


def test_space_boundary_skips_when_no_requesting_space():
    result = rule_space_boundary({"resource_space_id": "personal"})
    assert result is None


# ---------------------------------------------------------------------------
# rule_agent_status
# ---------------------------------------------------------------------------

def test_agent_status_allows_active_agent():
    result = rule_agent_status({"action": "agent.run", "agent_status": "active"})
    assert result is None


def test_agent_status_denies_disabled_agent_run():
    result = rule_agent_status({"action": "agent.run", "agent_status": "disabled"})
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.policy_rule_id == "agent_status"


def test_agent_status_denies_disabled_agent_memory_action():
    result = rule_agent_status({"action": "memory.read", "agent_status": "archived"})
    assert result is not None
    assert result.decision == Decision.DENY


def test_agent_status_denies_disabled_agent_tool_action():
    result = rule_agent_status({"action": "tool.execute", "agent_status": "disabled"})
    assert result is not None
    assert result.decision == Decision.DENY


def test_agent_status_skips_non_agent_action():
    # Other action types not matched by this rule
    result = rule_agent_status({"action": "agent.delegate", "agent_status": "disabled"})
    assert result is None


def test_agent_status_skips_when_no_status():
    result = rule_agent_status({"action": "agent.run"})
    assert result is None


# ---------------------------------------------------------------------------
# rule_memory_scope
# ---------------------------------------------------------------------------

def test_memory_scope_requires_approval_for_user_scope():
    result = rule_memory_scope({"action": "memory.write", "resource_id": "user"})
    assert result is not None
    assert result.decision == Decision.REQUIRE_APPROVAL
    assert result.policy_rule_id == "memory_scope"


def test_memory_scope_requires_approval_for_space_scope():
    result = rule_memory_scope({"action": "memory.propose", "resource_id": "space"})
    assert result is not None
    assert result.decision == Decision.REQUIRE_APPROVAL


def test_memory_scope_requires_approval_for_system_scope():
    result = rule_memory_scope({"action": "memory.write", "resource_id": "system"})
    assert result is not None
    assert result.decision == Decision.REQUIRE_APPROVAL


def test_memory_scope_allows_agent_scope_directly():
    result = rule_memory_scope({"action": "memory.write", "resource_id": "agent"})
    assert result is None  # agent scope allowed without proposal


def test_memory_scope_skips_non_memory_action():
    result = rule_memory_scope({"action": "agent.run", "resource_id": "user"})
    assert result is None


# ---------------------------------------------------------------------------
# rule_tool_permission
# ---------------------------------------------------------------------------

def test_tool_permission_allows_listed_tool():
    result = rule_tool_permission({
        "action": "tool.execute",
        "tool_name": "echo",
        "agent_tool_permissions": ["echo", "claude_code"],
    })
    assert result is None


def test_tool_permission_denies_unlisted_tool():
    result = rule_tool_permission({
        "action": "tool.execute",
        "tool_name": "codex_cli",
        "agent_tool_permissions": ["echo"],
    })
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.policy_rule_id == "tool_permission"


def test_tool_permission_allows_all_when_permissions_none():
    # None means no restriction list set
    result = rule_tool_permission({
        "action": "tool.execute",
        "tool_name": "any_tool",
        "agent_tool_permissions": None,
    })
    assert result is None


def test_tool_permission_skips_non_tool_action():
    result = rule_tool_permission({"action": "agent.run", "tool_name": "echo"})
    assert result is None


# ---------------------------------------------------------------------------
# rule_delegation_depth
# ---------------------------------------------------------------------------

def test_delegation_depth_allows_within_limit():
    result = rule_delegation_depth({
        "action": "agent.delegate",
        "delegation_depth": 1,
        "max_delegation_depth": 3,
        "can_delegate": True,
    })
    assert result is None


def test_delegation_depth_denies_at_limit():
    result = rule_delegation_depth({
        "action": "agent.delegate",
        "delegation_depth": 3,
        "max_delegation_depth": 3,
        "can_delegate": True,
    })
    assert result is not None
    assert result.decision == Decision.DENY
    assert result.policy_rule_id == "delegation_depth"


def test_delegation_depth_denies_when_can_delegate_false():
    result = rule_delegation_depth({
        "action": "agent.delegate",
        "delegation_depth": 0,
        "max_delegation_depth": 3,
        "can_delegate": False,
    })
    assert result is not None
    assert result.decision == Decision.DENY


def test_delegation_depth_skips_non_delegate_action():
    result = rule_delegation_depth({
        "action": "agent.run",
        "delegation_depth": 100,
        "max_delegation_depth": 1,
    })
    assert result is None


# ---------------------------------------------------------------------------
# PolicyEngine — first-match wins, fallthrough to ALLOW
# ---------------------------------------------------------------------------

def test_engine_allows_by_default():
    engine = PolicyEngine()
    decision = engine.check({"action": "unknown.action"})
    assert decision.allowed
    assert decision.policy_rule_id == "default_allow"


def test_engine_returns_first_matching_rule():
    engine = PolicyEngine()
    # Cross-space + disabled agent — space boundary fires first
    decision = engine.check({
        "action": "agent.run",
        "space_id": "personal",
        "resource_space_id": "work",
        "agent_status": "disabled",
    })
    assert decision.policy_rule_id == "space_boundary"


def test_engine_deny_propagates():
    engine = PolicyEngine()
    decision = engine.check({"action": "agent.run", "agent_status": "archived"})
    assert decision.denied


def test_engine_require_approval_is_not_allowed_and_not_denied():
    engine = PolicyEngine()
    decision = engine.check({"action": "memory.write", "resource_id": "user"})
    assert not decision.allowed
    assert not decision.denied
    assert decision.decision == Decision.REQUIRE_APPROVAL


def test_engine_assert_allowed_raises_on_deny():
    engine = PolicyEngine()
    with pytest.raises(PermissionError):
        engine.assert_allowed({"action": "agent.run", "agent_status": "disabled"})


def test_engine_assert_allowed_passes_on_allow():
    engine = PolicyEngine()
    decision = engine.assert_allowed({"action": "some.benign.action"})
    assert decision.allowed


def test_engine_custom_rule_takes_precedence():
    from app.policy.decisions import PolicyDecision

    def always_deny(ctx):
        return PolicyDecision(
            decision=Decision.DENY,
            reason="always deny",
            risk_level=RiskLevel.LOW,
            policy_rule_id="test_always_deny",
        )

    engine = PolicyEngine(extra_rules=[always_deny])
    decision = engine.check({"action": "agent.run", "agent_status": "active"})
    # Built-in rules run first (no match for active agent) → custom rule fires
    assert decision.policy_rule_id == "test_always_deny"
