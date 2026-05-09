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

POLL_INTERVAL: float = 2.0      # seconds between empty-queue polls
RECLAIM_INTERVAL: float = 120.0  # seconds between stuck-job reclaim sweeps
STUCK_AFTER: int = 600           # seconds a job may sit in claimed/running before reclaim
MAX_CONCURRENCY: int = 4         # max parallel jobs per worker

# Stable ID for this worker instance (set at module import time)
WORKER_ID: str = str(ULID())


async def start_worker(queue: QueueService) -> asyncio.Task:
    """
    Start the background worker loop and return the asyncio.Task so the
    caller can cancel it cleanly on shutdown.
    """
    # Reset any orphaned jobs left over from a previous crash
    await queue.reclaim_stuck_jobs(STUCK_AFTER)
    task = asyncio.create_task(_worker_loop(queue), name="job-worker")
    log.info("Job worker started (id=%s, concurrency=%d)", WORKER_ID, MAX_CONCURRENCY)
    return task


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


async def _run_job(job, queue: QueueService, sem: asyncio.Semaphore) -> None:
    """Execute one job, update its status, then release the concurrency slot."""
    try:
        handler = get_handler(job.job_type)
        if handler is None:
            log.error("No handler registered for job type %r (job=%s)", job.job_type, job.id)
            await queue.fail_job(job.id, f"No handler for job type: {job.job_type!r}")
            await queue.append_event(job.id, "error", f"No handler registered for {job.job_type!r}")
            return

        await queue.start_job(job.id)
        await queue.append_event(
            job.id, "status_change",
            f"Job started by worker {WORKER_ID} (attempt {job.attempts + 1}/{job.max_attempts})",
        )

        log.info("Executing job %s type=%s attempt=%d", job.id, job.job_type, job.attempts + 1)

        result = await asyncio.get_running_loop().run_in_executor(None, handler, job)

        await queue.complete_job(job.id, result if isinstance(result, dict) else None)
        await queue.append_event(job.id, "status_change", "Job completed successfully")
        log.info("Job %s completed", job.id)

    except asyncio.CancelledError:
        # Worker is shutting down; leave job in running state — will be reclaimed next start
        raise
    except Exception as exc:
        log.exception("Job %s (%s) raised an exception", job.id, job.job_type)
        await queue.fail_job(job.id, str(exc))
        await queue.append_event(job.id, "error", f"Job failed: {exc}")
    finally:
        sem.release()
