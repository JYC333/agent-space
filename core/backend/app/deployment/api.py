from __future__ import annotations

from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ulid import ULID

from ..auth import get_identity
from ..config import settings
from ..db import get_db
from ..models import DeploymentJob
from .client import DeployerClient

router = APIRouter(prefix="/deployments", tags=["deployments"])

# Core deployment job types
_CORE_JOB_TYPES = {"rebuild_agent_space", "restart_agent_space", "health_check"}

# Self-evolution job types
_SELF_EVOLUTION_JOB_TYPES = {
    "init_agent_space_worktree",
    "create_system_worktree",
    "collect_system_diff",
    "run_system_tests",
    "run_test_deploy",
    "merge_approved_system_patch",
    "run_prod_deploy",
    "cleanup_system_worktree",
}

ALLOWED_JOB_TYPES = _CORE_JOB_TYPES | _SELF_EVOLUTION_JOB_TYPES


class DeploymentJobCreate(BaseModel):
    job_type: str
    proposal_id: Optional[str] = None
    target: str = "local"
    args: Optional[dict] = None


class DeploymentJobOut(BaseModel):
    id: str
    proposal_id: Optional[str]
    space_id: str
    requested_by_user_id: str
    job_type: str
    target: str
    status: str
    result_json: Optional[dict]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.post("/jobs", response_model=DeploymentJobOut, status_code=201)
def create_deployment_job(
    body: DeploymentJobCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids

    if body.job_type not in ALLOWED_JOB_TYPES:
        raise HTTPException(400, f"Unknown job_type. Allowed: {sorted(ALLOWED_JOB_TYPES)}")

    job = DeploymentJob(
        id=str(ULID()),
        proposal_id=body.proposal_id,
        space_id=space_id,
        requested_by_user_id=user_id,
        job_type=body.job_type,
        target=body.target,
        status="queued",
        request_json=body.model_dump(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    client = DeployerClient(settings.deployer_socket_path)
    job.started_at = datetime.now(UTC)
    job.status = "running"
    db.commit()

    result = client.submit_job({
        "job_id":                job.id,
        "proposal_id":           job.proposal_id,
        "space_id":              job.space_id,
        "requested_by_user_id":  job.requested_by_user_id,
        "job_type":              job.job_type,
        "target":                job.target,
    }, args=body.args)

    job.result_json = result
    job.status = result.get("status", "failed")
    job.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs", response_model=list[DeploymentJobOut])
def list_deployment_jobs(
    limit: int = 20,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return (
        db.query(DeploymentJob)
        .filter(DeploymentJob.space_id == space_id)
        .order_by(DeploymentJob.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/jobs/{job_id}", response_model=DeploymentJobOut)
def get_deployment_job(
    job_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    job = (
        db.query(DeploymentJob)
        .filter(DeploymentJob.id == job_id, DeploymentJob.space_id == space_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Deployment job not found")
    return job
