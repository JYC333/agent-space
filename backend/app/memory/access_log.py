"""Persist memory read audit rows and bump MemoryEntry aggregate counters.

This module does not commit. Callers own the Session lifecycle; uncommitted
work stays in the same transaction as the log row. If search_hit volume grows
large, consider reducing log frequency at the call sites.
"""

from __future__ import annotations
import uuid

from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import MemoryEntry


def _new_id() -> str:
    return str(uuid.uuid4())


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
    # last_retrieved_at tracks when memory was injected into a run context.
    if access_type == "context_injection":
        memory.last_retrieved_at = log.accessed_at


def prune_memory_access_logs(
    db: "Session",
    *,
    older_than_days: int,
    now: datetime | None = None,
) -> int:
    """Delete `memory_access_logs` trace rows older than the retention window.

    This is a maintenance sweep, not an audit-semantics change: the aggregate
    read counters on `memory_entries` (`access_count` / `last_accessed_at`),
    which feed the MemoryEvolver fitness, are left untouched — only the
    append-only per-read trace rows are pruned. `search_hit` writes one row per
    returned hit, so without retention this table grows unbounded; nothing reads
    the rows back today (the evolver uses the counters), so old traces are safe
    to drop. Backend-owned: the control-plane role has INSERT-only on this table.

    Returns the number of rows deleted. Commits its own transaction.
    """
    from ..models import MemoryReadTrace

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=older_than_days)
    deleted = (
        db.query(MemoryReadTrace)
        .filter(MemoryReadTrace.accessed_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted)
