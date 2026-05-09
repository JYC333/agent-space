from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..schemas import Page
from .queue import get_queue, QueueService
from .schemas import JobOut, JobEventOut
from .handlers import list_registered

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _queue() -> QueueService:
    return get_queue()


# ---------------------------------------------------------------------------
# List / get jobs
# ---------------------------------------------------------------------------

@router.get("", response_model=Page[JobOut])
async def list_jobs(
    status: str | None = Query(None),
    job_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    queue: QueueService = Depends(_queue),
):
    space_id, user_id = ids
    total = await queue.count_jobs(space_id=space_id, user_id=user_id, status=status)
    items = await queue.list_jobs(
        space_id=space_id,
        user_id=user_id,
        status=status,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/handlers", response_model=list[str])
def list_handlers():
    """Return registered job type names (useful for introspection / debugging)."""
    return list_registered()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    queue: QueueService = Depends(_queue),
):
    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    space_id, _ = ids
    if job.space_id != space_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return job


@router.get("/{job_id}/events", response_model=list[JobEventOut])
async def get_job_events(
    job_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    queue: QueueService = Depends(_queue),
):
    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    space_id, _ = ids
    if job.space_id != space_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return await queue.get_events(job_id)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    queue: QueueService = Depends(_queue),
):
    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    space_id, _ = ids
    if job.space_id != space_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if job.status not in ("pending", "claimed"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel a job in status '{job.status}'",
        )
    await queue.cancel_job(job_id)
    await queue.append_event(job_id, "status_change", "Job cancelled by user")
    return await queue.get_job(job_id)
