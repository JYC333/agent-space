"""ORM MemoryEntry → API MemoryOut with centralized read checks and summary-only redaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas import MemoryOut
from .read_auth import can_read_memory, summary_only_redact_content

if TYPE_CHECKING:
    from ..models import MemoryEntry


def memory_entry_to_out(
    memory: "MemoryEntry",
    *,
    viewer_user_id: str,
    space_id: str,
    workspace_id: str | None = None,
    include_system_scope: bool = False,
    include_public_templates: bool = False,
) -> MemoryOut | None:
    if not can_read_memory(
        memory,
        user_id=viewer_user_id,
        space_id=space_id,
        workspace_id=workspace_id,
        include_system_scope=include_system_scope,
        include_public_templates=include_public_templates,
    ):
        return None
    out = MemoryOut.model_validate(memory)
    if summary_only_redact_content(memory, viewer_user_id=viewer_user_id):
        return out.model_copy(update={"content": None})
    return out
