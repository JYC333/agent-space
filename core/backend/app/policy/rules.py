from __future__ import annotations
"""
Built-in policy rules. Each rule is a function that receives a PolicyContext
dict and returns a PolicyDecision | None. Returning None means the rule does
not apply — the next rule is tried. The first non-None result wins.

Built-in rules (in evaluation order):
  1. space_boundary      — deny cross-space access
  2. agent_status        — deny runs for non-active agents
  3. memory_scope        — require_approval for protected scopes
  4. tool_permission     — deny tools not in agent's tool_permissions_json
  5. delegation_depth    — deny delegation past max_delegation_depth
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
            reason=f"Cross-space access denied: requesting={requesting}, resource={resource}",
            risk_level=RiskLevel.CRITICAL,
            policy_rule_id="space_boundary",
        )
    return None


def rule_agent_status(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny tool.execute and memory.* actions for non-active agents."""
    action = ctx.get("action", "")
    agent_status = ctx.get("agent_status")
    if agent_status and agent_status != "active":
        if action.startswith("memory.") or action.startswith("tool.") or action == "agent.run":
            return PolicyDecision(
                decision=Decision.DENY,
                reason=f"Agent is not active (status={agent_status})",
                risk_level=RiskLevel.HIGH,
                policy_rule_id="agent_status",
            )
    return None


def rule_memory_scope(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Require approval for writes to protected memory scopes."""
    action = ctx.get("action", "")
    if action not in ("memory.propose", "memory.write"):
        return None
    scope = ctx.get("resource_id", "")  # resource_id = scope name for memory actions
    protected = {"user", "workspace", "space", "system"}
    if scope in protected:
        return PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            reason=f"Writing to scope '{scope}' requires user approval",
            risk_level=RiskLevel.MEDIUM,
            required_approver_role="owner",
            policy_rule_id="memory_scope",
        )
    return None


def rule_tool_permission(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny tool execution if the tool is not in the agent's allowed tool list."""
    action = ctx.get("action", "")
    if action != "tool.execute":
        return None
    tool_name = ctx.get("tool_name")
    allowed_tools = ctx.get("agent_tool_permissions")  # list[str] or None
    if tool_name and allowed_tools is not None and tool_name not in allowed_tools:
        return PolicyDecision(
            decision=Decision.DENY,
            reason=f"Tool '{tool_name}' is not in agent's tool_permissions_json",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="tool_permission",
        )
    return None


def rule_delegation_depth(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Deny delegation if it would exceed the agent's max_delegation_depth."""
    action = ctx.get("action", "")
    if action != "agent.delegate":
        return None
    current_depth = ctx.get("delegation_depth", 0)
    max_depth = ctx.get("max_delegation_depth", 3)
    can_delegate = ctx.get("can_delegate", True)
    if not can_delegate:
        return PolicyDecision(
            decision=Decision.DENY,
            reason="Agent does not have delegation permission (can_delegate=false)",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="delegation_depth",
        )
    if current_depth >= max_depth:
        return PolicyDecision(
            decision=Decision.DENY,
            reason=f"Delegation depth limit reached ({current_depth} >= {max_depth})",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="delegation_depth",
        )
    return None


# Ordered list of built-in rules evaluated by the engine
BUILTIN_RULES = [
    rule_space_boundary,
    rule_agent_status,
    rule_memory_scope,
    rule_tool_permission,
    rule_delegation_depth,
]
