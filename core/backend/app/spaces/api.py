from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, UTC, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from ulid import ULID

from ..db import get_db
from ..models import Space, SpaceMembership, SpaceInvitation, User
from ..auth.session import get_current_user
from ..auth.policy import (
    require_view_space, require_invite_member, require_manage_space,
)
from ..auth.service import UserService

router = APIRouter(prefix="/spaces", tags=["spaces"])
invitations_router = APIRouter(prefix="/invitations", tags=["invitations"])
extra_routers = [invitations_router]


def _new_id() -> str:
    return str(ULID())


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class SpaceCreate(BaseModel):
    name: str
    type: Literal["personal", "household", "team"] = "team"


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"


def _space_out(space: Space, role: Optional[str] = None) -> dict:
    d = {
        "id": space.id,
        "name": space.name,
        "type": space.type,
        "created_by_user_id": getattr(space, "created_by_user_id", None),
        "created_at": space.created_at.isoformat(),
        "updated_at": space.updated_at.isoformat(),
    }
    if role is not None:
        d["role"] = role
    return d


@router.post("", status_code=201)
def create_space(
    data: SpaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.type == "personal":
        raise HTTPException(status_code=400, detail="Cannot explicitly create a personal space")
    space = UserService(db).create_space(user.id, data.name, data.type)
    return _space_out(space, role="owner")


@router.get("/{space_id}")
def get_space(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_view_space(db, user.id, space_id)
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    m = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space_id,
        SpaceMembership.user_id == user.id,
    ).first()
    return _space_out(space, role=m.role if m else None)


@router.get("/{space_id}/members")
def list_members(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_view_space(db, user.id, space_id)
    rows = (
        db.query(SpaceMembership, User)
        .join(User, SpaceMembership.user_id == User.id)
        .filter(SpaceMembership.space_id == space_id, SpaceMembership.status == "active")
        .all()
    )
    return [
        {
            "user_id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "avatar_url": u.avatar_url,
            "role": m.role,
            "joined_at": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


@router.post("/{space_id}/invitations", status_code=201)
def create_invitation(
    space_id: str,
    data: InvitationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_invite_member(db, user.id, space_id)

    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    raw_token = secrets.token_urlsafe(32)
    inv = SpaceInvitation(
        id=_new_id(),
        space_id=space_id,
        invited_email=data.email,
        role=data.role,
        token_hash=_hash_token(raw_token),
        invited_by_user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.commit()

    return {
        "id": inv.id,
        "space_id": space_id,
        "invited_email": data.email,
        "role": data.role,
        "token": raw_token,
        "status": inv.status,
        "expires_at": inv.expires_at.isoformat(),
    }


@invitations_router.post("/{token}/accept")
def accept_invitation(
    token: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = _hash_token(token)
    inv = db.query(SpaceInvitation).filter(SpaceInvitation.token_hash == h).first()

    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status != "pending":
        raise HTTPException(status_code=409, detail=f"Invitation is already {inv.status}")

    expires = inv.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        inv.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")

    if user.email.lower() != inv.invited_email.lower():
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address")

    # Check not already a member
    existing = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == inv.space_id,
        SpaceMembership.user_id == user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already a member of this space")

    db.add(SpaceMembership(
        id=_new_id(),
        space_id=inv.space_id,
        user_id=user.id,
        role=inv.role,
        status="active",
    ))
    inv.status = "accepted"
    inv.accepted_at = datetime.now(UTC)
    db.commit()

    space = db.query(Space).filter(Space.id == inv.space_id).first()
    return {"space_id": inv.space_id, "role": inv.role, "space_name": space.name if space else None}
