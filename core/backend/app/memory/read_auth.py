"""
Centralized memory read authorization and summary-only redaction helpers.

All list/search/get/context paths must use ``can_read_memory`` so visibility,
sensitivity, owner/subject separation, and scope (system / public_template) stay
consistent. Do not infer ``owner_user_id`` from ``subject_user_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import MemoryEntry

SENSITIVITY_LEVELS = frozenset({"normal", "sensitive", "restricted", "highly_restricted"})

VISIBILITY_VALUES = frozenset(
    {
        "private",
        "space_shared",
        "workspace_shared",
        "selected_users",
        "summary_only",
        "restricted",
        "public_template",
    }
)


# Memory follow-up: if space membership rules tighten, revisit JSON storage and
# equality semantics for selected_user_ids (e.g. normalise types vs user_id).
def user_in_selected_ids(memory: "MemoryEntry", user_id: str) -> bool:
    raw: Any = memory.selected_user_ids
    if raw is None:
        return False
    if isinstance(raw, list):
        return user_id in raw
    if isinstance(raw, str):
        return user_id == raw
    return False


def can_read_memory(
    memory: "MemoryEntry",
    *,
    user_id: str,
    space_id: str,
    workspace_id: str | None = None,
    include_system_scope: bool = False,
    include_public_templates: bool = False,
) -> bool:
    """
    Return True if this reader may see the memory in any form (full or summary-only redacted).

    Normal family reads pass include_system_scope=False and include_public_templates=False.
    ContextBuilder's explicit system-policy branch uses include_system_scope=True.
    """
    if memory.space_id != space_id or memory.deleted_at is not None:
        return False

    sens = (getattr(memory, "sensitivity_level", None) or "normal").lower()
    vis = (memory.visibility or "private").lower()
    owner = memory.owner_user_id
    scope_t = memory.scope_type

    if not include_public_templates and vis == "public_template":
        return False

    if not include_system_scope and scope_t == "system":
        return False

    if sens == "highly_restricted":
        if owner and owner == user_id:
            return True
        return False

    if owner and owner == user_id:
        return True

    if vis == "private":
        return False

    if vis == "restricted":
        return user_in_selected_ids(memory, user_id)

    if vis == "selected_users":
        return user_in_selected_ids(memory, user_id)

    if vis == "summary_only":
        return True

    if vis == "workspace_shared":
        if workspace_id is None or memory.workspace_id is None:
            return False
        return memory.workspace_id == workspace_id

    if vis == "space_shared":
        return True

    if vis == "public_template" and include_public_templates:
        return True

    return False


def summary_only_redact_content(memory: "MemoryEntry", *, viewer_user_id: str) -> bool:
    """True if full ``content`` must not be exposed (summary_only visibility, non-owner)."""
    if (memory.visibility or "").lower() != "summary_only":
        return False
    if memory.owner_user_id and memory.owner_user_id == viewer_user_id:
        return False
    return True

