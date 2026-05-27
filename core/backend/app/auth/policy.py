from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..policy.roles import has_role_at_least, normalize_role


def _get_role(db: Session, user_id: str, space_id: str) -> str | None:
    """Return the normalized canonical role for user in space, or None if not a member."""
    from ..models import SpaceMembership

    m = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if m is None:
        return None
    return normalize_role(m.role)  # "viewer" and any unknown → "guest"


def can_view_space(db: Session, user_id: str, space_id: str) -> bool:
    return _get_role(db, user_id, space_id) is not None


def can_use_space(db: Session, user_id: str, space_id: str) -> bool:
    role = _get_role(db, user_id, space_id)
    return role is not None and has_role_at_least(role, "member")


def can_manage_space_resources(db: Session, user_id: str, space_id: str) -> bool:
    role = _get_role(db, user_id, space_id)
    return role is not None and has_role_at_least(role, "admin")


def can_invite_member(db: Session, user_id: str, space_id: str) -> bool:
    role = _get_role(db, user_id, space_id)
    return role is not None and has_role_at_least(role, "admin")


def can_manage_space(db: Session, user_id: str, space_id: str) -> bool:
    role = _get_role(db, user_id, space_id)
    return role is not None and has_role_at_least(role, "owner")


def require_view_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_view_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Not a member of this space")


def require_use_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_use_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires member role or above")


def require_manage_space_resources(db: Session, user_id: str, space_id: str) -> None:
    if not can_manage_space_resources(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires admin role")


def require_invite_member(db: Session, user_id: str, space_id: str) -> None:
    if not can_invite_member(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires admin role to invite")


def require_manage_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_manage_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires owner role")
