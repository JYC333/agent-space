from __future__ import annotations
"""
MemoryProvider — abstract interface for memory storage backends.

Only LocalMemoryProvider is enabled in the MVP. The interface exists so
future providers (vector databases, remote services, etc.) can be swapped
in without changing callers.

Usage:
    provider = LocalMemoryProvider(db_session)
    memories = provider.list(space_id="personal", scope="user")
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models import Memory


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
        """Persist a new memory entry. Returns the created record as a dict."""
        ...

    @abstractmethod
    def update(self, memory_id: str, space_id: str, updates: dict) -> dict:
        """Apply partial updates to an existing memory. Returns updated record."""
        ...

    @abstractmethod
    def delete(self, memory_id: str, space_id: str) -> bool:
        """Soft-delete a memory. Returns True if deleted, False if not found."""
        ...

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable identifier used in logs and config, e.g. 'local', 'pgvector'."""
        ...


# ---------------------------------------------------------------------------
# LocalMemoryProvider — database-backed, the only enabled provider in MVP
# ---------------------------------------------------------------------------

def _row_to_dict(m: "Memory") -> dict:
    return {
        "id": m.id,
        "space_id": m.space_id,
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
    """

    def __init__(self, db: "Session") -> None:
        from .store import MemoryStore
        self._db = db
        self._store = MemoryStore(db)

    @property
    def provider_id(self) -> str:
        return "local"

    def get(self, memory_id: str, space_id: str) -> Optional[dict]:
        m = self._store.get(self._db, memory_id, space_id)
        return _row_to_dict(m) if m else None

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
        rows = self._store.list(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
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
        rows = self._store.search(
            query=query,
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=limit,
        )
        return [_row_to_dict(m) for m in rows]

    def create(self, space_id: str, data: dict) -> dict:
        m = self._store.create(space_id=space_id, **data)
        return _row_to_dict(m)

    def update(self, memory_id: str, space_id: str, updates: dict) -> dict:
        m = self._store.update(memory_id, space_id, **updates)
        return _row_to_dict(m)

    def delete(self, memory_id: str, space_id: str) -> bool:
        return self._store.delete(memory_id, space_id)
