from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..feature_gates import feature_not_implemented

router = APIRouter(prefix="/deployments", tags=["deployments"])


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
    del body, ids, db
    feature_not_implemented("deployment_jobs")


@router.get("/jobs", response_model=list[DeploymentJobOut])
def list_deployment_jobs(
    limit: int = 20,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del limit, ids, db
    return []


@router.get("/jobs/{job_id}", response_model=DeploymentJobOut)
def get_deployment_job(
    job_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del job_id, ids, db
    feature_not_implemented("deployment_jobs")
