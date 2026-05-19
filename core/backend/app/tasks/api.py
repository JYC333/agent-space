from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.api_key import get_identity
from app.db import get_db
from app.participation.service import try_record_participation
from app.proposals.read_model import proposal_to_summary_out
from app.schemas import (
    Page,
    RunOutV2,
    TaskArtifactOut,
    TaskCreate,
    TaskOut,
    TaskProposalOut,
    TaskRunCreateBody,
    TaskRunListItem,
    TaskRunOut,
    TaskUpdate,
)

from .board_api import router as board_router
from .service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])

extra_routers = [board_router]


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    data: TaskCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    task = TaskService(db).create(data, space_id, user_id)
    try_record_participation(
        db,
        user_id=user_id,
        source_space_id=space_id,
        source_object_type="task",
        source_object_id=task.id,
        role="created",
    )
    return task


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    board_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    total, items = TaskService(db).list_tasks(
        space_id, board_id=board_id, limit=limit, offset=offset, user_id=user_id
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return TaskService(db).get(task_id, space_id, user_id=user_id)


@router.patch("/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: str,
    data: TaskUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return TaskService(db).update(task_id, space_id, data, user_id=user_id)


@router.post("/{task_id}/runs", response_model=RunOutV2, status_code=201)
def create_task_run(
    task_id: str,
    body: TaskRunCreateBody,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    _link, run = TaskService(db).create_queued_run_for_task(task_id, space_id, user_id, body)
    return run


@router.get("/{task_id}/runs", response_model=Page[TaskRunListItem])
def list_task_runs(
    task_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = TaskService(db)
    total, links, runs = svc.list_task_runs(task_id, space_id, user_id=user_id, limit=limit, offset=offset)
    run_by_id = {r.id: r for r in runs}
    items: list[TaskRunListItem] = []
    for link in links:
        r = run_by_id.get(link.run_id)
        if r:
            items.append(TaskRunListItem(link=TaskRunOut.model_validate(link), run=RunOutV2.model_validate(r)))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}/artifacts", response_model=Page[TaskArtifactOut])
def list_task_artifacts(
    task_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    total, rows = TaskService(db).list_task_artifacts(task_id, space_id, user_id=user_id, limit=limit, offset=offset)
    out: list[TaskArtifactOut] = []
    for row in rows:
        out.append(TaskArtifactOut.model_validate(row))
    return Page(items=out, total=total, limit=limit, offset=offset)


@router.get("/{task_id}/proposals", response_model=Page[TaskProposalOut])
def list_task_proposals(
    task_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    now = datetime.now(UTC)
    total, rows = TaskService(db).list_task_proposals(task_id, space_id, user_id=user_id, limit=limit, offset=offset)
    out: list[TaskProposalOut] = []
    for r in rows:
        out.append(
            TaskProposalOut(
                id=r.id,
                space_id=r.space_id,
                task_id=r.task_id,
                proposal_id=r.proposal_id,
                role=r.role,
                created_at=r.created_at,
                proposal=proposal_to_summary_out(r.proposal, now=now),
            )
        )
    return Page(items=out, total=total, limit=limit, offset=offset)
