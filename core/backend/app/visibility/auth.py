"""
Visibility authorization helper for non-memory scoped objects.

Used by Task, Run, Artifact, ActivityRecord, and Proposal list/get paths
to enforce the visibility column.

Rules:
  space_shared  → readable by any space member
  private       → readable only by the owner (owner_user_id)
  restricted    → readable only by the owner (no selected-users field on these objects yet)
  unknown       → deny by default (fail closed)

public visibility is not implemented.
"""

from __future__ import annotations

_KNOWN_VISIBILITY = frozenset({"space_shared", "private", "restricted"})


def can_read_scoped_object(
    *,
    visibility: str,
    owner_user_id: str | None,
    current_user_id: str | None,
    is_space_member: bool,
) -> bool:
    """Return True if current_user_id may read the object.

    Parameters
    ----------
    visibility:
        The object's visibility column value.
    owner_user_id:
        The user who owns the object (object-type-specific convention):
          - Artifact / ActivityRecord: owner_user_id column
          - Run: instructed_by_user_id
          - Task: created_by_user_id
          - Proposal: created_by_user_id
    current_user_id:
        The authenticated user making the request.
    is_space_member:
        Whether current_user_id is an active member of the object's space.
    """
    if not current_user_id:
        return False

    vis = (visibility or "space_shared").lower()

    if vis == "space_shared":
        return is_space_member

    if vis in ("private", "restricted"):
        return bool(owner_user_id and owner_user_id == current_user_id)

    # Unknown or future visibility values: fail closed.
    return False
