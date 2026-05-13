from __future__ import annotations
"""
MemoryStore — CRUD and query operations for long-term memories.

Read access is enforced via ``read_auth.can_read_memory`` on every list/search/get path.
"""

from datetime import datetime, UTC
from typing import Optional
from ulid import ULID
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..models import MemoryEntry
from ..schemas import MemoryCreate, MemoryUpdate
from ..config import settings
from .read_auth import can_read_memory
from .access_log import record_memory_access


def _new_id() -> str:
    return str(ULID())


class MemoryStore:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        data: MemoryCreate,
        *,
        acting_user_id: str | None = None,
        created_by: str | None = None,
        approved_by: str | None = None,
    ) -> MemoryEntry:
        owner_user_id = data.owner_user_id
        if data.visibility == "private" and owner_user_id is None:
            owner_user_id = acting_user_id
        if data.visibility == "private" and owner_user_id is None:
            raise ValueError("owner_user_id is required for private visibility (or provide acting_user_id)")

        if created_by is not None:
            audit = created_by
        else:
            audit = acting_user_id or settings.default_user_id

        mem = MemoryEntry(
            id=_new_id(),
            space_id=data.space_id or settings.default_space_id,
            subject_user_id=data.subject_user_id,
            owner_user_id=owner_user_id,
            sensitivity_level=data.sensitivity_level,
            selected_user_ids=data.selected_user_ids,
            last_confirmed_at=data.last_confirmed_at,
            workspace_id=data.workspace_id,
            scope=data.scope,
            namespace=data.namespace,
            type=data.type,
            title=data.title,
            content=data.content,
            status="active",
            visibility=data.visibility,
            confidence=data.confidence,
            importance=data.importance,
            source_id=data.source_id,
            source_proposal_id=data.source_proposal_id,
            created_by=audit,
            approved_by=approved_by,
            tags=data.tags,
            version=1,
        )
        self.db.add(mem)
        self.db.commit()
        self.db.refresh(mem)
        return mem

    def get(self, memory_id: str) -> MemoryEntry | None:
        return (
            self.db.query(MemoryEntry)
            .filter(MemoryEntry.id == memory_id, MemoryEntry.deleted_at.is_(None))
            .first()
        )

    def can_read_entry(
        self,
        mem: MemoryEntry,
        requesting_space_id: str,
        requesting_user_id: str,
        workspace_id: str | None = None,
        *,
        include_system_scope: bool = False,
        include_public_templates: bool = False,
    ) -> bool:
        return can_read_memory(
            mem,
            user_id=requesting_user_id,
            space_id=requesting_space_id,
            workspace_id=workspace_id,
            include_system_scope=include_system_scope,
            include_public_templates=include_public_templates,
        )

    def update(self, memory_id: str, data: MemoryUpdate) -> MemoryEntry | None:
        mem = self.get(memory_id)
        if not mem:
            return None
        payload = data.model_dump(exclude_none=True)
        for field, value in payload.items():
            if field == "scope":
                setattr(mem, "scope_type", value)
            elif field == "type":
                setattr(mem, "memory_type", value)
            else:
                setattr(mem, field, value)
        mem.version += 1
        mem.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(mem)
        return mem

    def delete(self, memory_id: str) -> bool:
        mem = self.get(memory_id)
        if not mem:
            return False
        mem.deleted_at = datetime.now(UTC)
        self.db.commit()
        return True

    def _filter_readable(
        self,
        rows: list[MemoryEntry],
        space_id: str,
        user_id: str,
        workspace_id: str | None,
        *,
        include_system_scope: bool,
        include_public_templates: bool = False,
    ) -> list[MemoryEntry]:
        return [
            m
            for m in rows
            if can_read_memory(
                m,
                user_id=user_id,
                space_id=space_id,
                workspace_id=workspace_id,
                include_system_scope=include_system_scope,
                include_public_templates=include_public_templates,
            )
        ]

    def _scoped_query(
        self,
        space_id: str,
        workspace_id: str | None,
        scope: str | None,
        namespace: str | None,
        memory_type: str | None,
        status: str,
    ):
        q = self.db.query(MemoryEntry).filter(MemoryEntry.space_id == space_id, MemoryEntry.deleted_at.is_(None))
        if status:
            q = q.filter(MemoryEntry.status == status)
        if scope:
            q = q.filter(MemoryEntry.scope == scope)
        if namespace:
            q = q.filter(MemoryEntry.namespace == namespace)
        if memory_type:
            q = q.filter(MemoryEntry.type == memory_type)
        return q

    def count(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        scope: str | None = None,
        namespace: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        *,
        include_system_scope: bool = False,
    ) -> int:
        q = self._scoped_query(space_id, workspace_id, scope, namespace, memory_type, status)
        return len(
            self._filter_readable(
                q.all(),
                space_id,
                user_id,
                workspace_id,
                include_system_scope=include_system_scope,
            )
        )

    def list(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        scope: str | None = None,
        namespace: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
        *,
        include_system_scope: bool = False,
    ) -> list[MemoryEntry]:
        q = self._scoped_query(space_id, workspace_id, scope, namespace, memory_type, status)
        rows = q.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).all()
        filtered = self._filter_readable(
            rows,
            space_id,
            user_id,
            workspace_id,
            include_system_scope=include_system_scope,
        )
        return filtered[offset : offset + limit]

    def search(
        self,
        query: str,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        scope: str | None = None,
        namespace: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        *,
        include_system_scope: bool = False,
    ) -> list[MemoryEntry]:
        """Simple keyword search. Future: replace with vector search."""
        q = self.db.query(MemoryEntry).filter(
            MemoryEntry.space_id == space_id,
            MemoryEntry.status == "active",
            MemoryEntry.deleted_at.is_(None),
            or_(
                MemoryEntry.title.ilike(f"%{query}%"),
                MemoryEntry.content.ilike(f"%{query}%"),
            ),
        )
        if scope:
            q = q.filter(MemoryEntry.scope == scope)
        if namespace:
            q = q.filter(MemoryEntry.namespace == namespace)
        if memory_type:
            q = q.filter(MemoryEntry.type == memory_type)

        rows = q.order_by(MemoryEntry.importance.desc(), MemoryEntry.confidence.desc()).all()
        filtered = self._filter_readable(
            rows,
            space_id,
            user_id,
            workspace_id,
            include_system_scope=include_system_scope,
        )
        return filtered[:limit]

    def get_by_scope(
        self,
        space_id: str,
        user_id: str,
        scope: str,
        workspace_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        include_system = scope == "system"
        return self.list(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            scope=scope,
            memory_type=memory_type,
            limit=limit,
            include_system_scope=include_system,
        )

    def log_explicit_read(
        self,
        memory: MemoryEntry,
        *,
        space_id: str,
        user_id: str,
        agent_id: str | None,
        run_id: str | None,
        access_type: str = "explicit_read",
        reason: str | None = None,
    ) -> None:
        record_memory_access(
            self.db,
            memory,
            space_id=space_id,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            access_type=access_type,
            reason=reason,
        )
        self.db.commit()

    def log_reads_batch(
        self,
        memories: list[MemoryEntry],
        *,
        space_id: str,
        user_id: str,
        agent_id: str | None,
        run_id: str | None,
        access_type: str,
        reason: str | None,
    ) -> None:
        for m in memories:
            record_memory_access(
                self.db,
                m,
                space_id=space_id,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                access_type=access_type,
                reason=reason,
            )
        self.db.commit()
