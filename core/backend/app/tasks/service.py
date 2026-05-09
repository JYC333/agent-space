from __future__ import annotations
"""
TaskService — create and manage tasks (units of agent work).
"""

from datetime import datetime, UTC
from ulid import ULID
from sqlalchemy.orm import Session

from ..models import Task
from ..schemas import TaskCreate
from ..config import settings


def _new_id() -> str:
    return str(ULID())


class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: TaskCreate) -> Task:
        task = Task(
            id=_new_id(),
            space_id=data.space_id or settings.default_space_id,
            user_id=data.user_id or settings.default_user_id,
            workspace_id=data.workspace_id,
            session_id=data.session_id,
            title=data.title,
            description=data.description,
            capability_id=data.capability_id,
            status="pending",
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get(self, task_id: str) -> Task | None:
        return (
            self.db.query(Task)
            .filter(Task.id == task_id, Task.deleted_at.is_(None))
            .first()
        )

    def count(self, space_id: str, user_id: str, status: str | None = None) -> int:
        from sqlalchemy import func as _func
        q = self.db.query(_func.count(Task.id)).filter(
            Task.space_id == space_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        if status:
            q = q.filter(Task.status == status)
        return q.scalar() or 0

    def list(
        self,
        space_id: str,
        user_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        q = self.db.query(Task).filter(
            Task.space_id == space_id,
            Task.user_id == user_id,
            Task.deleted_at.is_(None),
        )
        if status:
            q = q.filter(Task.status == status)
        return q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()

    def update_status(
        self,
        task_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> Task | None:
        task = self.get(task_id)
        if not task:
            return None
        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        task.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(task)
        return task
