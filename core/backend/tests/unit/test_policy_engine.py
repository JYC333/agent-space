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


def test_context_inject_memory_same_space_is_allowed_by_default():
    """context.inject_memory registry default is ALLOW; rule_id is registry_default when no rule matches."""
    d = _engine().check(
        {
            "action": "context.inject_memory",
            "space_id": "personal",
            "resource_space_id": "personal",
            "agent_status": "active",
        }
    )
    assert d.allowed
    assert d.policy_rule_id == "registry_default"


def test_context_inject_memory_cross_space_is_denied():
    d = _engine().check(
        {
            "action": "context.inject_memory",
            "space_id": "personal",
            "resource_space_id": "work",
            "agent_status": "active",
        }
    )
    assert d.denied
    assert d.policy_rule_id == "space_boundary"
    assert "Cross-space" in d.message


def test_memory_create_workspace_scope_requires_approval():
    """Canonical protected scope 'workspace' from rule_memory_scope."""
    d = _engine().check(
        {
            "action": "memory.create",
            "resource_id": "workspace",
            "space_id": "personal",
            "resource_space_id": "personal",
        }
    )
    assert d.decision == Decision.REQUIRE_APPROVAL
    assert d.policy_rule_id == "memory_scope"
    assert d.risk_level == RiskLevel.MEDIUM


def test_memory_update_user_scope_requires_approval_not_denied():
    d = _engine().check({"action": "memory.update", "resource_id": "user"})
    assert d.requires_approval
    assert not d.denied


def test_runtime_execute_with_empty_allowlist_denies_when_tool_named():
    d = _engine().check(
        {
            "action": "runtime.execute",
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
        _engine().assert_allowed({"action": "memory.create", "resource_id": "user"})
    assert "memory_scope" in str(exc.value) or "approval" in str(exc.value).lower()


def test_unknown_action_is_denied_not_allowed():
    """Unregistered actions must not silently fall through as allow."""
    d = _engine().check(
        {
            "action": "workspace.tree_read",
            "space_id": "personal",
            "resource_space_id": "personal",
        }
    )
    assert d.denied
    assert d.audit_code == "unknown_policy_action"
    assert d.policy_rule_id == "unknown_action_deny"


def test_agent_delegate_is_denied_by_engine():
    """agent.delegate is not registered; engine must deny it."""
    d = _engine().check({"action": "agent.delegate"})
    assert d.denied
    assert d.audit_code == "unknown_policy_action"


def test_none_action_is_denied():
    """None action must also be denied, not fall through."""
    d = _engine().check({"action": None})
    assert d.denied
    assert d.audit_code == "unknown_policy_action"


def test_known_action_falls_through_to_registry_default_when_no_rule_matches():
    """Registered ALLOW-default actions with no matching rule return registry_default."""
    d = _engine().check(
        {
            "action": "context.inject_memory",
            "space_id": "personal",
            "resource_space_id": "personal",
        }
    )
    assert d.allowed
    assert d.policy_rule_id == "registry_default"


# ---------------------------------------------------------------------------
# rule_workspace_write_patch
# ---------------------------------------------------------------------------


def test_workspace_write_patch_accepted_code_patch_context_allows():
    """workspace.write_patch ALLOW requires proposal_id + proposal_type=code_patch + proposal_apply_allowed."""
    d = _engine().check({
        "action": "workspace.write_patch",
        "space_id": "personal",
        "proposal_id": "prop-123",
        "proposal_type": "code_patch",
        "proposal_apply_allowed": True,
    })
    assert d.allowed
    assert d.policy_rule_id == "workspace_write_patch_via_proposal"


def test_workspace_write_patch_proposal_id_alone_not_sufficient():
    """proposal_id alone without proposal_type/proposal_apply_allowed falls to registry default."""
    d = _engine().check({
        "action": "workspace.write_patch",
        "space_id": "personal",
        "proposal_id": "prop-123",
    })
    assert d.requires_approval
    assert d.policy_rule_id == "registry_default"


def test_workspace_write_patch_wrong_proposal_type_not_sufficient():
    """proposal_type != code_patch falls to registry default even with proposal_id."""
    d = _engine().check({
        "action": "workspace.write_patch",
        "space_id": "personal",
        "proposal_id": "prop-123",
        "proposal_type": "memory_create",
        "proposal_apply_allowed": True,
    })
    assert d.requires_approval
    assert d.policy_rule_id == "registry_default"


def test_workspace_write_patch_without_proposal_id_requires_approval():
    """workspace.write_patch without any context falls to registry default REQUIRE_APPROVAL."""
    d = _engine().check({
        "action": "workspace.write_patch",
        "space_id": "personal",
    })
    assert d.requires_approval
    assert d.policy_rule_id == "registry_default"


# ---------------------------------------------------------------------------
# rule_policy_change
# ---------------------------------------------------------------------------


def test_policy_change_admin_role_allows():
    d = _engine().check({
        "action": "policy.change",
        "space_id": "personal",
        "membership_role": "admin",
    })
    assert d.allowed
    assert d.policy_rule_id == "policy_change_admin_allow"


def test_policy_change_owner_role_allows():
    d = _engine().check({
        "action": "policy.change",
        "space_id": "personal",
        "membership_role": "owner",
    })
    assert d.allowed
    assert d.policy_rule_id == "policy_change_admin_allow"


def test_policy_change_member_role_denies():
    d = _engine().check({
        "action": "policy.change",
        "space_id": "personal",
        "membership_role": "member",
    })
    assert d.denied
    assert d.policy_rule_id == "policy_change_insufficient_role"


def test_policy_change_guest_role_denies():
    d = _engine().check({
        "action": "policy.change",
        "space_id": "personal",
        "membership_role": "guest",
    })
    assert d.denied


def test_policy_change_no_role_denies():
    """No membership_role means guest; should deny."""
    d = _engine().check({
        "action": "policy.change",
        "space_id": "personal",
    })
    assert d.denied
