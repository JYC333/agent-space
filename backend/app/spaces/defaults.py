"""Default-space resolution (single-user / dev fallback).

There is no configured default space id and no magic ``"personal"`` string.
The default space is the bootstrap owner's *personal* space — created by
``bootstrap_instance`` with a generated UUID and located by owner membership.

Service create-paths use ``resolve_default_space_id`` only as a single-user
convenience when a request carries no explicit ``space_id``; multi-user
requests always supply their own space.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Space, SpaceMembership


def personal_space_id_for_owner(db: Session, user_id: str) -> str | None:
    """Return the id of the personal space owned by ``user_id`` (or ``None``).

    A personal space is one whose ``type == 'personal'`` and on which the user
    holds an active ``owner`` membership.
    """
    row = (
        db.query(SpaceMembership.space_id)
        .join(Space, Space.id == SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.role == "owner",
            SpaceMembership.status == "active",
            Space.type == "personal",
        )
        .first()
    )
    return row[0] if row else None


def resolve_default_space_id(db: Session) -> str:
    """The bootstrap owner's personal space id.

    Raises ``RuntimeError`` if it does not exist yet — ``bootstrap_instance``
    creates it on startup, so a missing default space means bootstrap has not
    run against this database.
    """
    space_id = personal_space_id_for_owner(db, settings.default_user_id)
    if space_id is None:
        raise RuntimeError(
            "No default space available: bootstrap_instance() must create the "
            "owner's personal space before a space-less create call."
        )
    return space_id
