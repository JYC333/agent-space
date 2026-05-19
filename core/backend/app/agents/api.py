from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Run
from ..schemas import (
    AgentCreate, AgentUpdate, AgentOut,
    RunRequest, RunOut,
    AgentVersionCreate, AgentVersionOut,
    RunCreate, RunOutV2,
)
from .agent_service import AgentService
from .version_service import AgentVersionService
from app.runs.run_service import RunService
from ..auth import get_identity
from ..jobs.queue import get_queue
from ..participation.service import try_record_participation

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=AgentOut, status_code=201)
def create_agent(
    data: AgentCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    if not data.space_id:
        data.space_id = space_id
    return AgentService(db).create(data, requesting_user_id=user_id)


@router.get("", response_model=list[AgentOut])
def list_agents(
    created_by_user_id: str | None = Query(None),
    visibility: str | None = Query(None),
    status: str | None = Query("active"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return AgentService(db).list(
        space_id=space_id,
        created_by_user_id=created_by_user_id,
        visibility=visibility,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    agent = AgentService(db).get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    data: AgentUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    updated = svc.update(agent_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return updated


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not svc.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


# ---------------------------------------------------------------------------
# Run status polling + history
# NOTE: /runs and /runs/{run_id} routes must be registered BEFORE /{agent_id}
# and /{agent_id}/runs to prevent FastAPI matching "runs" as an agent_id.
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=list[RunOutV2])
def list_all_runs(
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List all Runs in this space."""
    space_id, user_id = ids
    svc = RunService(db)
    return svc.list_runs(space_id=space_id, limit=limit)


@router.get("/runs/{run_id}", response_model=RunOutV2)
def get_run(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Get a Run by ID, scoped to the request space."""
    space_id, _ = ids
    return RunService(db).get_run(run_id, space_id)


@router.get("/runs/{run_id}/chain", response_model=list[RunOutV2])
def get_run_delegation_chain(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Walk parent_run_id links to return the full delegation ancestry, space-scoped."""
    space_id, _ = ids

    chain: list[Run] = []
    current = (
        db.query(Run).filter(Run.id == run_id, Run.space_id == space_id).first()
    )
    while current:
        chain.append(current)
        if current.parent_run_id:
            current = db.query(Run).filter(
                Run.id == current.parent_run_id, Run.space_id == space_id
            ).first()
        else:
            break
    chain.reverse()
    if not chain:
        raise HTTPException(status_code=404, detail="Run not found")
    return chain


# ---------------------------------------------------------------------------
# Alternate run entrypoints (same enqueue path as POST /{agent_id}/runs)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/run", response_model=RunOutV2, status_code=202)
async def run_agent(
    agent_id: str,
    req: RunRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Superseded URL shape; prefer POST /{agent_id}/runs.

    Creates a Run via RunService, then enqueues a job for deferred execution.
    """
    space_id, user_id = ids

    # Build context
    from ..memory.context_builder import ContextBuilder
    context = ContextBuilder(db).build(
        space_id=space_id,
        user_id=user_id,
        workspace_id=req.workspace_id,
        agent_id=agent_id,
    ).model_dump()

    # Create Run via RunService (status=queued, no execution yet)
    run_svc = RunService(db)
    run = run_svc.create_run(
        agent_id=agent_id,
        data=RunCreate(
            mode="live",
            run_type="agent",
            trigger_origin="manual",
            workspace_id=req.workspace_id,
        ),
        space_id=space_id,
        user_id=user_id,
    )

    # Enqueue job for deferred execution
    await get_queue().enqueue(
        "agent_run",
        {
            "run_id": run.id,
            "adapter_type": req.adapter_type,
            "prompt": req.prompt,
            "context": context,
            "workspace_path": req.workspace_path,
            "timeout": 300,
            "risk_level": req.risk_level,
            "cli_adapter_config_id": req.cli_adapter_config_id,
        },
        space_id=space_id,
        user_id=user_id,
        agent_id=agent_id,
    )
    return run


@router.post("/{agent_id}/delegate", response_model=RunOutV2, status_code=201)
async def delegate_to_agent(
    agent_id: str,
    req: RunRequest,
    parent_run_id: str = Query(..., description="The run ID of the delegating agent"),
    instructed_by_agent_id: str = Query(..., description="The agent ID that is delegating"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Superseded URL shape; prefer POST /{agent_id}/runs with parent_run_id.

    Agent-to-agent delegation. Creates a Run via RunService and enqueues
    for deferred execution.
    """
    space_id, diag_user_id = ids

    from ..memory.context_builder import ContextBuilder

    svc = AgentService(db)
    run = svc.delegate(
        target_agent_id=agent_id,
        req=req,
        space_id=space_id,
        parent_run_id=parent_run_id,
        instructed_by_agent_id=instructed_by_agent_id,
    )

    ctx_user = run.instructed_by_user_id or diag_user_id
    context = ContextBuilder(db).build(
        space_id=space_id,
        user_id=ctx_user,
        workspace_id=req.workspace_id,
        agent_id=agent_id,
    ).model_dump()

    # Enqueue job for deferred execution
    await get_queue().enqueue(
        "agent_run",
        {
            "run_id": run.id,
            "adapter_type": req.adapter_type,
            "prompt": req.prompt,
            "context": context,
            "workspace_path": req.workspace_path,
            "timeout": 300,
            "risk_level": req.risk_level,
        },
        space_id=space_id,
        user_id=ctx_user,
        agent_id=agent_id,
    )
    return run


@router.get("/{agent_id}/runs", response_model=list[RunOutV2])
def list_runs_for_agent(
    agent_id: str,
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List Runs for a specific agent."""
    space_id, user_id = ids
    svc = RunService(db)
    return svc.list_runs(space_id=space_id, agent_id=agent_id, limit=limit)


# ---------------------------------------------------------------------------
# Run creation
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/runs", response_model=RunOutV2, status_code=201)
def create_agent_run(
    agent_id: str,
    data: RunCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Create a Run for the given Agent using its current AgentVersion.

    - Creates Run with status=queued
    - Uses Agent.current_version_id (no new AgentVersion created)
    - Creates minimal ContextSnapshot
    - mode=dry_run only records the mode (no preview artifact/proposal)
    - No real execution, no adapter calls, no job dispatch

    Raises:
    - 404 if Agent not found in this space
    - 400 if Agent has no current_version_id
    - 400 if AgentVersion doesn't belong to this agent/space
    - 422 if mode/run_type/trigger_origin is invalid
    - 400 if workspace_id/session_id is in a different space
    """
    space_id, user_id = ids
    svc = RunService(db)
    run = svc.create_run(
        agent_id=agent_id,
        data=data,
        space_id=space_id,
        user_id=user_id,
    )
    try_record_participation(
        db,
        user_id=run.instructed_by_user_id,
        source_space_id=space_id,
        source_object_type="run",
        source_object_id=run.id,
        role="instructed",
    )
    return run


# ---------------------------------------------------------------------------
# AgentVersion endpoints
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/versions", response_model=AgentVersionOut, status_code=201)
def create_agent_version(
    agent_id: str,
    data: AgentVersionCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Explicitly create a new AgentVersion and advance current_version_id."""
    space_id, user_id = ids
    svc = AgentService(db)
    # Validate agent exists and belongs to this space
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return svc.create_version(agent_id, data)


@router.get("/{agent_id}/versions", response_model=list[AgentVersionOut])
def list_agent_versions(
    agent_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List all versions for an agent, newest first."""
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentVersionService(db).list_for_agent(agent_id, space_id)


@router.get("/{agent_id}/versions/{version_id}", response_model=AgentVersionOut)
def get_agent_version(
    agent_id: str,
    version_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Return an immutable version snapshot."""
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentVersionService(db).get_version_for_agent(version_id, agent.id, agent.space_id)
