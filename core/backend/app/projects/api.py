"""Project HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..schemas import (
    Page,
    ProjectCreate,
    ProjectOut,
    ProjectSummaryOut,
    ProjectUpdate,
    ProjectWorkspaceLinkCreate,
    ProjectWorkspaceLinkOut,
)
from .service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def _get_project_or_404(
    project_id: str,
    space_id: str,
    db: Session,
) -> "ProjectOut":
    svc = ProjectService(db)
    row = svc.get(project_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    status: str = Query("active"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    total, rows = svc.list_projects(space_id, status=status, limit=limit, offset=offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    data: ProjectCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ProjectService(db)
    try:
        row = svc.create(space_id, data, created_by_user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return row


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return _get_project_or_404(project_id, space_id, db)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    try:
        row = svc.update(project_id, space_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    row = svc.archive(project_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.get("/{project_id}/summary", response_model=ProjectSummaryOut)
def get_project_summary(
    project_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    result = svc.get_summary(project_id, space_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.get("/{project_id}/workspaces", response_model=list[ProjectWorkspaceLinkOut])
def list_project_workspaces(
    project_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    _get_project_or_404(project_id, space_id, db)
    svc = ProjectService(db)
    return svc.list_workspaces(project_id, space_id)


@router.post("/{project_id}/workspaces", response_model=ProjectWorkspaceLinkOut, status_code=201)
def link_workspace(
    project_id: str,
    data: ProjectWorkspaceLinkCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    try:
        link = svc.link_workspace(project_id, space_id, data)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=409, detail=detail)
    return link


@router.delete("/{project_id}/workspaces/{workspace_id}", status_code=204)
def unlink_workspace(
    project_id: str,
    workspace_id: str,
    role: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = ProjectService(db)
    removed = svc.unlink_workspace(project_id, workspace_id, space_id, role=role)
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found")
