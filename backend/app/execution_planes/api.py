from __future__ import annotations
"""ExecutionPlane HTTP API — read-only plane listing and lookup."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .service import ExecutionPlaneService

router = APIRouter(prefix="/execution-planes", tags=["execution_planes"])


class ExecutionPlaneOut(BaseModel):
    id: str
    space_id: str
    name: str
    type: str
    provider: str
    execution_location: str
    runtime_origin: str
    trust_level: str
    observability_level: str
    data_exposure_level: str
    credential_mode: str
    enabled: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ExecutionPlaneOut])
def list_execution_planes(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return ExecutionPlaneService(db).list_execution_planes(space_id)


@router.get("/{execution_plane_id}", response_model=ExecutionPlaneOut)
def get_execution_plane(
    execution_plane_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    plane = ExecutionPlaneService(db).get_execution_plane(execution_plane_id, space_id)
    if not plane:
        raise HTTPException(status_code=404, detail="Execution plane not found")
    return plane
