"""
Unit tests for the Policy Kernel.

Covers:
  - PolicyEngine registry default semantics (unknown=DENY, known defaults honored)
  - Role normalization and approval authority
  - PolicyDecisionRecord metadata sanitizer
  - HardInvariantGuard invariants
"""

from __future__ import annotations

import pytest

from app.policy.decisions import Decision, RiskLevel, PolicyDecision
from app.policy.engine import PolicyEngine
from app.policy.actions import require_action_definition, list_action_definitions
from app.policy.hard_invariants import HardInvariantGuard
from app.policy.roles import (
    normalize_role,
    role_rank,
    has_role_at_least,
    can_approve_policy_decision,
    can_approve_proposal_type,
    CANONICAL_ROLES,
)
from app.policy.sanitizer import sanitize_policy_metadata


# ---------------------------------------------------------------------------
# PolicyEngine registry default behavior
# ---------------------------------------------------------------------------


class TestPolicyEngineRegistryDefaults:
    def _engine(self):
        return PolicyEngine()

    def test_unknown_action_returns_deny(self):
        d = self._engine().check({"action": "not_a_real_action"})
        assert d.denied
        assert d.audit_code == "unknown_policy_action"
        assert d.risk_level == RiskLevel.HIGH

    def test_known_allow_default_action_allows_when_no_rule_matches(self):
        """context.inject_memory default is ALLOW — should allow when no rule fires."""
        d = self._engine().check({
            "action": "context.inject_memory",
            "space_id": "s1",
            "resource_space_id": "s1",
        })
        assert d.allowed
        assert d.policy_rule_id == "registry_default"

    def test_known_require_approval_default_returns_require_approval(self):
        """proposal.apply default is REQUIRE_APPROVAL — must not silently allow."""
        d = self._engine().check({
            "action": "proposal.apply",
            "space_id": "s1",
            "resource_space_id": "s1",
        })
        assert d.requires_approval
        assert d.policy_rule_id == "registry_default"

    def test_known_deny_rule_denies(self):
        """policy.change is denied by rule for non-admin roles."""
        d = self._engine().check({
            "action": "policy.change",
            "space_id": "s1",
            "membership_role": "member",
        })
        assert d.denied
        assert d.policy_rule_id == "policy_change_insufficient_role"

    def test_builtin_rule_overrides_registry_default(self):
        """space_boundary rule should fire before registry default on cross-space access."""
        d = self._engine().check({
            "action": "context.inject_memory",
            "space_id": "space_a",
            "resource_space_id": "space_b",
        })
        assert d.denied
        assert d.policy_rule_id == "space_boundary"

    def test_registry_default_carries_risk_level(self):
        """Registry default must carry the action's default_risk_level.

        workspace.write_patch without proposal_id falls to registry default REQUIRE_APPROVAL.
        policy.change is intercepted by rule_policy_change and returns DENY for guest.
        """
        d = self._engine().check({
            "action": "workspace.write_patch",
            "space_id": "s1",
            "resource_space_id": "s1",
        })
        assert d.requires_approval
        assert d.risk_level == RiskLevel.HIGH

    def test_policy_change_without_role_denied_by_rule(self):
        """policy.change with no membership_role is intercepted by rule_policy_change and denied."""
        d = self._engine().check({
            "action": "policy.change",
            "space_id": "s1",
            "resource_space_id": "s1",
        })
        assert d.denied
        assert d.risk_level == RiskLevel.HIGH
        assert d.policy_rule_id == "policy_change_insufficient_role"

    def test_registry_default_carries_approver_role(self):
        """Registry default must carry default_required_approver_role."""
        d = self._engine().check({
            "action": "memory.create",
            "space_id": "s1",
            "resource_space_id": "s1",
        })
        assert d.requires_approval
        assert d.required_approver_role is not None

    def test_all_registered_actions_have_defined_defaults(self):
        """Every action in the registry must have a concrete default_decision."""
        engine = self._engine()
        for defn in list_action_definitions():
            d = engine.check({
                "action": defn.action,
                "space_id": "s1",
                "resource_space_id": "s1",
            })
            # Result must match registry default OR a builtin rule that fired
            if d.policy_rule_id == "registry_default":
                assert d.decision == defn.default_decision, (
                    f"Action {defn.action!r}: expected {defn.default_decision} "
                    f"but got {d.decision}"
                )


# ---------------------------------------------------------------------------
# Role normalization and approval authority
# ---------------------------------------------------------------------------


