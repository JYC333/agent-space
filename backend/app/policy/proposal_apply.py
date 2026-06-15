from __future__ import annotations

"""check_proposal_apply_policy — proposal.apply policy gate returning a full PolicyDecision.

Effective proposal risk is max(type_default, proposal.risk_level).
Invalid proposal.risk_level strings fail closed with ProposalRiskLevelError.
Proposal types with no real apply handler deny at this gate (audit_code="unsupported_proposal_type").
"""

from typing import Any

from .actions import require_action_definition
from .approval import get_space_role, _RISK_RANK, _ADMIN_MAX_RISK, _REVIEWER_MAX_RISK
from .decisions import Decision, PolicyDecision, RiskLevel


_PROPOSAL_TYPE_RISK: dict[str, RiskLevel] = {
    "memory_create": RiskLevel.MEDIUM,
    "memory_update": RiskLevel.MEDIUM,
    "memory_archive": RiskLevel.MEDIUM,
    "follow_up_task": RiskLevel.MEDIUM,
    "code_patch": RiskLevel.HIGH,
    "policy_change": RiskLevel.HIGH,
    "egress_review": RiskLevel.HIGH,
    "agent_config_update": RiskLevel.HIGH,
    "prompt_update": RiskLevel.MEDIUM,
    "knowledge_create": RiskLevel.MEDIUM,
    "knowledge_update": RiskLevel.MEDIUM,
    "knowledge_archive": RiskLevel.MEDIUM,
    "knowledge_relation_create": RiskLevel.MEDIUM,
    "knowledge_relation_delete": RiskLevel.MEDIUM,
}

KNOWLEDGE_PROPOSAL_TYPES: frozenset[str] = frozenset({
    "knowledge_create",
    "knowledge_update",
    "knowledge_archive",
    "knowledge_relation_create",
    "knowledge_relation_delete",
})

# Proposal types covered by the policy risk table above. A type is live-supported
# by the gate only when it has both a registered applier and an explicit risk
# table entry; tests pin the default registry keys == this set so the two
# sources cannot silently drift.
SUPPORTED_PROPOSAL_TYPES: frozenset[str] = frozenset(_PROPOSAL_TYPE_RISK.keys())


def _supported_proposal_types() -> frozenset[str]:
    """Proposal types with both a registered applier and a risk-table entry."""
    from ..proposals import get_proposal_applier_registry

    registered = frozenset(get_proposal_applier_registry().registered_appliers())
    return registered & SUPPORTED_PROPOSAL_TYPES


def supported_proposal_apply_types() -> frozenset[str]:
    """Public read-only view of live proposal types accepted by proposal.apply."""
    return _supported_proposal_types()

# Proposal types whose type-default risk is MEDIUM or lower.
# Effective risk = max(type_default, declared_risk). For types in this set the
# effective risk can be MEDIUM or lower when declared_risk is also <= MEDIUM.
# For HIGH-default types (code_patch, policy_change, egress_review) the effective
# risk is always >= HIGH regardless of declared_risk, so they are always excluded
# from roles whose approval authority tops out at MEDIUM (i.e. reviewer).
MEDIUM_DEFAULT_PROPOSAL_TYPES: frozenset[str] = frozenset(
    t for t, r in _PROPOSAL_TYPE_RISK.items()
    if _RISK_RANK[r] <= _RISK_RANK[RiskLevel.MEDIUM]
)


class ProposalRiskLevelError(Exception):
    """Raised when proposal.risk_level contains an invalid risk string."""

    def __init__(self, risk_value: str) -> None:
        self.risk_value = risk_value
        super().__init__(
            f"Invalid proposal risk_level {risk_value!r}. "
            "Must be one of: low, medium, high, critical."
        )


def _parse_proposal_risk(risk_str: str | None) -> RiskLevel | None:
    """Parse proposal.risk_level string. Returns None for None/empty. Raises ProposalRiskLevelError for invalid."""
    if not risk_str:
        return None
    try:
        return RiskLevel(risk_str)
    except ValueError:
        raise ProposalRiskLevelError(risk_str)


def effective_proposal_risk(proposal_type: str, declared_risk_str: str | None) -> RiskLevel:
    """Compute effective risk as max(type_default, declared_risk).

    Raises ProposalRiskLevelError if declared_risk_str is set but not a valid RiskLevel.
    Unknown proposal types default to HIGH.
    """
    type_default = _PROPOSAL_TYPE_RISK.get(proposal_type, RiskLevel.HIGH)
    declared = _parse_proposal_risk(declared_risk_str)
    if declared is None:
        return type_default
    return declared if _RISK_RANK[declared] > _RISK_RANK[type_default] else type_default


