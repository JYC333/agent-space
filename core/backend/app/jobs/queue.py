from __future__ import annotations
"""
QueueService — replaceable durable job queue abstraction.

DatabaseQueueService is the default backend (SQLite/SQLAlchemy).
Swap for a Redis or AMQP implementation without changing any caller.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Callable

from ulid import ULID

log = logging.getLogger(__name__)

_queue_service: "QueueService | None" = None


def _dt(dt: datetime) -> str:
    """Serialize datetime for raw SQLite text() parameters (matches SQLAlchemy storage format)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(sep=" ")


def get_queue() -> "QueueService":
    if _queue_service is None:
        raise RuntimeError("QueueService not initialised — call init_queue() first")
    return _queue_service


def init_queue(q: "QueueService") -> None:
    global _queue_service
    _queue_service = q


def _new_id() -> str:
    return str(ULID())


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class QueueService(ABC):
    """All queue backends must implement this interface."""

    @abstractmethod
    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        *,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        scheduled_at: datetime | None = None,
    ) -> "Job": ...

    @abstractmethod
    async def claim_next(
        self,
        worker_id: str,
        job_types: list[str] | None = None,
    ) -> "Job | None": ...

    @abstractmethod
    async def start_job(self, job_id: str) -> None: ...

    @abstractmethod
    async def complete_job(self, job_id: str, result: dict | None = None) -> None: ...

    @abstractmethod
    async def fail_job(self, job_id: str, error: str) -> None: ...

    @abstractmethod
    async def cancel_job(self, job_id: str) -> None: ...

    @abstractmethod
    async def append_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        data: dict | None = None,
    ) -> None: ...

    @abstractmethod
    async def get_job(self, job_id: str) -> "Job | None": ...

    @abstractmethod
    async def list_jobs(
        self,
        space_id: str,
        user_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> "list[Job]": ...

    @abstractmethod
    async def count_jobs(
        self,
        space_id: str,
        user_id: str | None = None,
        status: str | None = None,
    ) -> int: ...

    @abstractmethod
    async def get_events(self, job_id: str) -> "list[JobEvent]": ...

    @abstractmethod
    async def reclaim_stuck_jobs(self, stuck_after_seconds: int = 600) -> int:
        """Reset claimed/running jobs that haven't progressed (e.g. after a crash)."""
        ...


# ---------------------------------------------------------------------------
# Database-backed implementation
# ---------------------------------------------------------------------------

class DatabaseQueueService(QueueService):
    """
    SQLite/SQLAlchemy queue backend.

    Claim atomicity relies on SQLite's single-writer guarantee in WAL mode plus
    an UPDATE … WHERE id = (SELECT id … LIMIT 1) RETURNING id query that is
    processed as a single statement. Safe for a multi-threaded single-process
    deployment; add row-level locking when migrating to PostgreSQL.
    """

    def __init__(self, db_factory: Callable):
        self._db_factory = db_factory

    # ------------------------------------------------------------------
    # Helpers — sync implementations run in a thread-pool executor
    # ------------------------------------------------------------------

    def _run_in_thread(self, fn, *args):
        import asyncio
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, fn, *args)

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        job_type,
        payload,
        *,
        space_id,
        user_id,
        workspace_id=None,
        agent_id=None,
        priority=0,
        max_attempts=3,
        scheduled_at=None,
    ):
        return await self._run_in_thread(
            self._enqueue_sync,
            job_type, payload, space_id, user_id,
            workspace_id, agent_id, priority, max_attempts, scheduled_at,
        )

    def _enqueue_sync(self, job_type, payload, space_id, user_id,
                      workspace_id, agent_id, priority, max_attempts, scheduled_at):
        from ..models import Job
        db = self._db_factory()
        try:
            job = Job(
                id=_new_id(),
                space_id=space_id,
                user_id=user_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                job_type=job_type,
                status="pending",
                priority=priority,
                payload=payload,
                attempts=0,
                max_attempts=max_attempts,
                scheduled_at=scheduled_at or datetime.now(UTC),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        finally:
            db.close()

    # ------------------------------------------------------------------
    # claim_next — atomic UPDATE via subquery + RETURNING
    # ------------------------------------------------------------------

    async def claim_next(self, worker_id, job_types=None):
        return await self._run_in_thread(self._claim_next_sync, worker_id, job_types)

    def _claim_next_sync(self, worker_id: str, job_types: list[str] | None) -> "Job | None":
        from sqlalchemy import text
        from ..models import Job
        db = self._db_factory()
        try:
            now = _dt(datetime.now(UTC))
            params: dict = {"worker_id": worker_id, "now": now}

            type_clause = ""
            if job_types:
                names = [f":jt{i}" for i in range(len(job_types))]
                type_clause = f"AND job_type IN ({', '.join(names)})"
                for i, t in enumerate(job_types):
                    params[f"jt{i}"] = t

            result = db.execute(text(f"""
                UPDATE jobs
                SET status     = 'claimed',
                    claimed_by = :worker_id,
                    claimed_at = :now,
                    updated_at = :now
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE  status       = 'pending'
                      AND  scheduled_at <= :now
                      AND  attempts     < max_attempts
                      {type_clause}
                    ORDER BY priority DESC, scheduled_at ASC
                    LIMIT 1
                )
                RETURNING id
            """), params)

            # Fetch BEFORE commit — cursor is invalidated after commit
            row = result.fetchone()
            db.commit()

            if not row:
                return None
            return db.query(Job).filter(Job.id == row[0]).first()
        except Exception:
            db.rollback()
            return None
        finally:
            db.close()

    # ------------------------------------------------------------------
    # start_job
    # ------------------------------------------------------------------

    async def start_job(self, job_id: str) -> None:
        await self._run_in_thread(self._start_job_sync, job_id)

    def _start_job_sync(self, job_id: str) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "running"
                job.attempts = (job.attempts or 0) + 1
                job.started_at = datetime.now(UTC)
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # complete_job
    # ------------------------------------------------------------------

    async def complete_job(self, job_id: str, result: dict | None = None) -> None:
        await self._run_in_thread(self._complete_job_sync, job_id, result)

    def _complete_job_sync(self, job_id: str, result: dict | None) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "completed"
                job.result = result
                job.completed_at = datetime.now(UTC)
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # fail_job — auto-retry if attempts < max_attempts
    # ------------------------------------------------------------------

    async def fail_job(self, job_id: str, error: str) -> None:
        await self._run_in_thread(self._fail_job_sync, job_id, error)

    def _fail_job_sync(self, job_id: str, error: str) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                return
            job.error = error
            job.completed_at = datetime.now(UTC)
            if job.attempts < job.max_attempts:
                # Back to pending for retry
                job.status = "pending"
                job.claimed_by = None
                job.claimed_at = None
                job.started_at = None
                job.completed_at = None
            else:
                job.status = "failed"
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # cancel_job
    # ------------------------------------------------------------------

    async def cancel_job(self, job_id: str) -> None:
        await self._run_in_thread(self._cancel_job_sync, job_id)

    def _cancel_job_sync(self, job_id: str) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status in ("pending", "claimed"):
                job.status = "cancelled"
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # append_event
    # ------------------------------------------------------------------

    async def append_event(self, job_id: str, event_type: str, message: str, data: dict | None = None) -> None:
        await self._run_in_thread(self._append_event_sync, job_id, event_type, message, data)

    def _append_event_sync(self, job_id: str, event_type: str, message: str, data: dict | None) -> None:
        from ..models import JobEvent
        db = self._db_factory()
        try:
            event = JobEvent(
                id=_new_id(),
                job_id=job_id,
                event_type=event_type,
                message=message,
                data=data,
            )
            db.add(event)
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # get_job / list_jobs / count_jobs / get_events
    # ------------------------------------------------------------------

    async def get_job(self, job_id: str) -> "Job | None":
        return await self._run_in_thread(self._get_job_sync, job_id)

    def _get_job_sync(self, job_id: str):
        from ..models import Job
        db = self._db_factory()
        try:
            return db.query(Job).filter(Job.id == job_id).first()
        finally:
            db.close()

    async def list_jobs(self, space_id, user_id=None, status=None, job_type=None, limit=50, offset=0):
        return await self._run_in_thread(
            self._list_jobs_sync, space_id, user_id, status, job_type, limit, offset
        )

    def _list_jobs_sync(self, space_id, user_id, status, job_type, limit, offset):
        from ..models import Job
        db = self._db_factory()
        try:
            q = db.query(Job).filter(Job.space_id == space_id)
            if user_id:
                q = q.filter(Job.user_id == user_id)
            if status:
                q = q.filter(Job.status == status)
            if job_type:
                q = q.filter(Job.job_type == job_type)
            return q.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()
        finally:
            db.close()

    async def count_jobs(self, space_id, user_id=None, status=None) -> int:
        return await self._run_in_thread(self._count_jobs_sync, space_id, user_id, status)

    def _count_jobs_sync(self, space_id, user_id, status) -> int:
        from sqlalchemy import func
        from ..models import Job
        db = self._db_factory()
        try:
            q = db.query(func.count(Job.id)).filter(Job.space_id == space_id)
            if user_id:
                q = q.filter(Job.user_id == user_id)
            if status:
                q = q.filter(Job.status == status)
            return q.scalar() or 0
        finally:
            db.close()

    async def get_events(self, job_id: str) -> "list[JobEvent]":
        return await self._run_in_thread(self._get_events_sync, job_id)

    def _get_events_sync(self, job_id: str):
        from ..models import JobEvent
        db = self._db_factory()
        try:
            return (
                db.query(JobEvent)
                .filter(JobEvent.job_id == job_id)
                .order_by(JobEvent.created_at.asc())
                .all()
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # reclaim_stuck_jobs
    # ------------------------------------------------------------------

    async def reclaim_stuck_jobs(self, stuck_after_seconds: int = 600) -> int:
        return await self._run_in_thread(self._reclaim_stuck_sync, stuck_after_seconds)

    def _reclaim_stuck_sync(self, stuck_after_seconds: int) -> int:
        from sqlalchemy import text
        db = self._db_factory()
        try:
            from datetime import timedelta
            cutoff = _dt(datetime.now(UTC) - timedelta(seconds=stuck_after_seconds))
            result = db.execute(text("""
                UPDATE jobs
                SET status     = 'pending',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    started_at = NULL,
                    updated_at = :now
                WHERE status IN ('claimed', 'running')
                  AND updated_at < :cutoff
                  AND attempts   < max_attempts
            """), {"now": _dt(datetime.now(UTC)), "cutoff": cutoff})
            db.commit()
            n = result.rowcount
            if n:
                log.warning("Reclaimed %d stuck job(s) (stuck_after=%ds)", n, stuck_after_seconds)
            return n
        finally:
            db.close()
