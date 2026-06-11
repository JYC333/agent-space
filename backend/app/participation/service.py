"""
ParticipationRecord creation service.

Best-effort: records a user's participation in a shared-space object by
creating a pointer in the participation_records table, linked to the user's
personal space. The parent operation must never fail because of this service.

Rules:
  - Only creates records when source_space.type != "personal".
  - Finds the user's personal space via SpaceMembership + Space.type == "personal".
  - If no personal space exists, skips without error.
  - Does not copy content; stores pointer metadata only.
  - Duplicate guard: skips creation if an identical record already exists
    (user_id + source_space_id + source_object_type + source_object_id + role).
"""

from __future__ import annotations
import uuid

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..models import ParticipationRecord, Space, SpaceMembership

log = logging.getLogger(__name__)


def try_record_participation(
    db: Session,
    *,
    user_id: str | None,
    source_space_id: str,
    source_object_type: str,
    source_object_id: str,
    role: str,
    occurred_at: datetime | None = None,
) -> None:
    """Best-effort wrapper: logs and swallows any error so the parent operation is unaffected.

    Uses a savepoint (begin_nested) so that a participation failure rolls back only
    the participation write, never the caller's uncommitted state.
    """
    if not user_id:
        return
    try:
        with db.begin_nested():  # savepoint — on exception, only this write is rolled back
            result = record_participation(
                db,
                user_id=user_id,
                source_space_id=source_space_id,
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                role=role,
                occurred_at=occurred_at,
            )
        if result is not None:
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "participation record failed for %s/%s (user=%s role=%s): %s",
            source_object_type,
            source_object_id,
            user_id,
            role,
            exc,
        )


def _new_id() -> str:
    return str(uuid.uuid4())


def _find_personal_space_id(db: Session, user_id: str) -> str | None:
    """Return the personal space ID for user_id, or None if not found."""
    row = (
        db.query(SpaceMembership)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
            Space.type == "personal",
        )
        .first()
    )
    return row.space_id if row else None


def _source_space_type(db: Session, source_space_id: str) -> str:
    space = db.query(Space).filter(Space.id == source_space_id).first()
    return space.type if space else "unknown"


def _already_exists(
    db: Session,
    *,
    user_id: str,
    source_space_id: str,
    source_object_type: str,
    source_object_id: str,
    role: str,
) -> bool:
    return (
        db.query(ParticipationRecord)
        .filter(
            ParticipationRecord.user_id == user_id,
            ParticipationRecord.source_space_id == source_space_id,
            ParticipationRecord.source_object_type == source_object_type,
            ParticipationRecord.source_object_id == source_object_id,
            ParticipationRecord.role == role,
        )
        .first()
    ) is not None


def record_participation(
    db: Session,
    *,
    user_id: str,
    source_space_id: str,
    source_object_type: str,
    source_object_id: str,
    role: str,
    occurred_at: datetime | None = None,
) -> ParticipationRecord | None:
    """
    Create a ParticipationRecord best-effort.

    Returns the created record, or None if skipped (personal source space,
    no personal space found for user, or duplicate).

    The caller must NOT fail if this raises — wrap in try/except at call sites.
    """
    space_type = _source_space_type(db, source_space_id)
    if space_type == "personal":
        return None

    personal_space_id = _find_personal_space_id(db, user_id)
    if not personal_space_id:
        log.debug(
            "participation: no personal space for user %s; skipping %s/%s",
            user_id,
            source_object_type,
            source_object_id,
        )
        return None

    if _already_exists(
        db,
        user_id=user_id,
        source_space_id=source_space_id,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        role=role,
    ):
        return None

    rec = ParticipationRecord(
        id=_new_id(),
        user_id=user_id,
        personal_space_id=personal_space_id,
        source_space_id=source_space_id,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        role=role,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(rec)
    db.flush()
    return rec
