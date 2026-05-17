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

from typing import Any, Callable, Optional
from .access import load_active_policies_for_write_direct
from .decisions import PolicyDecision, Decision, RiskLevel
from .domains import MEMORY_WRITE_DIRECT
from .rules import BUILTIN_RULES

PolicyContext = dict
RuleFunction = Callable[[PolicyContext], Optional[PolicyDecision]]

_WRITE_DIRECT_RESOURCE_TYPE = "memory"

_DEFAULT_ALLOW = PolicyDecision(
    decision=Decision.ALLOW,
    reason="No rule denied this action",
    risk_level=RiskLevel.LOW,
    policy_rule_id="default_allow",
    policy_source="default",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_effect(value: Any) -> Decision | None:
    raw = str(value or "").strip().lower()
    if raw == Decision.DENY.value:
        return Decision.DENY
    if raw == Decision.REQUIRE_APPROVAL.value:
        return Decision.REQUIRE_APPROVAL
    if raw == Decision.ALLOW.value:
        return Decision.ALLOW
    return None


def _normalize_risk(value: Any) -> RiskLevel:
    raw = str(value or "").strip().lower()
    for risk in RiskLevel:
        if raw == risk.value:
            return risk
    return RiskLevel.MEDIUM


def load_persisted_policies_for_action(
    db: Any,
    *,
    space_id: str,
    action: str,
    resource_type: str,
) -> list[Any]:
    """Load active persisted policies for ``memory.write_direct`` via canonical loader."""
    return load_active_policies_for_write_direct(
        db, space_id=space_id, action=action, resource_type=resource_type
    )


def persisted_policy_decision(ctx: PolicyContext) -> Optional[PolicyDecision]:
    """Evaluate the deliberately narrow M5 persisted policy class."""
    action = ctx.get("action")
    resource_type = ctx.get("resource_type")
    space_id = ctx.get("space_id")
    if not isinstance(action, str) or not isinstance(resource_type, str) or not isinstance(space_id, str):
        return None

    for row in load_persisted_policies_for_action(
        ctx.get("db"),
        space_id=space_id,
        action=action,
        resource_type=resource_type,
    ):
        rule_json = _as_dict(row.rule_json)
        policy_json = _as_dict(row.policy_json)
        effect = _normalize_effect(
            row.enforcement_mode
            or rule_json.get("effect")
            or policy_json.get("effect")
        )
        if effect is None:
            continue
        reason = (
            rule_json.get("reason")
            or policy_json.get("reason")
            or f"Persisted policy {row.name!r} applied"
        )
        return PolicyDecision(
            decision=effect,
            reason=str(reason),
            risk_level=_normalize_risk(rule_json.get("risk_level") or policy_json.get("risk_level")),
            required_approver_role=rule_json.get("required_approver_role")
            or policy_json.get("required_approver_role"),
            policy_rule_id=row.policy_key or f"persisted.{MEMORY_WRITE_DIRECT}",
            policy_source="persisted",
            policy_id=row.id,
            actor_id=ctx.get("actor_id"),
            actor_ref=ctx.get("actor_ref") if isinstance(ctx.get("actor_ref"), dict) else None,
            space_id=space_id,
            action=action,
            resource_type=resource_type,
        )
    return None


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
        result = persisted_policy_decision(ctx)
        if result is not None:
            return result
        return PolicyDecision(
            decision=_DEFAULT_ALLOW.decision,
            reason=_DEFAULT_ALLOW.reason,
            risk_level=_DEFAULT_ALLOW.risk_level,
            policy_rule_id=_DEFAULT_ALLOW.policy_rule_id,
            policy_source=_DEFAULT_ALLOW.policy_source,
            actor_id=ctx.get("actor_id"),
            actor_ref=ctx.get("actor_ref") if isinstance(ctx.get("actor_ref"), dict) else None,
            space_id=ctx.get("space_id"),
            action=ctx.get("action"),
            resource_type=ctx.get("resource_type"),
        )

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
