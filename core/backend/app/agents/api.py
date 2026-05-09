from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import AgentCreate, AgentUpdate, AgentOut, AgentRunRequest, AgentRunOut
from .agent_service import AgentService
from .runner import AgentRunService
from ..auth import get_identity
from ..jobs.queue import get_queue

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
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    return AgentService(db).get_or_404(agent_id)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, data: AgentUpdate, db: Session = Depends(get_db)):
    agent = AgentService(db).update(agent_id, data)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    if not AgentService(db).delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


# ---------------------------------------------------------------------------
# Run status polling + history
# NOTE: /runs and /runs/{run_id} routes must be registered BEFORE /{agent_id}
# and /{agent_id}/runs to prevent FastAPI matching "runs" as an agent_id.
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=list[AgentRunOut])
def list_all_runs(
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return AgentRunService(db).list_runs(space_id=space_id, user_id=user_id, limit=limit)


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = AgentRunService(db).get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/chain", response_model=list[AgentRunOut])
def get_run_delegation_chain(run_id: str, db: Session = Depends(get_db)):
    chain = AgentRunService(db).get_delegation_chain(run_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Run not found")
    return chain


# ---------------------------------------------------------------------------
# Running agents
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/run", response_model=AgentRunOut, status_code=202)
async def run_agent(
    agent_id: str,
    req: AgentRunRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = AgentService(db)
    run = svc.submit(
        agent_id=agent_id,
        req=req,
        space_id=space_id,
        instructed_by_user_id=user_id,
    )
    await get_queue().enqueue(
        "agent_run",
        {
            "run_id": run.id,
            "adapter_type": req.adapter_type,
            "prompt": req.prompt,
            "context": run.context_snapshot or {},
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


@router.post("/{agent_id}/delegate", response_model=AgentRunOut, status_code=201)
def delegate_to_agent(
    agent_id: str,
    req: AgentRunRequest,
    parent_run_id: str = Query(..., description="The run ID of the delegating agent"),
    instructed_by_agent_id: str = Query(..., description="The agent ID that is delegating"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    return AgentService(db).delegate(
        target_agent_id=agent_id,
        req=req,
        space_id=space_id,
        parent_run_id=parent_run_id,
        instructed_by_agent_id=instructed_by_agent_id,
    )


@router.get("/{agent_id}/runs", response_model=list[AgentRunOut])
def list_agent_runs(
    agent_id: str,
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return AgentRunService(db).list_runs(
        space_id=space_id, user_id=user_id, agent_id=agent_id, limit=limit
    )
