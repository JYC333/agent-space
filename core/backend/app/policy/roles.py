from __future__ import annotations

"""Canonical product role definitions and authority helpers.

Canonical roles (in ascending authority order):
    guest     — read invited content only
    member    — create activity, artifacts, proposals; run low-risk allowed actions
    reviewer  — approve medium-risk project/space proposals (memory/wiki/task updates)
    admin     — approve high-risk policy/capability/credential/workspace actions
    owner     — full authority inside the space (hard invariants still apply)

No other role strings are recognized as granting approval authority.
Roles outside this set are treated as equivalent to "guest" for authority checks.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .decisions import PolicyDecision, RiskLevel

CANONICAL_ROLES: tuple[str, ...] = ("guest", "member", "reviewer", "admin", "owner")

_ROLE_RANK: dict[str, int] = {role: i for i, role in enumerate(CANONICAL_ROLES)}

def normalize_role(raw: str) -> str:
    """Normalize a raw role string to a canonical role.

    Canonical roles return as-is. Unknown roles normalize to "guest" (least authority).
    """
    if not raw:
        return "guest"
    lower = raw.strip().lower()
    if lower in _ROLE_RANK:
        return lower
    return "guest"


def role_rank(role: str) -> int:
    """Return the numeric rank of a role. Higher = more authority. Unknown roles → 0."""
    return _ROLE_RANK.get(normalize_role(role), 0)


def has_role_at_least(role: str, required: str) -> bool:
    """Return True if role has at least the authority of required."""
    return role_rank(role) >= role_rank(required)


def can_approve_policy_decision(role: str, decision: "PolicyDecision") -> bool:
    """Return True if this role has authority to approve the given PolicyDecision.

    Approval rules:
      owner   → approves everything
      admin   → approves low / medium / high risk (not critical)
      reviewer → approves low / medium risk only
      member / guest → cannot approve
    """
    from .decisions import RiskLevel

    normalized = normalize_role(role)
    risk = decision.risk_level

    if normalized == "owner":
        return True
    if normalized == "admin":
        return risk in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
    if normalized == "reviewer":
        return risk in (RiskLevel.LOW, RiskLevel.MEDIUM)
    return False


def can_approve_proposal_type(role: str, proposal_type: str, risk_level: str) -> bool:
    """Return True if role has authority to approve the given proposal type and risk.

    policy_change and capability.enable always require admin or owner.
    Canonical matrix: owner=all, admin=low/medium/high, reviewer=low/medium, member/guest=none.
    """
    from .decisions import RiskLevel

    normalized = normalize_role(role)

    try:
        rl = RiskLevel(risk_level)
    except ValueError:
        rl = RiskLevel.HIGH

    if normalized == "owner":
        return True

    if proposal_type in ("policy_change", "capability.enable", "tool_binding.enable"):
        return normalized == "admin" and rl in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)

    if normalized == "admin":
        return rl in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)

    if normalized == "reviewer":
        return rl in (RiskLevel.LOW, RiskLevel.MEDIUM)

    return False


def get_space_role_normalized(db: Any, user_id: str, space_id: str) -> str | None:
    """Return the user's normalized active SpaceMembership role in the given space, or None."""
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
    if membership is None:
        return None
    return normalize_role(membership.role)
