from __future__ import annotations
"""
PolicyEngine — central permission decision point.

All permission checks in the system should go through PolicyEngine.check().
Do not scatter permission logic across API routes or service methods.

Usage:
    engine = PolicyEngine()
    decision = engine.check({
        "action": "memory.propose",
        "space_id": "personal",
        "user_id": "default_user",
        "resource_id": "user",        # scope name for memory actions
    })
    if decision.denied:
        raise HTTPException(status_code=403, detail=decision.reason)

PolicyContext keys (all optional unless noted):
    action               (str, required)  — e.g. "memory.read", "tool.execute", "agent.delegate"
    space_id             (str)            — requesting space
    resource_space_id    (str)            — space of the resource being accessed
    user_id              (str)            — requesting user
    agent_id             (str)            — agent performing the action
    agent_status         (str)            — "active" | "disabled" | ...
    agent_tool_permissions (list[str])    — agent's allowed tools
    resource_type        (str)            — "memory" | "workspace" | "credential" | ...
    resource_id          (str)            — ID or scope name of the resource
    tool_name            (str)            — for tool.execute actions
    delegation_depth     (int)            — current depth
    max_delegation_depth (int)            — from agent's runtime_policy
    can_delegate         (bool)           — from agent's runtime_policy
"""

from typing import Callable, Optional
from .decisions import PolicyDecision, Decision, RiskLevel
from .rules import BUILTIN_RULES

PolicyContext = dict
RuleFunction = Callable[[PolicyContext], Optional[PolicyDecision]]

_DEFAULT_ALLOW = PolicyDecision(
    decision=Decision.ALLOW,
    reason="No rule denied this action",
    risk_level=RiskLevel.LOW,
    policy_rule_id="default_allow",
)


class PolicyEngine:
    """
    Evaluates policy rules in order. First non-None result wins.
    Falls through to ALLOW if no rule matches.
    """

    def __init__(self, extra_rules: list[RuleFunction] | None = None):
        self._rules: list[RuleFunction] = list(BUILTIN_RULES)
        if extra_rules:
            self._rules.extend(extra_rules)

    def check(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Evaluate all rules against the given context.
        Returns the first matching PolicyDecision, or ALLOW if none match.
        """
        for rule in self._rules:
            result = rule(ctx)
            if result is not None:
                return result
        return _DEFAULT_ALLOW

    def assert_allowed(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Like check(), but raises ValueError if the decision is not ALLOW.
        Use this at enforcement points where you want an exception on deny.
        """
        decision = self.check(ctx)
        if not decision.allowed:
            raise PermissionError(
                f"[{decision.policy_rule_id}] {decision.reason} "
                f"(decision={decision.decision}, risk={decision.risk_level})"
            )
        return decision


# Module-level singleton for convenience
default_engine = PolicyEngine()
