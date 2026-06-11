from __future__ import annotations

"""Approval resolver for policy actions.

Determines whether a given user has the authority to approve a sensitive
action in a space, based on their SpaceMembership role and the action's
risk level.

Canonical approval role matrix:
  owner    — approves low / medium / high / critical.
  admin    — approves low / medium / high (not critical).
  reviewer — approves low / medium only.
  member   — cannot approve.
  guest    — cannot approve.
"""

from typing import Any

from .actions import require_action_definition
from .decisions import RiskLevel

_RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

_ADMIN_MAX_RISK = RiskLevel.HIGH
_REVIEWER_MAX_RISK = RiskLevel.MEDIUM


def get_space_role(db: Any, user_id: str, space_id: str) -> str | None:
    """Return the user's active SpaceMembership role in the given space, or None."""
    from ..models import SpaceMembership

    membership = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    return membership.role if membership is not None else None


def can_approve_policy_action(
    db: Any,
    *,
    user_id: str,
    space_id: str,
    action: str,
    proposal_type: str | None = None,
    risk_level: RiskLevel | None = None,
    approval_capability: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> bool:
    """Return True if the user has approval authority for the given action.

    Raises UnknownPolicyActionError for any action not in the canonical registry.
    Unknown actions never fall through to allow.

    Resolution order for risk_level:
      1. Explicit ``risk_level`` argument (if provided, must be a RiskLevel instance).
      2. Default risk level from the action registry.
    """
    defn = require_action_definition(action)

    role = get_space_role(db, user_id, space_id)
    if role is None:
        return False

    resolved_risk = risk_level if risk_level is not None else defn.default_risk_level

    if role == "owner":
        return True

    if role == "admin":
        return _RISK_RANK[resolved_risk] <= _RISK_RANK[_ADMIN_MAX_RISK]

    if role == "reviewer":
        return _RISK_RANK[resolved_risk] <= _RISK_RANK[_REVIEWER_MAX_RISK]

    return False
