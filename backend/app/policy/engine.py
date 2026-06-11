from __future__ import annotations
"""
PolicyEngine — stateless policy rule evaluator.

Evaluates built-in rules (BUILTIN_RULES from policy/rules.py) in priority order.
If no rule matches, returns the action registry default_decision — not a permissive
ALLOW. Unknown actions always fail closed with DENY.

PolicyEngine does NOT load persisted Policy rows and does NOT run HardInvariantGuard.
Use PolicyGateway (policy/gateway.py) as the enforcement entry point for actual
sensitive actions — it composes HardInvariantGuard, PolicyEngine, and
PolicyDecisionRecord persistence. PreflightService may call PolicyEngine only
for its non-mutating dry-run simulation.

PolicyContext keys (all optional unless noted):
    action               (str, required)  — e.g. "memory.create", "runtime.execute"
    space_id             (str)            — requesting space
    resource_space_id    (str)            — space of the resource being accessed
    actor_id             (str)            — requesting actor (user or system)
    actor_ref            (dict)           — structured actor reference
    agent_id             (str)            — agent performing the action
    agent_status         (str)            — "active" | "disabled" | ...
    agent_tool_permissions (list[str])    — agent's allowed tools/adapters
    resource_type        (str)            — "memory" | "workspace" | "credential" | ...
    resource_id          (str)            — ID or scope name of the resource
    tool_name            (str)            — for runtime.execute when checking a specific tool/adapter
"""

from typing import Callable, Optional
from .actions import require_action_definition, UnknownPolicyActionError
from .decisions import PolicyDecision, Decision, RiskLevel
from .rules import BUILTIN_RULES

PolicyContext = dict
RuleFunction = Callable[[PolicyContext], Optional[PolicyDecision]]


class PolicyEngine:
    """
    Evaluates policy rules in order. First non-None result wins.
    Falls through to the action registry default_decision when no rule matches.
    """

    def __init__(self, extra_rules: list[RuleFunction] | None = None):
        self._rules: list[RuleFunction] = list(BUILTIN_RULES)
        if extra_rules:
            self._rules.extend(extra_rules)

    def check(self, ctx: PolicyContext) -> PolicyDecision:
        """
        Evaluate all rules against the given context.

        Unknown actions fail closed with DENY (audit_code="unknown_policy_action").
        Known actions with no matching rule use the action's registry default_decision —
        never a permissive ALLOW fallback.
        """
        action = ctx.get("action")
        try:
            defn = require_action_definition(action)
        except (UnknownPolicyActionError, TypeError):
            return PolicyDecision(
                decision=Decision.DENY,
                message=f"Unknown policy action {action!r}. All sensitive actions must be registered in the canonical action registry.",
                risk_level=RiskLevel.HIGH,
                reason_code="unknown_policy_action",
                policy_rule_id="unknown_action_deny",
                policy_source="builtin",
                audit_code="unknown_policy_action",
                action=action,
                space_id=ctx.get("space_id"),
            )

        for rule in self._rules:
            result = rule(ctx)
            if result is not None:
                return result

        return PolicyDecision(
            decision=defn.default_decision,
            message=f"No rule matched; registry default for {action!r} is {defn.default_decision.value}",
            risk_level=defn.default_risk_level,
            reason_code="registry_default",
            required_approver_role=defn.default_required_approver_role,
            approval_capability=defn.approval_capability,
            policy_rule_id="registry_default",
            policy_source="registry",
            resource_type=defn.resource_type,
            action=action,
            actor_id=ctx.get("actor_id"),
            actor_ref=ctx.get("actor_ref") if isinstance(ctx.get("actor_ref"), dict) else None,
            space_id=ctx.get("space_id"),
        )

    def assert_allowed(self, ctx: PolicyContext) -> PolicyDecision:
        """Like check(), but raises PermissionError if the decision is not ALLOW."""
        decision = self.check(ctx)
        if not decision.allowed:
            raise PermissionError(
                f"[{decision.policy_rule_id}] {decision.message} "
                f"(decision={decision.decision}, risk={decision.risk_level})"
            )
        return decision


# Module-level singleton for convenience
default_engine = PolicyEngine()
