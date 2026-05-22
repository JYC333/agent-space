"""
Boundary unit tests for PolicyEngine — composed decisions via check() / assert_allowed().

Rule-level behavior is covered by this module and policy-domain code; here we assert
engine-visible outcomes and gaps vs aspirational policy coverage.
"""
import pytest

from app.policy.decisions import Decision, RiskLevel
from app.policy.engine import PolicyEngine
from tests.support import factories


def _engine() -> PolicyEngine:
    return PolicyEngine()


def test_memory_read_same_space_is_allowed_by_default():
    """memory.read is not gated by memory_scope; no deny rule applies."""
    d = _engine().check(
        {
            "action": "memory.read",
            "space_id": "personal",
            "resource_space_id": "personal",
            "agent_status": "active",
        }
    )
    assert d.allowed
    assert d.policy_rule_id == "default_allow"


def test_memory_read_cross_space_is_denied():
    d = _engine().check(
        {
            "action": "memory.read",
            "space_id": "personal",
            "resource_space_id": "work",
            "agent_status": "active",
        }
    )
    assert d.denied
    assert d.policy_rule_id == "space_boundary"
    assert "Cross-space" in d.reason


def test_memory_propose_workspace_scope_requires_approval():
    """Canonical protected scope 'workspace' from rule_memory_scope."""
    d = _engine().check(
        {
            "action": "memory.propose",
            "resource_id": "workspace",
            "space_id": "personal",
            "resource_space_id": "personal",
        }
    )
    assert d.decision == Decision.REQUIRE_APPROVAL
    assert d.policy_rule_id == "memory_scope"
    assert d.risk_level == RiskLevel.MEDIUM


def test_memory_write_user_scope_requires_approval_not_denied():
    d = _engine().check({"action": "memory.write", "resource_id": "user"})
    assert d.requires_approval
    assert not d.denied


def test_tool_execute_with_empty_allowlist_denies_when_tool_named():
    d = _engine().check(
        {
            "action": "tool.execute",
            "tool_name": "any_tool",
            "agent_tool_permissions": [],
            "agent_status": "active",
        }
    )
    assert d.denied
    assert d.policy_rule_id == "tool_permission"


def test_assert_allowed_raises_on_require_approval():
    """assert_allowed treats REQUIRE_APPROVAL as not allowed."""
    with pytest.raises(PermissionError) as exc:
        _engine().assert_allowed({"action": "memory.write", "resource_id": "user"})
    assert "memory_scope" in str(exc.value) or "approval" in str(exc.value).lower()


def test_benign_unknown_action_falls_through_to_allow():
    d = _engine().check(
        {
            "action": "workspace.tree_read",
            "space_id": "personal",
            "resource_space_id": "personal",
        }
    )
    assert d.allowed
    assert d.policy_rule_id == "default_allow"
