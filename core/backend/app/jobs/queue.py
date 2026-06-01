"""Durable job queue.

``PostgresQueueService`` is the queue implementation. It uses
``SELECT … FOR UPDATE SKIP LOCKED`` for safe concurrent claim. ``QueueService``
is the internal interface that queue consumers depend on.
"""
from __future__ import annotations
import uuid

import logging
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Callable


log = logging.getLogger(__name__)

_queue_service: "QueueService | None" = None


def get_queue() -> "QueueService":
    if _queue_service is None:
        raise RuntimeError("QueueService not initialised — call init_queue() first")
    return _queue_service


def init_queue(q: "QueueService") -> None:
    global _queue_service
    _queue_service = q


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class QueueService(ABC):
    """Internal queue interface that queue consumers depend on.

    Implemented by ``PostgresQueueService``.
    """

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
    async def start_job(self, job_id: str, worker_id: str | None = None) -> None: ...

    @abstractmethod
    async def complete_job(
        self, job_id: str, result: dict | None = None, worker_id: str | None = None
    ) -> None: ...

    @abstractmethod
    async def fail_job(self, job_id: str, error: str, worker_id: str | None = None) -> None: ...

    @abstractmethod
    async def cancel_job(self, job_id: str, worker_id: str | None = None) -> None: ...

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
    async def touch_heartbeat(self, job_id: str, worker_id: str | None = None) -> None:
        """Update heartbeat_at to now so reclaim logic treats this job as alive."""
        ...

    @abstractmethod
    async def reclaim_stuck_jobs(self, stuck_after_seconds: int = 600) -> int:
        """Recover claimed/running jobs that haven't progressed (e.g. after a crash).

        Uses COALESCE(heartbeat_at, updated_at) so a job that is actively
        sending heartbeats is never considered stuck, even if updated_at is old.
        """
        ...


# ---------------------------------------------------------------------------
# Database-backed implementation
# ---------------------------------------------------------------------------

