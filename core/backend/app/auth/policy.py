from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import SpaceMembership

_ROLE_RANK = {"viewer": 0, "guest": 1, "member": 1, "admin": 2, "owner": 3}


def _get_rank(db: Session, user_id: str, space_id: str) -> int:
    m = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    return _ROLE_RANK.get(m.role, -1) if m else -1


def can_view_space(db: Session, user_id: str, space_id: str) -> bool:
    return _get_rank(db, user_id, space_id) >= 0


def can_use_space(db: Session, user_id: str, space_id: str) -> bool:
    return _get_rank(db, user_id, space_id) >= _ROLE_RANK["member"]


def can_manage_space_resources(db: Session, user_id: str, space_id: str) -> bool:
    return _get_rank(db, user_id, space_id) >= _ROLE_RANK["admin"]


def can_invite_member(db: Session, user_id: str, space_id: str) -> bool:
    return _get_rank(db, user_id, space_id) >= _ROLE_RANK["admin"]


def can_manage_space(db: Session, user_id: str, space_id: str) -> bool:
    return _get_rank(db, user_id, space_id) >= _ROLE_RANK["owner"]


def require_view_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_view_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Not a member of this space")


def require_manage_space_resources(db: Session, user_id: str, space_id: str) -> None:
    if not can_manage_space_resources(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires admin role")


def require_invite_member(db: Session, user_id: str, space_id: str) -> None:
    if not can_invite_member(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires admin role to invite")


def require_manage_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_manage_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Requires owner role")
