from __future__ import annotations
"""
MemoryStore — CRUD and query operations for long-term memories.
"""

from datetime import datetime, UTC
from typing import Optional
from ulid import ULID
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_

from ..models import Memory
from ..schemas import MemoryCreate, MemoryUpdate
from ..config import settings


def _new_id() -> str:
    return str(ULID())


class MemoryStore:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        data: MemoryCreate,
        created_by: str | None = None,
    ) -> Memory:
        mem = Memory(
            id=_new_id(),
            space_id=data.space_id or settings.default_space_id,
            owner_user_id=data.owner_user_id or settings.default_user_id,
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
            created_by=created_by or data.owner_user_id or settings.default_user_id,
            tags=data.tags,
            version=1,
        )
        self.db.add(mem)
        self.db.commit()
        self.db.refresh(mem)
        return mem

    def get(self, memory_id: str) -> Memory | None:
        return (
            self.db.query(Memory)
            .filter(Memory.id == memory_id, Memory.deleted_at.is_(None))
            .first()
        )

    def update(self, memory_id: str, data: MemoryUpdate) -> Memory | None:
        mem = self.get(memory_id)
        if not mem:
            return None
        for field, value in data.model_dump(exclude_none=True).items():
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

    def _base_query(self, space_id: str, user_id: str, workspace_id: str | None,
                    scope: str | None, namespace: str | None, memory_type: str | None, status: str):
        q = self.db.query(Memory).filter(Memory.space_id == space_id, Memory.deleted_at.is_(None))
        if status:
            q = q.filter(Memory.status == status)
        if scope:
            q = q.filter(Memory.scope == scope)
        if namespace:
            q = q.filter(Memory.namespace == namespace)
        if memory_type:
            q = q.filter(Memory.type == memory_type)
        visibility = [
            Memory.owner_user_id == user_id,
            and_(Memory.visibility == "space_shared", Memory.space_id == space_id),
        ]
        if workspace_id is not None:
            visibility.append(and_(Memory.visibility == "workspace_shared", Memory.workspace_id == workspace_id))
        return q.filter(or_(*visibility))

    def count(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        scope: str | None = None,
        namespace: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
    ) -> int:
        q = self.db.query(func.count(Memory.id)).filter(Memory.space_id == space_id, Memory.deleted_at.is_(None))
        if status:
            q = q.filter(Memory.status == status)
        if scope:
            q = q.filter(Memory.scope == scope)
        if namespace:
            q = q.filter(Memory.namespace == namespace)
        if memory_type:
            q = q.filter(Memory.type == memory_type)
        visibility = [
            Memory.owner_user_id == user_id,
            and_(Memory.visibility == "space_shared", Memory.space_id == space_id),
        ]
        if workspace_id is not None:
            visibility.append(and_(Memory.visibility == "workspace_shared", Memory.workspace_id == workspace_id))
        return q.filter(or_(*visibility)).scalar() or 0

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
    ) -> list[Memory]:
        return (
            self._base_query(space_id, user_id, workspace_id, scope, namespace, memory_type, status)
            .order_by(Memory.importance.desc(), Memory.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

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
    ) -> list[Memory]:
        """Simple keyword search. Future: replace with vector search."""
        q = self.db.query(Memory).filter(
            Memory.space_id == space_id,
            Memory.status == "active",
            Memory.deleted_at.is_(None),
            or_(
                Memory.title.ilike(f"%{query}%"),
                Memory.content.ilike(f"%{query}%"),
            ),
        )
        if scope:
            q = q.filter(Memory.scope == scope)
        if namespace:
            q = q.filter(Memory.namespace == namespace)
        if memory_type:
            q = q.filter(Memory.type == memory_type)

        # Visibility filter — never leak across spaces
        q = q.filter(
            or_(
                Memory.owner_user_id == user_id,
                Memory.visibility == "space_shared",
            )
        )
        return (
            q.order_by(Memory.importance.desc(), Memory.confidence.desc())
            .limit(limit)
            .all()
        )

    def get_by_scope(
        self,
        space_id: str,
        user_id: str,
        scope: str,
        workspace_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        return self.list(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            scope=scope,
            memory_type=memory_type,
            limit=limit,
        )
