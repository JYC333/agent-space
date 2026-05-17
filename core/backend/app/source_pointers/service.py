"""
SourcePointer metadata service.

Creates and lists provenance pointers only. Never fetches source object content and
never bypasses source-space membership or policy checks. Cross-space reads remain
denied via memory.cross_space_read; access_mode values are intent labels for future
federation/subscribe flows, not read grants.

HTTP membership checks live in ``app.source_pointers.api``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..models import SourcePointer, SpaceMembership
from ..personal_memory_grants.egress_guard import (
    EgressDecision,
    check_source_pointer_metadata_egress,
)
from .validation import validate_metadata_json


class GrantDerivedSourcePointerError(ValueError):
    """Raised when SourcePointer metadata contains grant-derived indicators for a non-personal owner_space."""

VALID_ACCESS_MODES = frozenset({"read", "subscribe", "federated"})


class InvalidSourcePointerAccessModeError(ValueError):
    """Raised when access_mode is not one of the allowed pointer intent values."""


class InvalidSourcePointerExpiresAtError(ValueError):
    """Raised when expires_at is in the past."""


def _validate_access_mode(access_mode: str) -> None:
    if access_mode not in VALID_ACCESS_MODES:
        raise InvalidSourcePointerAccessModeError(
            f"invalid access_mode {access_mode!r}; must be one of {sorted(VALID_ACCESS_MODES)}"
        )


def _validate_expires_at(expires_at: datetime | None) -> None:
    if expires_at is None:
        return
    now = datetime.now(UTC)
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    if exp < now:
        raise InvalidSourcePointerExpiresAtError("expires_at must not be in the past")


def create_source_pointer(
    db: Session,
    *,
    owner_space_id: str,
    source_space_id: str,
    source_object_type: str,
    source_object_id: str,
    access_mode: str,
    granted_by_user_id: str | None = None,
    expires_at: datetime | None = None,
    metadata_json: dict | None = None,
) -> SourcePointer:
    """Persist a provenance pointer in owner_space (metadata only).

    ``granted_by_user_id`` is trusted server-side input only. The public API must derive
    it from the authenticated identity (see ``app.source_pointers.api``); this service is
    not a public authorization boundary and must not receive client-supplied grantor ids.
    """
    _validate_access_mode(access_mode)
    validate_metadata_json(metadata_json)
    _validate_expires_at(expires_at)

    # Reject grant-derived indicator keys in metadata for non-personal owner_space.
    sp_egress = check_source_pointer_metadata_egress(
        db, owner_space_id=owner_space_id, metadata_json=metadata_json
    )
    if sp_egress.decision == EgressDecision.BLOCK:
        raise GrantDerivedSourcePointerError(sp_egress.reason)

    pointer = SourcePointer(
        owner_space_id=owner_space_id,
        source_space_id=source_space_id,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        access_mode=access_mode,
        granted_by_user_id=granted_by_user_id,
        expires_at=expires_at,
        metadata_json=metadata_json,
    )
    db.add(pointer)
    db.flush()
    return pointer


def list_source_pointers_for_owner_space(
    db: Session,
    *,
    owner_space_id: str,
) -> list[SourcePointer]:
    """Return pointers owned by owner_space_id (no source content resolution)."""
    return (
        db.query(SourcePointer)
        .filter(SourcePointer.owner_space_id == owner_space_id)
        .order_by(SourcePointer.created_at.desc())
        .all()
    )


def get_source_pointer(
    db: Session,
    *,
    pointer_id: str,
    owner_space_id: str,
) -> SourcePointer | None:
    """Return a pointer when it belongs to owner_space_id, else None."""
    return (
        db.query(SourcePointer)
        .filter(
            SourcePointer.id == pointer_id,
            SourcePointer.owner_space_id == owner_space_id,
        )
        .first()
    )


def get_source_pointer_by_id(db: Session, *, pointer_id: str) -> SourcePointer | None:
    """Return a pointer by id (caller must enforce owner_space membership)."""
    return db.query(SourcePointer).filter(SourcePointer.id == pointer_id).first()


def _active_member_space_ids(db: Session, *, user_id: str) -> list[str]:
    rows = (
        db.query(SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .all()
    )
    return [r[0] for r in rows]


def list_source_pointers_for_user(
    db: Session,
    *,
    user_id: str,
    owner_space_id: str | None = None,
) -> list[SourcePointer]:
    """List pointers owned by spaces the user belongs to (metadata only)."""
    member_ids = _active_member_space_ids(db, user_id=user_id)
    if not member_ids:
        return []
    if owner_space_id is not None:
        if owner_space_id not in member_ids:
            return []
        scope_ids = [owner_space_id]
    else:
        scope_ids = member_ids
    return (
        db.query(SourcePointer)
        .filter(SourcePointer.owner_space_id.in_(scope_ids))
        .order_by(SourcePointer.created_at.desc())
        .all()
    )


def delete_source_pointer(db: Session, *, pointer_id: str) -> bool:
    """Hard-delete pointer metadata. Does not touch the source object. Returns True if deleted."""
    row = db.query(SourcePointer).filter(SourcePointer.id == pointer_id).first()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
