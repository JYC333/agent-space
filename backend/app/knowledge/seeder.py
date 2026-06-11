"""Seed default Notes collections for a space.

PARA is only the initial folder template. Once a space has any note collection
rows, normal folders are left alone so user customizations are not recreated on
startup.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import NoteCollection


DEFAULT_NOTE_COLLECTIONS: tuple[tuple[str, str, int, bool], ...] = (
    ("Inbox", "inbox", 0, True),
    ("Projects", "normal", 100, False),
    ("Areas", "normal", 200, False),
    ("Resources", "normal", 300, False),
    ("Archive", "archive", 400, True),
)


def seed_default_note_collections(db: Session, space_id: str) -> int:
    """Idempotently seed the default Notes collection tree for ``space_id``.

    If the space has no collections, seed the full default template. If it
    already has collections, only ensure the protected system Inbox/Archive
    collections exist.
    """

    existing_count = db.query(NoteCollection.id).filter(NoteCollection.space_id == space_id).count()
    inserted = 0

    def has_system_role(role: str) -> bool:
        return (
            db.query(NoteCollection.id)
            .filter(NoteCollection.space_id == space_id, NoteCollection.system_role == role)
            .first()
            is not None
        )

    def add(name: str, role: str, sort_order: int, is_system: bool) -> None:
        nonlocal inserted
        db.add(
            NoteCollection(
                space_id=space_id,
                parent_id=None,
                name=name,
                system_role=role,
                sort_order=sort_order,
                is_system=is_system,
                is_hidden=False,
            )
        )
        inserted += 1

    if existing_count == 0:
        for name, role, sort_order, is_system in DEFAULT_NOTE_COLLECTIONS:
            add(name, role, sort_order, is_system)
    else:
        if not has_system_role("inbox"):
            add("Inbox", "inbox", 0, True)
        if not has_system_role("archive"):
            add("Archive", "archive", 400, True)

    if inserted:
        db.flush()
    return inserted