class PostgresQueueService(QueueService):
    """
    PostgreSQL-backed queue using row-level locking (SELECT ... FOR UPDATE SKIP LOCKED).

    Claim atomicity is guaranteed by PostgreSQL row-level locking: concurrent workers
    each attempt to lock a pending job row; only one succeeds per row, and SKIP LOCKED
    ensures others immediately move on to the next available row rather than blocking.
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
    # claim_next — PostgreSQL SELECT ... FOR UPDATE SKIP LOCKED
    # ------------------------------------------------------------------

    async def claim_next(self, worker_id, job_types=None):
        return await self._run_in_thread(self._claim_next_sync, worker_id, job_types)

    def _claim_next_sync(self, worker_id: str, job_types: list[str] | None) -> "Job | None":
        from sqlalchemy import text
        from ..models import Job
        db = self._db_factory()
        try:
            now = datetime.now(UTC)
            params: dict = {"worker_id": worker_id, "now": now}

            type_filter = ""
            if job_types:
                placeholders = ", ".join(f":jt{i}" for i in range(len(job_types)))
                type_filter = f"AND job_type IN ({placeholders})"
                for i, t in enumerate(job_types):
                    params[f"jt{i}"] = t

            # SELECT ... FOR UPDATE SKIP LOCKED atomically claims one pending job.
            # attempts is incremented here so a crash between claim and start still
            # consumes an attempt; start_job only transitions claimed → running.
            # heartbeat_at is reset to NULL: no heartbeat has been sent for this
            # attempt yet, so any stale value from a prior attempt is cleared.
            # Liveness until start_job uses COALESCE(heartbeat_at, updated_at).
            result = db.execute(text(f"""
                UPDATE jobs
                SET status       = 'claimed',
                    claimed_by   = :worker_id,
                    claimed_at   = :now,
                    heartbeat_at = NULL,
                    attempts     = attempts + 1,
                    updated_at   = :now
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE  status       = 'pending'
                      AND  scheduled_at <= :now
                      AND  attempts     < max_attempts
                      {type_filter}
                    ORDER BY priority DESC, scheduled_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id
            """), params)

            row = result.fetchone()
            db.commit()

            if not row:
                return None
            return db.query(Job).filter(Job.id == row[0]).first()
        except Exception:
            log.exception("claim_next: database error — rolling back and re-raising")
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # start_job
    # ------------------------------------------------------------------

    async def start_job(self, job_id: str, worker_id: str | None = None) -> None:
        await self._run_in_thread(self._start_job_sync, job_id, worker_id)

    @staticmethod
    def _owns(job, worker_id: str | None) -> bool:
        """Ownership gate for claimed/running transitions.

        When a ``worker_id`` is supplied, only the worker that claimed the job
        (``job.claimed_by``) may transition it. ``worker_id=None`` is reserved for
        operator/system actions (e.g. an API cancel) that intentionally bypass the
        worker-ownership check.
        """
        return worker_id is None or job.claimed_by == worker_id

    def _start_job_sync(self, job_id: str, worker_id: str | None = None) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            # Only transition claimed → running. Non-claimed jobs (completed, failed,
            # cancelled, or already running) are ignored so duplicate start_job calls
            # are safe and terminal jobs are never reopened. attempts is not touched
            # here — it is consumed at claim time. Only the claiming worker may start
            # the job: a non-owner worker is a no-op.
            if job and job.status == "claimed" and self._owns(job, worker_id):
                now = datetime.now(UTC)
                job.status = "running"
                job.started_at = now
                job.heartbeat_at = now
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # complete_job
    # ------------------------------------------------------------------

    async def complete_job(
        self, job_id: str, result: dict | None = None, worker_id: str | None = None
    ) -> None:
        await self._run_in_thread(self._complete_job_sync, job_id, result, worker_id)

    def _complete_job_sync(
        self, job_id: str, result: dict | None, worker_id: str | None = None
    ) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            # Only the claiming worker may complete a claimed/running job. Terminal
            # jobs (completed, failed, cancelled) stay terminal; a non-owner worker
            # is a no-op.
            if job and job.status in ("claimed", "running") and self._owns(job, worker_id):
                job.status = "completed"
                job.result = result
                job.completed_at = datetime.now(UTC)
                job.heartbeat_at = None
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # fail_job — auto-retry if attempts < max_attempts
    # ------------------------------------------------------------------

    async def fail_job(self, job_id: str, error: str, worker_id: str | None = None) -> None:
        await self._run_in_thread(self._fail_job_sync, job_id, error, worker_id)

    def _fail_job_sync(self, job_id: str, error: str, worker_id: str | None = None) -> None:
        from ..models import Job
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            # Only the claiming worker may fail/retry a claimed/running job. Terminal
            # jobs (completed, failed, cancelled) stay terminal; a non-owner worker
            # is a no-op.
            if not job or job.status not in ("claimed", "running") or not self._owns(job, worker_id):
                return
            job.error = error
            job.heartbeat_at = None
            job.completed_at = datetime.now(UTC)
            # Retry decision uses attempts incremented at claim time.
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

    async def cancel_job(self, job_id: str, worker_id: str | None = None) -> None:
        await self._run_in_thread(self._cancel_job_sync, job_id, worker_id)

    def _cancel_job_sync(self, job_id: str, worker_id: str | None = None) -> None:
        from ..models import Job, Run
        db = self._db_factory()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            # Allowed source states: pending, claimed, running. Terminal jobs
            # (completed, failed, cancelled) stay terminal. A worker that later
            # calls complete_job/fail_job on this now-cancelled job is a no-op.
            # When a worker_id is supplied, only the claiming worker may cancel a
            # claimed/running job; operator/system cancels pass worker_id=None.
            if not job or job.status not in ("pending", "claimed", "running"):
                return
            if not self._owns(job, worker_id):
                return
            job.status = "cancelled"
            job.heartbeat_at = None
            # Cancel the linked Run when this is an agent_run job with a run_id payload.
            # Only cancel non-terminal runs; leave succeeded/failed/cancelled/etc. untouched.
            if job.job_type == "agent_run":
                payload = job.payload or {}
                run_id = payload.get("run_id")
                if run_id:
                    run = db.query(Run).filter(Run.id == run_id).first()
                    if run and run.status not in (
                        "succeeded", "failed", "degraded", "cancelled", "waiting_for_review"
                    ):
                        now = datetime.now(UTC)
                        run.status = "cancelled"
                        run.ended_at = now
                        run.updated_at = now
                        db.add(run)
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
    # touch_heartbeat — called periodically by the worker while handler runs
    # ------------------------------------------------------------------

    async def touch_heartbeat(self, job_id: str, worker_id: str | None = None) -> None:
        await self._run_in_thread(self._touch_heartbeat_sync, job_id, worker_id)

    def _touch_heartbeat_sync(self, job_id: str, worker_id: str | None = None) -> None:
        from sqlalchemy import text
        db = self._db_factory()
        try:
            # Only claimed/running jobs have a live heartbeat. Terminal jobs
            # (completed, failed, cancelled) are never touched. When a worker_id is
            # supplied, only the claiming worker (claimed_by) may heartbeat the job.
            db.execute(
                text(
                    "UPDATE jobs SET heartbeat_at = :now "
                    "WHERE id = :id AND status IN ('claimed', 'running') "
                    "AND (CAST(:worker_id AS text) IS NULL OR claimed_by = :worker_id)"
                ),
                {"now": datetime.now(UTC), "id": job_id, "worker_id": worker_id},
            )
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # reclaim_stuck_jobs
    # ------------------------------------------------------------------

    async def reclaim_stuck_jobs(self, stuck_after_seconds: int = 600) -> int:
        return await self._run_in_thread(self._reclaim_stuck_sync, stuck_after_seconds)

    def _record_reclaim_warning_events(self, db, job_ids: list[str], now: datetime) -> None:
        from ..models import JobEvent

        message = "orphan run execution lock cleanup failed during stuck-job reclaim"
        for job_id in sorted(set(job_ids)):
            db.add(
                JobEvent(
                    id=_new_id(),
                    job_id=job_id,
                    event_type="warning",
                    message=message,
                    data={
                        "operation": "reclaim_stuck_jobs",
                        "diagnostic": "orphan_run_execution_lock_cleanup_failed",
                    },
                    created_at=now,
                )
            )
        db.commit()

    def _delete_orphan_run_execution_lock(self, db, job_id: str, run_id: str) -> None:
        from sqlalchemy import text

        db.execute(text("""
            DELETE FROM run_execution_locks
            WHERE run_id = :run_id
              AND (job_id = :job_id OR job_id IS NULL)
        """), {"run_id": run_id, "job_id": job_id})

    def _reclaim_stuck_sync(self, stuck_after_seconds: int) -> int:
        import json as _json
        from sqlalchemy import text
        from datetime import timedelta
        db = self._db_factory()
        try:
            now = datetime.now(UTC)
            cutoff = now - timedelta(seconds=stuck_after_seconds)

            # Phase 1: clean up orphaned run_execution_locks for stuck agent_run jobs.
            stuck_run_jobs = db.execute(text("""
                SELECT id, payload_json FROM jobs
                WHERE status IN ('claimed', 'running')
                  AND job_type = 'agent_run'
                  AND COALESCE(heartbeat_at, updated_at) < :cutoff
            """), {"cutoff": cutoff}).fetchall()

            cleanup_targets: list[tuple[str, str]] = []
            for row in stuck_run_jobs:
                job_id, payload_raw = row[0], row[1]
                try:
                    payload = (
                        _json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw or {})
                    )
                except Exception:
                    continue
                run_id = payload.get("run_id")
                if run_id:
                    cleanup_targets.append((job_id, run_id))

            try:
                for job_id, run_id in cleanup_targets:
                    self._delete_orphan_run_execution_lock(db, job_id, run_id)
            except Exception:
                db.rollback()
                if cleanup_targets:
                    self._record_reclaim_warning_events(
                        db,
                        [job_id for job_id, _run_id in cleanup_targets],
                        now,
                    )
                log.warning(
                    "Orphan lock cleanup failed during reclaim_stuck_jobs — continuing",
                    exc_info=True,
                )

            # Phase 2: return retryable stuck jobs to pending and fail exhausted ones.
            # Capture the run_ids of the *exhausted* agent_run jobs first (before the
            # failing UPDATE changes their status) so their linked non-terminal Runs
            # can be moved to a terminal state once the job itself becomes failed.
            exhausted_run_rows = db.execute(text("""
                SELECT payload_json FROM jobs
                WHERE status IN ('claimed', 'running')
                  AND job_type = 'agent_run'
                  AND COALESCE(heartbeat_at, updated_at) < :cutoff
                  AND attempts >= max_attempts
            """), {"cutoff": cutoff}).fetchall()
            exhausted_run_ids: list[str] = []
            for row in exhausted_run_rows:
                payload_raw = row[0]
                try:
                    payload = (
                        _json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw or {})
                    )
                except Exception:
                    continue
                run_id = payload.get("run_id")
                if run_id:
                    exhausted_run_ids.append(run_id)

            # COALESCE(heartbeat_at, updated_at): active heartbeat jobs are never reclaimed.
            pending_result = db.execute(text("""
                UPDATE jobs
                SET status       = 'pending',
                    claimed_by   = NULL,
                    claimed_at   = NULL,
                    started_at   = NULL,
                    heartbeat_at = NULL,
                    updated_at   = :now
                WHERE status IN ('claimed', 'running')
                  AND COALESCE(heartbeat_at, updated_at) < :cutoff
                  AND attempts < max_attempts
            """), {"now": now, "cutoff": cutoff})
            failed_result = db.execute(text("""
                UPDATE jobs
                SET status       = 'failed',
                    claimed_by   = NULL,
                    claimed_at   = NULL,
                    heartbeat_at = NULL,
                    completed_at = :now,
                    error        = :error,
                    updated_at   = :now
                WHERE status IN ('claimed', 'running')
                  AND COALESCE(heartbeat_at, updated_at) < :cutoff
                  AND attempts >= max_attempts
            """), {
                "now": now,
                "cutoff": cutoff,
                "error": "job stuck and retry attempts exhausted",
            })

            # Phase 3: move linked non-terminal Runs to a terminal state for the
            # exhausted agent_run jobs just failed above. A Run left "running"/
            # "queued" after its backing job is permanently dead would otherwise
            # never reach a terminal state. Retryable jobs (returned to pending)
            # intentionally leave their Run untouched so the retry can proceed.
            if exhausted_run_ids:
                from ..models import Run

                _terminal_run_states = (
                    "succeeded", "failed", "degraded", "cancelled", "waiting_for_review",
                )
                for run_id in dict.fromkeys(exhausted_run_ids):
                    run = db.query(Run).filter(Run.id == run_id).first()
                    if run and run.status not in _terminal_run_states:
                        run.status = "failed"
                        run.ended_at = now
                        run.updated_at = now
                        run.error_message = (
                            "run abandoned: backing job stuck and retry attempts exhausted"
                        )
                        db.add(run)

            db.commit()
            n = (pending_result.rowcount or 0) + (failed_result.rowcount or 0)
            if n:
                log.warning("Recovered %d stuck job(s) (stuck_after=%ds)", n, stuck_after_seconds)
            return n
        except Exception:
            # Never hide DB errors as "nothing to reclaim" — roll back and re-raise.
            log.exception("reclaim_stuck_jobs: database error — rolling back and re-raising")
            db.rollback()
            raise
        finally:
            db.close()
