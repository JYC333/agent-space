"""Persist memory read audit rows and bump MemoryEntry aggregate counters.

Memory follow-up TODOs (see also read_auth, Proposal, context_api):
- Review transaction boundary: this module does not commit; callers own the
  Session lifecycle—uncommitted work stays in the same transaction as the log row.
- Consider reducing search_hit (and similar) access log volume later if tables grow.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from ulid import ULID

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import MemoryEntry


def _new_id() -> str:
    return str(ULID())


def record_memory_access(
    db: "Session",
    memory: "MemoryEntry",
    *,
    space_id: str,
    user_id: str | None,
    agent_id: str | None,
    run_id: str | None,
    access_type: str,
    reason: str | None,
) -> None:
    """Append one log row and bump aggregates; does not flush/commit (caller decides)."""
    from ..models import MemoryReadTrace

    log = MemoryReadTrace(
        id=_new_id(),
        space_id=space_id,
        memory_id=memory.id,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        access_type=access_type,
        reason=reason,
        accessed_at=datetime.now(UTC),
    )
    db.add(log)
    memory.access_count = (memory.access_count or 0) + 1
    memory.last_accessed_at = log.accessed_at
