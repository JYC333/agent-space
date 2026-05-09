from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import TaskCreate, TaskOut, AgentRunOut, Page
from .service import TaskService
from ..agents.runner import AgentRunService
from ..auth.api_key import get_identity
from ..jobs.queue import get_queue
from ..jobs.schemas import JobOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    data: TaskCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    if not data.space_id:
        data.space_id = space_id
    if not data.user_id:
        data.user_id = user_id
    svc = TaskService(db)
    return svc.create(data)


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = TaskService(db)
    total = svc.count(space_id=space_id, user_id=user_id, status=status)
    items = svc.list(space_id=space_id, user_id=user_id, status=status, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    svc = TaskService(db)
    task = svc.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/run", response_model=JobOut, status_code=202)
async def run_task(
    task_id: str,
    adapter_type: str = Query("echo"),
    workspace_path: str | None = Query(None),
    risk_level: str = Query("medium"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    task_svc = TaskService(db)
    task = task_svc.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Build context at enqueue time so the worker has everything it needs
    from ..memory.context_builder import ContextBuilder
    context = ContextBuilder(db).build(
        space_id=space_id,
        user_id=user_id,
        capability_id=task.capability_id,
        session_id=task.session_id,
    ).model_dump()

    # Pre-create the AgentRun record so callers can track it immediately
    runner = AgentRunService(db)
    run = runner.create_pending(
        prompt=task.description or task.title,
        context=context,
        adapter_type=adapter_type,
        space_id=space_id,
        user_id=user_id,
        task_id=task_id,
        capability_id=task.capability_id,
        workspace_id=task.workspace_id,
    )

    # Mark task as running now; worker will flip it to completed/failed
    task_svc.update_status(task_id, status="running")

    job = await get_queue().enqueue(
        "agent_run",
        {
            "run_id": run.id,
            "adapter_type": adapter_type,
            "prompt": task.description or task.title,
            "context": context,
            "workspace_path": workspace_path,
            "timeout": 300,
            "risk_level": risk_level,
            "task_id": task_id,
        },
        space_id=space_id,
        user_id=user_id,
        workspace_id=task.workspace_id,
    )
    return job


@router.get("/{task_id}/runs", response_model=list[AgentRunOut])
def list_runs(
    task_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    runner = AgentRunService(db)
    return runner.list_runs(space_id=space_id, user_id=user_id, task_id=task_id)
