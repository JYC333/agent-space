from __future__ import annotations
"""
Internal-only write paths for MemoryEntry and Policy rows.

ALLOWED CALLERS
---------------
- ProposalApplyService  (accepted-proposal application — the normal durable write boundary)
- System seed / bootstrap code
- Database migration scripts
- Tests (direct ORM construction or these writers)

FORBIDDEN CALLERS
-----------------
- Public memory API routes  (memory/api.py)      → must create Proposals instead
- Agent tools                                     → must go through Proposal workflow
- Runtime adapters  (runtimes/)                  → no direct active-memory writes
- Normal run execution paths                      → no direct active-memory writes
- LocalMemoryProvider write methods when exposed as public/agent-facing path

MemoryStore remains a low-level persistence helper but public and agent-facing
paths must not call MemoryStore.create / update / delete to mutate active Memory.
"""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import MemoryEntry, Policy


class MemoryInternalWriter:
    """Low-level writer for MemoryEntry rows.  Must only be called from allowed internal paths."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read helper (kept here so appliers don't import MemoryStore directly)
    # ------------------------------------------------------------------

    def get_active(self, memory_id: str, space_id: str) -> Optional[MemoryEntry]:
        """Return an active (non-deleted) MemoryEntry within space_id, or None."""
        from .store import MemoryStore

        mem = MemoryStore(self._db).get_for_space(space_id, memory_id)
        if mem is not None and mem.deleted_at is None:
            return mem
        return None

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def create(
        self,
        data: "MemoryCreate",
        *,
        acting_user_id: Optional[str] = None,
        created_by: Optional[str] = None,
        approved_by: Optional[str] = None,
        created_from_proposal_id: Optional[str] = None,
        root_memory_id: Optional[str] = None,
        supersedes_memory_id: Optional[str] = None,
        source_trust: Optional[str] = None,
        source_activity_id: Optional[str] = None,
    ) -> MemoryEntry:
        """Persist a new MemoryEntry and attach lineage fields when provided."""
        from .store import MemoryStore

        store = MemoryStore(self._db)
        mem = store.create(
            data,
            acting_user_id=acting_user_id,
            created_by=created_by,
            approved_by=approved_by,
        )

        extras: dict[str, str | None] = {}
        if created_from_proposal_id is not None:
            extras["created_from_proposal_id"] = created_from_proposal_id
        if root_memory_id is not None:
            extras["root_memory_id"] = root_memory_id
        if supersedes_memory_id is not None:
            extras["supersedes_memory_id"] = supersedes_memory_id
        if source_trust is not None:
            extras["source_trust"] = source_trust
        if source_activity_id is not None:
            extras["source_activity_id"] = source_activity_id

        if extras:
            for attr, val in extras.items():
                setattr(mem, attr, val)
            self._db.commit()
            self._db.refresh(mem)

        return mem

    def mark_status(self, memory_id: str, space_id: str, new_status: str) -> Optional[MemoryEntry]:
        """Set status on an existing non-deleted MemoryEntry (e.g. 'superseded', 'archived')."""
        mem = self.get_active(memory_id, space_id)
        if mem is None:
            return None
        mem.status = new_status
        mem.updated_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(mem)
        return mem


class PolicyInternalWriter:
    """Low-level writer for Policy rows.  Must only be called from allowed internal paths."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        space_id: str,
        name: str,
        domain: str,
        policy_key: Optional[str] = None,
        policy_version: int = 1,
        status: str = "active",
        enforcement_mode: Optional[str] = None,
        priority: int = 0,
        rule_json: Optional[dict] = None,
        applies_to_json: Optional[dict] = None,
        policy_json: Optional[dict] = None,
        supersedes_policy_id: Optional[str] = None,
        created_from_proposal_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Policy:
        """Persist a new Policy row with versioning fields."""
        import uuid

        row = Policy(
            id=str(uuid.uuid4()),
            space_id=space_id,
            name=name,
            domain=domain,
            policy_json=dict(policy_json or rule_json or {}),
            enabled=enabled,
            policy_key=policy_key,
            policy_version=policy_version,
            status=status,
            enforcement_mode=enforcement_mode,
            priority=priority,
            rule_json=rule_json,
            applies_to_json=applies_to_json,
            supersedes_policy_id=supersedes_policy_id,
            created_from_proposal_id=created_from_proposal_id,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def mark_superseded(self, policy_id: str, space_id: str) -> Optional[Policy]:
        """Mark an existing Policy row status='superseded'.  Returns None if not found."""
        row = (
            self._db.query(Policy)
            .filter(Policy.id == policy_id, Policy.space_id == space_id)
            .first()
        )
        if row is None:
            return None
        row.status = "superseded"
        row.updated_at = datetime.now(UTC)
        self._db.commit()
        self._db.refresh(row)
        return row
