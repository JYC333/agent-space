"""Stage 6 slice 7a: memory_access_logs retention sweep.

The TS read path appends one trace row per read (`search_hit` writes one per
returned hit), so the audit table grows unbounded. `prune_memory_access_logs`
drops rows older than the retention window. It must never touch the aggregate
read counters on `memory_entries` — those feed the MemoryEvolver fitness.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, UTC

import pytest

from app.config import Settings
from app.memory.access_log import prune_memory_access_logs
from app.models import MemoryReadTrace
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _trace(db, *, memory_id: str, accessed_at: datetime) -> None:
    db.add(
        MemoryReadTrace(
            id=uuid.uuid4().hex,
            space_id=PERSONAL_SPACE_ID,
            memory_id=memory_id,
            user_id=DEFAULT_USER_ID,
            access_type="search_hit",
            reason="memory search",
            accessed_at=accessed_at,
        )
    )


def test_prune_drops_only_rows_older_than_retention(db):
    mem = factories.create_test_memory_entry(
        db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID
    )
    db.flush()
    now = datetime(2026, 6, 15, tzinfo=UTC)
    _trace(db, memory_id=mem.id, accessed_at=now - timedelta(days=120))
    _trace(db, memory_id=mem.id, accessed_at=now - timedelta(days=91))
    _trace(db, memory_id=mem.id, accessed_at=now - timedelta(days=30))
    _trace(db, memory_id=mem.id, accessed_at=now - timedelta(days=1))
    db.flush()

    deleted = prune_memory_access_logs(db, older_than_days=90, now=now)

    assert deleted == 2
    remaining = (
        db.query(MemoryReadTrace)
        .filter(MemoryReadTrace.memory_id == mem.id)
        .all()
    )
    assert len(remaining) == 2
    assert all(r.accessed_at >= now - timedelta(days=90) for r in remaining)


def test_prune_does_not_touch_memory_entry_counters(db):
    """The evolver fitness reads access_count/last_accessed_at — pruning the
    trace rows must leave those aggregates intact."""
    mem = factories.create_test_memory_entry(
        db, space_id=PERSONAL_SPACE_ID, owner_user_id=DEFAULT_USER_ID
    )
    now = datetime(2026, 6, 15, tzinfo=UTC)
    mem.access_count = 5
    mem.last_accessed_at = now
    db.flush()
    _trace(db, memory_id=mem.id, accessed_at=now - timedelta(days=365))
    db.flush()

    prune_memory_access_logs(db, older_than_days=90, now=now)
    db.refresh(mem)

    assert mem.access_count == 5
    assert mem.last_accessed_at == now


def test_retention_config_bounds_are_enforced():
    with pytest.raises(ValueError):
        Settings(memory_access_log_retention_days=0)
    with pytest.raises(ValueError):
        Settings(memory_access_log_prune_interval_seconds=299)
    ok = Settings(
        memory_access_log_retention_days=1,
        memory_access_log_prune_interval_seconds=300,
    )
    assert ok.memory_access_log_retention_days == 1
