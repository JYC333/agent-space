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


def _memory_write_policy_kwargs(effect: str = "deny") -> dict:
    return {
        "domain": "memory",
        "policy_key": "memory.write_direct.guard",
        "enforcement_mode": effect,
        "rule_json": {
            "policy_type": "memory_write",
            "action": "memory.write_direct",
            "resource_type": "memory",
            "effect": effect,
            "reason": "Direct memory writes must use proposal review",
        },
    }


def test_active_persisted_memory_write_direct_policy_returns_decision(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    factories.create_test_policy(db, space_id=a, **_memory_write_policy_kwargs("deny"))

    d = _engine().check(
        {
            "db": db,
            "action": "memory.write_direct",
            "resource_type": "memory",
            "space_id": a,
            "resource_space_id": a,
        }
    )

    assert d.denied
    assert d.policy_source == "persisted"
    assert d.policy_rule_id == "memory.write_direct.guard"
    assert d.space_id == a
    assert d.action == "memory.write_direct"
    assert d.resource_type == "memory"


def test_active_persisted_memory_write_direct_policy_can_require_approval(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    factories.create_test_policy(db, space_id=a, **_memory_write_policy_kwargs("require_approval"))

    d = _engine().check(
        {
            "db": db,
            "action": "memory.write_direct",
            "resource_type": "memory",
            "space_id": a,
            "resource_space_id": a,
        }
    )

    assert d.requires_approval
    assert d.policy_source == "persisted"


def test_inactive_unrelated_and_other_space_policies_are_ignored(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    factories.create_test_policy(
        db,
        space_id=a,
        status="disabled",
        **_memory_write_policy_kwargs("deny"),
    )
    factories.create_test_policy(
        db,
        space_id=a,
        domain="runtime",
        policy_key="runtime.deny",
        enforcement_mode="deny",
        rule_json={
            "policy_type": "runtime_execution",
            "action": "runtime.execute",
            "resource_type": "run",
            "effect": "deny",
        },
    )
    factories.create_test_policy(db, space_id=b, **_memory_write_policy_kwargs("deny"))

    d = _engine().check(
        {
            "db": db,
            "action": "memory.write_direct",
            "resource_type": "memory",
            "space_id": a,
            "resource_space_id": a,
        }
    )

    assert d.allowed
    assert d.policy_source == "default"
    assert d.policy_rule_id == "default_allow"


def test_actor_ref_in_persisted_policy_context_is_preserved(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    actor_ref = {
        "actor_type": "user",
        "actor_id": "actor-1",
        "user_id": "user-1",
        "space_id": a,
    }
    factories.create_test_policy(db, space_id=a, **_memory_write_policy_kwargs("deny"))

    d = _engine().check(
        {
            "db": db,
            "action": "memory.write_direct",
            "resource_type": "memory",
            "space_id": a,
            "resource_space_id": a,
            "actor_id": "actor-1",
            "actor_ref": actor_ref,
        }
    )

    assert d.denied
    assert d.policy_source == "persisted"
    assert d.actor_id == "actor-1"
    assert d.actor_ref == actor_ref