def check_proposal_apply_policy(
    db: Any,
    *,
    user_id: str,
    space_id: str,
    proposal: Any,
) -> PolicyDecision:
    """Evaluate the proposal.apply policy gate and return a full PolicyDecision.

    Behavior:
      - deny: proposal type has no supported apply handler (audit_code="unsupported_proposal_type").
      - allow: actor has approval authority; proceed to ProposalApplyService.apply().
      - require_approval: actor lacks approval authority at this acceptance boundary.
        Treat as denial; do not call apply. Raise a clear error to the caller.

    Raises ProposalRiskLevelError if proposal.risk_level contains an invalid risk string.
    """
    defn = require_action_definition("proposal.apply")

    # Unsupported types fail at the gate before risk parsing, role lookup, or
    # DB policy checks. "Supported" means a registered applier exists and the
    # policy risk table has an explicit entry for the proposal type.
    if proposal.proposal_type not in _supported_proposal_types():
        return PolicyDecision(
            decision=Decision.DENY,
            message=(
                f"Proposal type {proposal.proposal_type!r} has no supported apply handler"
            ),
            risk_level=RiskLevel.HIGH,
            reason_code="unsupported_proposal_type",
            policy_rule_id="proposal_type_not_supported",
            action="proposal.apply",
            resource_type=defn.resource_type,
            resource_id=proposal.id,
            proposal_type=proposal.proposal_type,
            approval_capability=defn.approval_capability,
            audit_code="unsupported_proposal_type",
            space_id=space_id,
            actor_id=user_id,
            actor_type="user",
            metadata_json={
                "proposal_type": proposal.proposal_type,
                "supported_apply_type": False,
            },
        )

    risk = effective_proposal_risk(proposal.proposal_type, proposal.risk_level)

    role = get_space_role(db, user_id, space_id)

    def _meta(membership_role: str | None) -> dict:
        return {
            "proposal_type": proposal.proposal_type,
            "membership_role": membership_role,
            "effective_risk": risk.value,
            "proposal_declared_risk": proposal.risk_level,
            "default_type_risk": _PROPOSAL_TYPE_RISK.get(proposal.proposal_type, RiskLevel.HIGH).value,
            "supported_apply_type": True,
        }

    if role is None:
        return PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="User is not a member of this space",
            risk_level=risk,
            reason_code="no_membership",
            policy_rule_id="proposal_apply_no_membership",
            action="proposal.apply",
            resource_type=defn.resource_type,
            resource_id=proposal.id,
            proposal_type=proposal.proposal_type,
            approval_capability=defn.approval_capability,
            audit_code="no_membership",
            space_id=space_id,
            actor_id=user_id,
            actor_type="user",
            metadata_json=_meta(None),
        )

    if role == "owner":
        return PolicyDecision(
            decision=Decision.ALLOW,
            message=f"User has owner role; approved for {risk.value}-risk proposal",
            risk_level=risk,
            reason_code="approved_owner",
            policy_rule_id="proposal_apply_owner_allow",
            action="proposal.apply",
            resource_type=defn.resource_type,
            resource_id=proposal.id,
            proposal_type=proposal.proposal_type,
            approval_capability=defn.approval_capability,
            audit_code="approved_owner",
            space_id=space_id,
            actor_id=user_id,
            actor_type="user",
            metadata_json=_meta(role),
        )

    if role == "admin" and _RISK_RANK[risk] <= _RISK_RANK[_ADMIN_MAX_RISK]:
        return PolicyDecision(
            decision=Decision.ALLOW,
            message=f"User has admin role; approved for {risk.value}-risk proposal",
            risk_level=risk,
            reason_code="approved_admin",
            policy_rule_id="proposal_apply_admin_allow",
            action="proposal.apply",
            resource_type=defn.resource_type,
            resource_id=proposal.id,
            proposal_type=proposal.proposal_type,
            approval_capability=defn.approval_capability,
            audit_code="approved_admin",
            space_id=space_id,
            actor_id=user_id,
            actor_type="user",
            metadata_json=_meta(role),
        )

    if role == "reviewer" and _RISK_RANK[risk] <= _RISK_RANK[_REVIEWER_MAX_RISK]:
        return PolicyDecision(
            decision=Decision.ALLOW,
            message=f"User has reviewer role; approved for {risk.value}-risk proposal",
            risk_level=risk,
            reason_code="approved_reviewer",
            policy_rule_id="proposal_apply_reviewer_allow",
            action="proposal.apply",
            resource_type=defn.resource_type,
            resource_id=proposal.id,
            proposal_type=proposal.proposal_type,
            approval_capability=defn.approval_capability,
            audit_code="approved_reviewer",
            space_id=space_id,
            actor_id=user_id,
            actor_type="user",
            metadata_json=_meta(role),
        )

    return PolicyDecision(
        decision=Decision.REQUIRE_APPROVAL,
        message=f"User has {role!r} role; insufficient authority for {risk.value}-risk proposal",
        risk_level=risk,
        reason_code="insufficient_role",
        policy_rule_id="proposal_apply_insufficient_role",
        action="proposal.apply",
        resource_type=defn.resource_type,
        resource_id=proposal.id,
        proposal_type=proposal.proposal_type,
        approval_capability=defn.approval_capability,
        audit_code="insufficient_role",
        space_id=space_id,
        actor_id=user_id,
        actor_type="user",
        metadata_json=_meta(role),
    )
