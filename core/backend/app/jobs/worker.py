from __future__ import annotations
"""
Background worker loop for the durable job queue.

Start it once at application startup (called from main.py lifespan):

    from app.jobs.worker import start_worker
    task = await start_worker(queue)          # returns asyncio.Task
    # on shutdown:
    task.cancel(); await task

The loop:
  1. Claims the next pending job from the queue.
  2. Dispatches it to a thread-pool executor (all handlers are sync).
  3. Writes job events and updates status on completion / failure.
  4. Respects a concurrency semaphore (default 4 parallel jobs).
  5. Sleeps POLL_INTERVAL seconds when the queue is empty.
  6. Resets stuck jobs (from previous crashes) every RECLAIM_INTERVAL seconds.
"""

import asyncio
import logging
from datetime import datetime, UTC

from ulid import ULID

from .queue import QueueService
from .handlers import get_handler

log = logging.getLogger(__name__)

POLL_INTERVAL: float = 2.0        # seconds between empty-queue polls
RECLAIM_INTERVAL: float = 120.0   # seconds between stuck-job reclaim sweeps
STUCK_AFTER: int = 600            # seconds since last heartbeat before reclaim
MAX_CONCURRENCY: int = 4          # max parallel jobs per worker
HEARTBEAT_INTERVAL: float = 60.0  # seconds between heartbeat updates while handler runs

# Stable ID for this worker instance (set at module import time)
WORKER_ID: str = str(ULID())


async def start_worker(queue: QueueService) -> asyncio.Task:
    """
    Start the background worker loop and return the asyncio.Task so the
    caller can cancel it cleanly on shutdown.
    """
    # Reset any orphaned jobs left over from a previous crash
    await queue.reclaim_stuck_jobs(STUCK_AFTER)
    # Recover runs left in "running" state by a previous crash.
    await asyncio.get_running_loop().run_in_executor(None, _recover_stale_runs)
    task = asyncio.create_task(_worker_loop(queue), name="job-worker")
    log.info("Job worker started (id=%s, concurrency=%d)", WORKER_ID, MAX_CONCURRENCY)
    return task


def _recover_stale_runs() -> None:
    """Recover runs stuck in 'running' status — called once at worker startup."""
    try:
        from sqlalchemy.orm import sessionmaker
        from ..db import engine as _engine
        Session = sessionmaker(bind=_engine)
        db = Session()
        try:
            from ..runs.run_service import RunService
            count = RunService(db).recover_stale_runs()
            if count:
                log.warning("Stale run recovery: %d run(s) marked failed at startup", count)
        finally:
            db.close()
    except Exception:
        log.exception("Stale run recovery failed at startup — continuing")


async def _worker_loop(queue: QueueService) -> None:
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    loop = asyncio.get_running_loop()
    last_reclaim = loop.time()

    while True:
        try:
            # Periodic stuck-job reclaim
            now = loop.time()
            if now - last_reclaim >= RECLAIM_INTERVAL:
                await queue.reclaim_stuck_jobs(STUCK_AFTER)
                last_reclaim = now

            # Acquire a concurrency slot before touching the DB
            await sem.acquire()

            job = await queue.claim_next(WORKER_ID)
            if job is None:
                sem.release()
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Run the job without blocking the loop
            asyncio.create_task(_run_job(job, queue, sem))

        except asyncio.CancelledError:
            log.info("Job worker shutting down")
            raise
        except Exception:
            log.exception("Unexpected error in worker loop — continuing")
            await asyncio.sleep(POLL_INTERVAL)


async def _heartbeat_loop(job_id: str, queue: QueueService, interval: float) -> None:
    """Send periodic heartbeats while a handler is running.

    Cancelled by _run_job when the handler completes.  Each heartbeat updates
    job.heartbeat_at so reclaim_stuck_jobs knows the job is still alive.
    Heartbeat failures are logged but never propagate to the handler.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            await queue.touch_heartbeat(job_id)
            log.debug("Heartbeat sent for job %s", job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Heartbeat failed for job %s — will retry next interval", job_id)


async def _run_job(job, queue: QueueService, sem: asyncio.Semaphore) -> None:
    """Execute one job, update its status, then release the concurrency slot."""
    async def _append_event_aux(event_type: str, message: str, data: dict | None = None) -> None:
        """Write auxiliary JobEvent rows without poisoning terminal job state."""
        try:
            await queue.append_event(job.id, event_type, message, data)
        except Exception:
            log.exception(
                "Auxiliary JobEvent write failed after job state update (job=%s event=%s)",
                job.id,
                event_type,
            )

    hb_task: asyncio.Task | None = None
    try:
        handler = get_handler(job.job_type)
        if handler is None:
            log.error("No handler registered for job type %r (job=%s)", job.job_type, job.id)
            await queue.fail_job(job.id, f"No handler for job type: {job.job_type!r}")
            await _append_event_aux("error", f"No handler registered for {job.job_type!r}")
            return

        await queue.start_job(job.id)
        await _append_event_aux(
            "status_change",
            f"Job started by worker {WORKER_ID} (attempt {job.attempts + 1}/{job.max_attempts})",
        )

        log.info("Executing job %s type=%s attempt=%d", job.id, job.job_type, job.attempts + 1)

        # Start a background heartbeat so reclaim_stuck_jobs does not evict
        # this job while the handler is legitimately running (e.g. long CLI runs).
        hb_task = asyncio.create_task(
            _heartbeat_loop(job.id, queue, HEARTBEAT_INTERVAL),
            name=f"heartbeat-{job.id}",
        )

        result = await asyncio.get_running_loop().run_in_executor(None, handler, job)

        await queue.complete_job(job.id, result if isinstance(result, dict) else None)
        await _append_event_aux("status_change", "Job completed successfully")
        log.info("Job %s completed", job.id)

    except asyncio.CancelledError:
        # Worker is shutting down; leave job in running state — will be reclaimed next start
        raise
    except Exception as exc:
        log.exception("Job %s (%s) raised an exception", job.id, job.job_type)
        await queue.fail_job(job.id, str(exc))
        await _append_event_aux("error", f"Job failed: {exc}")
    finally:
        # Always cancel the heartbeat task regardless of outcome.
        if hb_task is not None and not hb_task.done():
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
        sem.release()
