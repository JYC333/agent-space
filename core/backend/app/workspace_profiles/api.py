from __future__ import annotations
"""WorkspaceProfile HTTP API — get/create/update structured workspace config."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from .service import WorkspaceProfileService

router = APIRouter(prefix="/workspace-profiles", tags=["workspace_profiles"])


class WorkspaceProfileOut(BaseModel):
    id: str
    space_id: str
    workspace_id: str
    repo_type: Optional[str] = None
    tech_stack_json: Optional[list] = None
    important_paths_json: Optional[list] = None
    forbidden_paths_json: Optional[list] = None
    test_commands_json: Optional[list] = None
    build_commands_json: Optional[list] = None
    architecture_boundaries_json: Optional[dict] = None
    current_focus: Optional[str] = None
    known_failures_json: Optional[list] = None
    validation_recipe_id: Optional[str] = None
    preferred_runtime_adapter_id: Optional[str] = None
    cloud_allowed: bool
    max_data_exposure_level: Optional[str] = None
    min_observability_level: Optional[str] = None

    model_config = {"from_attributes": True}


class WorkspaceProfilePatch(BaseModel):
    repo_type: Optional[str] = None
    tech_stack_json: Optional[list] = None
    important_paths_json: Optional[list] = None
    forbidden_paths_json: Optional[list] = None
    test_commands_json: Optional[list] = None
    build_commands_json: Optional[list] = None
    architecture_boundaries_json: Optional[dict] = None
    current_focus: Optional[str] = None
    known_failures_json: Optional[list] = None
    validation_recipe_id: Optional[str] = None
    preferred_runtime_adapter_id: Optional[str] = None
    cloud_allowed: Optional[bool] = None
    max_data_exposure_level: Optional[str] = None
    min_observability_level: Optional[str] = None


@router.get("/{workspace_id}", response_model=WorkspaceProfileOut)
def get_workspace_profile(
    workspace_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = WorkspaceProfileService(db)
    profile = svc.get_or_create_workspace_profile(workspace_id, space_id)
    return profile


@router.patch("/{workspace_id}", response_model=WorkspaceProfileOut)
def update_workspace_profile(
    workspace_id: str,
    body: WorkspaceProfilePatch,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = WorkspaceProfileService(db)
    svc.get_or_create_workspace_profile(workspace_id, space_id)
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    profile = svc.update_workspace_profile(workspace_id, space_id, patch)
    if not profile:
        raise HTTPException(status_code=404, detail="Workspace profile not found")
    return profile
