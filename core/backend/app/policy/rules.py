from __future__ import annotations
"""
Built-in policy rules. Each rule is a function that receives a PolicyContext
dict and returns a PolicyDecision | None. Returning None means the rule does
not apply — the next rule is tried. The first non-None result wins.

Built-in rules (in evaluation order):
  1. space_boundary        — deny cross-space access
  2. agent_status          — deny runtime.execute and memory.* for non-active agents
  3. memory_scope          — require_approval for writes to protected memory scopes
  4. tool_permission       — deny adapter/tool not in agent's allowed list
  5. workspace_write_patch — allow workspace file writes only via accepted code_patch proposal
  6. policy_change         — allow policy changes for admin/owner; deny lower roles
"""

from typing import Optional
from .decisions import PolicyDecision, Decision, RiskLevel


PolicyContext = dict  # see PolicyEngine.check() for keys


def rule_space_boundary(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny any action where requesting_space_id != resource_space_id."""
    requesting = ctx.get("space_id")
    resource = ctx.get("resource_space_id")
    if resource and requesting and requesting != resource:
        return PolicyDecision(
            decision=Decision.DENY,
            message=f"Cross-space access denied: requesting={requesting}, resource={resource}",
            risk_level=RiskLevel.CRITICAL,
            reason_code="space_boundary",
            policy_rule_id="space_boundary",
            audit_code="cross_space_access_denied",
        )
    return None


def rule_agent_status(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny runtime.execute and memory.* actions for non-active agents."""
    action = ctx.get("action", "")
    agent_status = ctx.get("agent_status")
    if agent_status and agent_status != "active":
        if action.startswith("memory.") or action == "runtime.execute":
            return PolicyDecision(
                decision=Decision.DENY,
                message=f"Agent is not active (status={agent_status})",
                risk_level=RiskLevel.HIGH,
                reason_code="agent_status",
                policy_rule_id="agent_status",
                audit_code="agent_not_active",
            )
    return None


def rule_memory_scope(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Require approval for writes to protected memory scopes."""
    action = ctx.get("action", "")
    if action not in ("memory.create", "memory.update", "memory.archive"):
        return None
    scope = ctx.get("resource_id", "")  # resource_id = scope name for memory actions
    protected = {"user", "workspace", "space", "system"}
    if scope in protected:
        return PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message=f"Writing to scope '{scope}' requires user approval",
            risk_level=RiskLevel.MEDIUM,
            reason_code="memory_scope_requires_approval",
            required_approver_role="owner",
            policy_rule_id="memory_scope",
            audit_code="memory_scope_requires_approval",
        )
    return None


def rule_use_credential(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Allow same-space manual credential use; deny cross-space or unknown-space credential use.

    automation-origin credential use falls through to registry default (REQUIRE_APPROVAL).
    """
    action = ctx.get("action", "")
    if action != "runtime.use_credential":
        return None

    space_id = ctx.get("space_id")
    resource_space_id = ctx.get("resource_space_id")
    trigger_origin = ctx.get("trigger_origin") or "manual"

    # Cross-space: deny before any secret resolution.
    if resource_space_id and space_id and resource_space_id != space_id:
        return PolicyDecision(
            decision=Decision.DENY,
            message=(
                f"Cross-space credential use denied: run space={space_id!r} "
                f"credential space={resource_space_id!r}"
            ),
            risk_level=RiskLevel.CRITICAL,
            reason_code="credential_cross_space",
            policy_rule_id="credential_cross_space_deny",
            audit_code="credential_cross_space",
        )

    # automation-origin: require approval (fall through to default keeps REQUIRE_APPROVAL,
    # but explicit rule makes audit clearer).
    if trigger_origin == "automation":
        return PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="Automation-origin credential use requires explicit approval.",
            risk_level=RiskLevel.HIGH,
            reason_code="credential_automation_origin",
            required_approver_role="owner",
            policy_rule_id="credential_automation_require_approval",
            audit_code="credential_automation_origin",
        )

    # Same-space manual or user-initiated run: allow with audit.
    if trigger_origin in ("manual", "user", "api") or not trigger_origin:
        return PolicyDecision(
            decision=Decision.ALLOW,
            message="Same-space manual credential use allowed.",
            risk_level=RiskLevel.HIGH,
            reason_code="credential_same_space_manual",
            policy_rule_id="credential_same_space_manual_allow",
            audit_code="credential_same_space_manual",
        )

    # Unknown trigger origin: fall through to registry default (REQUIRE_APPROVAL).
    return None


def rule_tool_permission(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny adapter/tool use if it is not in the agent's allowed tool list."""
    action = ctx.get("action", "")
    if action != "runtime.execute":
        return None
    tool_name = ctx.get("tool_name")
    allowed_tools = ctx.get("agent_tool_permissions")  # list[str] or None
    if tool_name and allowed_tools is not None and tool_name not in allowed_tools:
        return PolicyDecision(
            decision=Decision.DENY,
            message=f"Tool '{tool_name}' is not in agent's tool_permissions_json",
            risk_level=RiskLevel.HIGH,
            reason_code="tool_not_permitted",
            policy_rule_id="tool_permission",
            audit_code="tool_not_permitted",
        )
    return None


def rule_workspace_write_patch(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """ALLOW workspace.write_patch only when all three conditions hold:
      - proposal_id is present (came through proposal path)
      - proposal_type == "code_patch" (only code_patch proposals may write files)
      - proposal_apply_allowed is True (the apply gate confirmed the proposal is accepted)

    Without all three, fall through to the registry default (REQUIRE_APPROVAL).
    """
    action = ctx.get("action", "")
    if action != "workspace.write_patch":
        return None
    if (
        ctx.get("proposal_id")
        and ctx.get("proposal_type") == "code_patch"
        and ctx.get("proposal_apply_allowed") is True
    ):
        return PolicyDecision(
            decision=Decision.ALLOW,
            message="workspace.write_patch via accepted code_patch proposal",
            risk_level=RiskLevel.HIGH,
            reason_code="workspace_write_patch_via_proposal",
            policy_rule_id="workspace_write_patch_via_proposal",
            audit_code="workspace_write_via_proposal",
        )
    return None


def rule_policy_change(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """ALLOW policy.change for admin/owner; DENY for lower roles."""
    action = ctx.get("action", "")
    if action != "policy.change":
        return None
    role = ctx.get("membership_role") or "guest"
    from .roles import has_role_at_least
    if has_role_at_least(role, "admin"):
        return PolicyDecision(
            decision=Decision.ALLOW,
            message=f"policy.change allowed for role={role}",
            risk_level=RiskLevel.HIGH,
            reason_code="policy_change_admin_allow",
            policy_rule_id="policy_change_admin_allow",
            audit_code="policy_change_allowed",
        )
    return PolicyDecision(
        decision=Decision.DENY,
        message=f"policy.change requires admin or owner authority; role={role}",
        risk_level=RiskLevel.HIGH,
        reason_code="policy_change_insufficient_role",
        policy_rule_id="policy_change_insufficient_role",
        audit_code="policy_change_denied",
    )


# Ordered list of built-in rules evaluated by the engine
BUILTIN_RULES = [
    rule_space_boundary,
    rule_agent_status,
    rule_memory_scope,
    rule_use_credential,
    rule_tool_permission,
    rule_workspace_write_patch,
    rule_policy_change,
]
