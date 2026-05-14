from __future__ import annotations
"""
MemoryProvider — abstract interface for memory storage backends.

Only LocalMemoryProvider is enabled in the MVP.  The interface exists so
future providers (vector databases, remote services, etc.) can be swapped
in without changing callers.

Write governance
----------------
LocalMemoryProvider.create / update / delete are INTERNAL-ONLY methods.
They must NOT be called from:
  - Public API routes (memory/api.py)    → those create Proposals
  - Agent tools                          → must go through Proposal workflow
  - Runtime adapters (runtimes/)         → no direct active-memory writes
  - Normal run execution paths

Allowed callers of the write methods:
  - ProposalApplyService (accepted-proposal application)
  - System seed / bootstrap
  - Migration scripts
  - Tests that need to pre-populate memory state

Usage (reads — unchanged):
    provider = LocalMemoryProvider(db_session)
    memories = provider.list(space_id="personal", user_id="...", scope="user")
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models import MemoryEntry

_INTERNAL_WRITE_ALLOWED = True  # sentinel — future phases may gate this per caller


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class MemoryProvider(ABC):
    """
    Pluggable storage backend for memory entries.

    All methods operate within a single space_id boundary — cross-space
    access must be denied before calling any provider method.
    """

    @abstractmethod
    def get(self, memory_id: str, space_id: str) -> Optional[dict]:
        """Return a single memory by ID, or None if not found / not in space."""
        ...

    @abstractmethod
    def list(
        self,
        space_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        scope: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return memories matching the given filters, serialised as dicts."""
        ...

    @abstractmethod
    def search(
        self,
        space_id: str,
        query: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text / semantic search across content and titles."""
        ...

    @abstractmethod
    def create(self, space_id: str, data: dict) -> dict:
        """INTERNAL ONLY.  Persist a new memory entry. Returns the created record as a dict.

        Must not be called from public API routes or agent/runtime-facing paths.
        Use the Proposal workflow for public memory creation.
        """
        ...

    @abstractmethod
    def update(self, memory_id: str, space_id: str, updates: dict) -> dict:
        """INTERNAL ONLY.  Apply partial updates to an existing memory.

        Must not be called from public API routes or agent/runtime-facing paths.
        Use the Proposal workflow for public memory updates.
        """
        ...

    @abstractmethod
    def delete(self, memory_id: str, space_id: str) -> bool:
        """INTERNAL ONLY.  Soft-delete a memory.

        Must not be called from public API routes or agent/runtime-facing paths.
        Use the Proposal workflow for public memory archives.
        """
        ...

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable identifier used in logs and config, e.g. 'local', 'pgvector'."""
        ...


# ---------------------------------------------------------------------------
# LocalMemoryProvider — database-backed, the only enabled provider in MVP
# ---------------------------------------------------------------------------


def _row_to_dict(m: "MemoryEntry") -> dict:
    return {
        "id": m.id,
        "space_id": m.space_id,
        "subject_user_id": m.subject_user_id,
        "owner_user_id": m.owner_user_id,
        "workspace_id": m.workspace_id,
        "agent_id": m.agent_id,
        "capability_id": m.capability_id,
        "scope": m.scope,
        "namespace": m.namespace,
        "type": m.type,
        "title": m.title,
        "content": m.content,
        "status": m.status,
        "visibility": m.visibility,
        "sensitivity_level": m.sensitivity_level,
        "selected_user_ids": m.selected_user_ids,
        "last_confirmed_at": m.last_confirmed_at.isoformat() if m.last_confirmed_at else None,
        "confidence": m.confidence,
        "importance": m.importance,
        "source_id": m.source_id,
        "source_activity_id": m.source_activity_id,
        "source_artifact_id": m.source_artifact_id,
        "created_by": m.created_by,
        "approved_by": m.approved_by,
        "tags": m.tags,
        "access_count": m.access_count,
        "last_accessed_at": m.last_accessed_at.isoformat() if m.last_accessed_at else None,
        "fitness_score": m.fitness_score,
        "version": m.version,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
    }


class LocalMemoryProvider(MemoryProvider):
    """
    SQLAlchemy-backed memory provider.

    Wraps MemoryStore so callers can depend on the abstract interface without
    importing the concrete store directly.

    Write methods (create / update / delete) are INTERNAL-ONLY — see module
    docstring for the full list of allowed and forbidden callers.
    """

    def __init__(self, db: "Session") -> None:
        from .store import MemoryStore

        self._db = db
        self._store = MemoryStore(db)

    @property
    def provider_id(self) -> str:
        return "local"

    def get(self, memory_id: str, space_id: str) -> Optional[dict]:
        m = self._store.get_for_space(space_id, memory_id)
        if not m:
            return None
        return _row_to_dict(m)

    def list(
        self,
        space_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        scope: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if not user_id:
            return []
        rows = self._store.list(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            scope=scope,
            memory_type=memory_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [_row_to_dict(m) for m in rows]

    def search(
        self,
        space_id: str,
        query: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if not user_id:
            return []
        rows = self._store.search(
            query=query,
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
        )
        return [_row_to_dict(m) for m in rows]

    # ------------------------------------------------------------------
    # Write methods — INTERNAL ONLY
    # See module docstring for allowed callers.
    # ------------------------------------------------------------------

    def create(self, space_id: str, data: dict) -> dict:
        """INTERNAL ONLY.  Direct MemoryEntry creation — not for public or agent use."""
        from ..schemas import MemoryCreate

        payload = dict(data)
        payload.setdefault("space_id", space_id)
        acting = payload.pop("acting_user_id", None) or payload.pop("user_id", None)
        mc = MemoryCreate.model_validate(payload)
        m = self._store.create(mc, acting_user_id=acting)
        return _row_to_dict(m)

    def update(self, memory_id: str, space_id: str, updates: dict) -> dict:
        """INTERNAL ONLY.  Direct MemoryEntry mutation — not for public or agent use."""
        from ..schemas import MemoryUpdate

        m = self._store.get_for_space(space_id, memory_id)
        if not m:
            raise ValueError("memory not found")
        mu = MemoryUpdate.model_validate(updates)
        m2 = self._store.update(memory_id, mu, space_id=space_id)
        if not m2:
            raise ValueError("memory not found")
        return _row_to_dict(m2)

    def delete(self, memory_id: str, space_id: str) -> bool:
        """INTERNAL ONLY.  Direct soft-delete — not for public or agent use."""
        m = self._store.get_for_space(space_id, memory_id)
        if not m:
            return False
        return self._store.delete(memory_id, space_id=space_id)
