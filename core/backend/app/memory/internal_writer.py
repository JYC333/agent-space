from __future__ import annotations
"""
Internal-only write paths for MemoryEntry and Policy rows.

ALLOWED CALLERS
---------------
- ProposalApplyService (accepted-proposal application — the sole normal durable write boundary)
- System seed / bootstrap code (create_system_seed_memory only)
- Tests (direct ORM construction or create_system_seed_memory for seed rows)

FORBIDDEN CALLERS
-----------------
- Public memory API routes  (memory/api.py)   → must create Proposals instead
- Agent tools                                  → must go through Proposal workflow
- Runtime adapters  (runtimes/)               → no direct active-memory writes
- Normal run execution paths                   → no direct active-memory writes
- MemoryProvider / LocalMemoryProvider         → read-only; no write methods remain

Active MemoryEntry rows are written through exactly two paths:
  1. ProposalApplyService.apply()
     → MemoryInternalWriter.create_from_approved_proposal() / mark_status_from_approved_proposal()
  2. MemoryInternalWriter.create_system_seed_memory()  (bootstrap only)
"""

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import MemoryEntry, Policy, Proposal


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
    # Proposal-approved write paths (the sole normal product write boundary)
    # ------------------------------------------------------------------

    def create_from_approved_proposal(
        self,
        proposal: Proposal,
        data: "MemoryCreate",
        *,
        acting_user_id: Optional[str] = None,
        created_by: Optional[str] = None,
        approved_by: Optional[str] = None,
        root_memory_id: Optional[str] = None,
        supersedes_memory_id: Optional[str] = None,
        source_trust: Optional[str] = None,
        source_activity_id: Optional[str] = None,
    ) -> MemoryEntry:
        """Persist memory during ProposalApplyService after explicit proposal approval."""
        self._validate_proposal_apply_bypass(proposal, data)
        return self._persist(
            data,
            acting_user_id=acting_user_id,
            created_by=created_by,
            approved_by=approved_by,
            created_from_proposal_id=proposal.id,
            root_memory_id=root_memory_id,
            supersedes_memory_id=supersedes_memory_id,
            source_trust=source_trust,
            source_activity_id=source_activity_id,
            commit=False,
        )

    def mark_status_from_approved_proposal(
        self,
        proposal: Proposal,
        memory_id: str,
        new_status: str,
    ) -> Optional[MemoryEntry]:
        """Set memory status during ProposalApplyService after explicit proposal approval."""
        if proposal.proposal_type not in ("memory_update", "memory_archive"):
            raise PermissionError("approved proposal status bypass requires a memory update/archive proposal")
        if proposal.preview:
            raise PermissionError("preview proposals cannot bypass the proposal-approval boundary")
        if proposal.status != "pending":
            raise PermissionError("proposal apply bypass is only valid during pending proposal acceptance")
        db_row = (
            self._db.query(Proposal)
            .filter(Proposal.id == proposal.id, Proposal.space_id == proposal.space_id)
            .first()
        )
        if db_row is None or db_row is not proposal:
            raise PermissionError("proposal apply bypass requires a persisted proposal from this session")
        return self._mark_status_without_policy_check(
            memory_id, proposal.space_id, new_status, commit=False
        )

    # ------------------------------------------------------------------
    # Bootstrap / seed path (system use only — not for tests or product code)
    # ------------------------------------------------------------------

    def create_system_seed_memory(
        self,
        data: "MemoryCreate",
        *,
        created_by: str = "system_seed",
        commit: bool = True,
    ) -> MemoryEntry:
        """Persist a system-bootstrap MemoryEntry without proposal review.

        ONLY for bootstrap/seed code that runs before any space policies exist.
        Sets ``source_trust="internal_system"`` so seed rows are auditably distinct
        from proposal-created memory.

        Forbidden callers: public API routes, agent tools, runtime adapters, tests
        that verify product memory-creation behaviour.
        """
        return self._persist(
            data,
            created_by=created_by,
            source_trust="internal_system",
            commit=commit,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_proposal_apply_bypass(self, proposal: Proposal, data: "MemoryCreate") -> None:
        if proposal.proposal_type not in ("memory_create", "memory_update"):
            raise PermissionError("approved proposal memory write bypass requires a memory create/update proposal")
        if proposal.preview:
            raise PermissionError("preview proposals cannot bypass the proposal-approval boundary")
        if proposal.space_id != data.space_id:
            raise PermissionError("proposal space does not match memory write space")
        if proposal.status != "pending":
            raise PermissionError("proposal apply bypass is only valid during pending proposal acceptance")
        db_row = (
            self._db.query(Proposal)
            .filter(Proposal.id == proposal.id, Proposal.space_id == proposal.space_id)
            .first()
        )
        if db_row is None or db_row is not proposal:
            raise PermissionError("proposal apply bypass requires a persisted proposal from this session")

    def _persist(
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
        commit: bool = True,
    ) -> MemoryEntry:

        from .store import MemoryStore, _INTERNAL_WRITE_AUTHORITY

        store = MemoryStore(self._db)
        mem = store.create(
            data,
            acting_user_id=acting_user_id,
            created_by=created_by,
            approved_by=approved_by,
            commit=False,
            _write_authority=_INTERNAL_WRITE_AUTHORITY,
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
            self._db.flush()
        if commit:
            self._db.commit()
            self._db.refresh(mem)

        return mem

    def _mark_status_without_policy_check(
        self, memory_id: str, space_id: str, new_status: str, *, commit: bool = True
    ) -> Optional[MemoryEntry]:
        mem = self.get_active(memory_id, space_id)
        if mem is None:
            return None
        mem.status = new_status
        mem.updated_at = datetime.now(UTC)
        self._db.flush()
        if commit:
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
        commit: bool = True,
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
        self._db.flush()
        if commit:
            self._db.commit()
            self._db.refresh(row)
        return row

    def mark_superseded(
        self, policy_id: str, space_id: str, *, commit: bool = True
    ) -> Optional[Policy]:
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
        self._db.flush()
        if commit:
            self._db.commit()
            self._db.refresh(row)
        return row
