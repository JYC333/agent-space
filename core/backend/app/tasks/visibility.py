from __future__ import annotations

from app.models import Task


def can_read_task(task: Task, current_user_id: str) -> bool:
    """Return True if current_user_id may read the task.

    space_shared: any space member (space boundary enforced at the API layer).
    private / restricted: readable by created_by_user_id, assigned_user_id, or claimed_by_user_id.
    unknown: fail closed.
    """
    vis = (task.visibility or "space_shared").lower()
    if vis == "space_shared":
        return True
    if vis in ("private", "restricted"):
        return any(
            uid and uid == current_user_id
            for uid in (task.created_by_user_id, task.assigned_user_id, task.claimed_by_user_id)
        )
    return False