class TestRoleNormalization:
    def test_canonical_roles_normalize_to_themselves(self):
        for role in CANONICAL_ROLES:
            assert normalize_role(role) == role

    def test_unknown_viewer_maps_to_guest(self):
        assert normalize_role("viewer") == "guest"

    def test_unknown_role_maps_to_guest(self):
        assert normalize_role("phd_student") == "guest"
        assert normalize_role("postdoc") == "guest"
        assert normalize_role("lab_member") == "guest"

    def test_empty_maps_to_guest(self):
        assert normalize_role("") == "guest"

    def test_role_rank_order(self):
        assert role_rank("guest") < role_rank("member")
        assert role_rank("member") < role_rank("reviewer")
        assert role_rank("reviewer") < role_rank("admin")
        assert role_rank("admin") < role_rank("owner")

    def test_has_role_at_least(self):
        assert has_role_at_least("owner", "admin") is True
        assert has_role_at_least("admin", "reviewer") is True
        assert has_role_at_least("member", "reviewer") is False
        assert has_role_at_least("guest", "member") is False

    def test_reviewer_approves_medium_not_high(self):
        high_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="test",
            risk_level=RiskLevel.HIGH,
        )
        medium_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="test",
            risk_level=RiskLevel.MEDIUM,
        )
        assert can_approve_policy_decision("reviewer", medium_decision) is True
        assert can_approve_policy_decision("reviewer", high_decision) is False

    def test_admin_approves_high_not_critical(self):
        critical_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="test",
            risk_level=RiskLevel.CRITICAL,
        )
        high_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="test",
            risk_level=RiskLevel.HIGH,
        )
        assert can_approve_policy_decision("admin", high_decision) is True
        assert can_approve_policy_decision("admin", critical_decision) is False

    def test_owner_approves_all(self):
        for rl in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL):
            d = PolicyDecision(decision=Decision.REQUIRE_APPROVAL, message="t", risk_level=rl)
            assert can_approve_policy_decision("owner", d) is True

    def test_member_cannot_approve(self):
        d = PolicyDecision(decision=Decision.REQUIRE_APPROVAL, message="t", risk_level=RiskLevel.LOW)
        assert can_approve_policy_decision("member", d) is False

    def test_policy_change_requires_admin_minimum(self):
        assert can_approve_proposal_type("reviewer", "policy_change", "high") is False
        assert can_approve_proposal_type("admin", "policy_change", "high") is True
        assert can_approve_proposal_type("owner", "policy_change", "high") is True

    def test_policy_change_critical_denied_for_admin(self):
        assert can_approve_proposal_type("admin", "policy_change", "critical") is False

    def test_owner_can_approve_critical_risk(self):
        for proposal_type in ("memory_create", "memory_update", "code_patch", "policy_change"):
            assert can_approve_proposal_type("owner", proposal_type, "critical") is True, (
                f"owner must approve critical risk for {proposal_type}"
            )


# ---------------------------------------------------------------------------
# PolicyDecisionRecord metadata sanitizer
# ---------------------------------------------------------------------------


class TestPolicyMetadataSanitizer:
    def test_none_input_returns_none(self):
        assert sanitize_policy_metadata(None) is None

    def test_safe_metadata_passes_through(self):
        data = {"ops_count": 3, "adapter_type": "echo", "run_id": "abc123"}
        result = sanitize_policy_metadata(data)
        assert result["ops_count"] == 3
        assert result["adapter_type"] == "echo"

    def test_password_key_is_redacted(self):
        data = {"password": "hunter2", "user": "alice"}
        result = sanitize_policy_metadata(data)
        assert result["password"] == "[REDACTED]"
        assert result["user"] == "alice"

    def test_api_key_is_redacted(self):
        result = sanitize_policy_metadata({"api_key": "sk-secret"})
        assert result["api_key"] == "[REDACTED]"

    def test_personal_context_block_is_redacted(self):
        result = sanitize_policy_metadata({"personal_context_block": "private memory text"})
        assert result["personal_context_block"] == "[REDACTED]"

    def test_raw_memory_is_redacted(self):
        result = sanitize_policy_metadata({"raw_memory": "sensitive content"})
        assert result["raw_memory"] == "[REDACTED]"

    def test_stdout_stderr_redacted(self):
        result = sanitize_policy_metadata({"stdout": "output", "stderr": "error"})
        assert result["stdout"] == "[REDACTED]"
        assert result["stderr"] == "[REDACTED]"

    def test_patch_diff_file_content_redacted(self):
        data = {"patch": "--- a/file\n+++ b/file", "diff": "changes", "file_content": "code"}
        result = sanitize_policy_metadata(data)
        for k in ("patch", "diff", "file_content"):
            assert result[k] == "[REDACTED]"

    def test_nested_dangerous_key_is_redacted(self):
        data = {"context": {"api_key": "secret", "safe_field": "ok"}}
        result = sanitize_policy_metadata(data)
        assert result["context"]["api_key"] == "[REDACTED]"
        assert result["context"]["safe_field"] == "ok"

    def test_long_string_truncated(self):
        data = {"info": "x" * 1000}
        result = sanitize_policy_metadata(data)
        assert len(result["info"]) <= 512

    def test_deeply_nested_redacted_at_max_depth(self):
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = sanitize_policy_metadata(data)
        # Should not blow up and should produce something
        assert result is not None
