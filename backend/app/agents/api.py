from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Run, Proposal
from ..schemas import (
    AgentCreate, AgentUpdate, AgentOut,
    AgentConfigProposalCreate, AgentConfigUpdate,
    RunRequest,
    AgentVersionCreate, AgentVersionOut,
    RunCreate, RunOut, ProposalOut,
    SpaceAssistantSettingsOut, SpaceAssistantSettingsUpdate,
)
from .agent_service import AgentService
from .chat_service import ChatTurnOut, ChatTurnRequest, run_chat_turn
from .version_service import AgentVersionService
from app.runs import RunService
from app.runs import run_to_out
from ..proposals import proposal_to_out
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
    svc = AgentService(db)
    agent = svc.create(data, requesting_user_id=user_id)
    return svc.to_agent_out(agent)


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
    svc = AgentService(db)
    agents = svc.list(
        space_id=space_id,
        created_by_user_id=created_by_user_id,
        visibility=visibility,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [svc.to_agent_out(a) for a in agents]


# ---------------------------------------------------------------------------
# Per-space system-managed default Assistant (the Chat identity).
# NOTE: must precede /{agent_id} so "default-assistant" is not matched as an id.
# ---------------------------------------------------------------------------

@router.get("/default-assistant", response_model=AgentOut)
def get_default_assistant_route(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Return this space's default Assistant Agent, or 404 if not created yet."""
    from .personal_assistant import get_default_assistant

    space_id, _ = ids
    agent = get_default_assistant(db, space_id=space_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="No default Assistant in this space")
    return AgentService(db).to_agent_out(agent)


@router.post("/default-assistant", response_model=AgentOut, status_code=200)
def ensure_default_assistant(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Resolve-or-create this space's system-managed default Assistant.

    Idempotent: returns the existing assistant if present, otherwise mints one via
    copy-on-create from the internal seed spec. The assistant is system-managed (it
    is not user-owned and not a public template instance) — chat execution is wired
    separately and is intentionally out of scope here.
    """
    from .personal_assistant import get_or_create_default_assistant

    space_id, _ = ids
    # System-managed: owner stays NULL (space/system-owned), not the calling user.
    agent = get_or_create_default_assistant(db, space_id=space_id, owner_user_id=None)
    return AgentService(db).to_agent_out(agent)


@router.get("/default-assistant/settings", response_model=SpaceAssistantSettingsOut)
def get_default_assistant_settings(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Return this space's Assistant preferences (soft UI/context layer)."""
    from .assistant_settings import AssistantSettingsService

    space_id, _ = ids
    return AssistantSettingsService(db).get_or_create(space_id)


@router.patch("/default-assistant/settings", response_model=SpaceAssistantSettingsOut)
def update_default_assistant_settings(
    data: SpaceAssistantSettingsUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Update Assistant preferences. Cannot touch the core prompt or any hard policy."""
    from .assistant_settings import AssistantSettingsService

    space_id, _ = ids
    return AssistantSettingsService(db).update(space_id, data.model_dump(exclude_unset=True))


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return svc.to_agent_out(agent)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    data: AgentUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    updated = svc.update(agent_id, data, user_id=user_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return svc.to_agent_out(updated)


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


@router.post("/{agent_id}/config", response_model=AgentOut)
def update_agent_config(
    agent_id: str,
    data: AgentConfigUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Owner config edit: append a new AgentVersion from the current one + repoint it.

    The previous AgentVersion is never mutated. Hard-safety snapshots are copied
    verbatim and cannot be loosened by frontend overrides.
    """
    space_id, user_id = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    updated = svc.update_config(agent_id, data, user_id=user_id)
    return svc.to_agent_out(updated)


@router.get("/{agent_id}/current-version", response_model=AgentVersionOut)
def get_agent_current_version(
    agent_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Return the Agent's current immutable AgentVersion config snapshot."""
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    version = svc.get_current_version(agent_id)
    if not version:
        raise HTTPException(status_code=404, detail="Agent has no current version")
    return version


@router.get("/{agent_id}/proposals", response_model=list[ProposalOut])
def list_agent_proposals(
    agent_id: str,
    status: str | None = Query("pending"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Proposals associated with this agent (config updates + run-emitted proposals)."""
    space_id, _ = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    q = db.query(Proposal).filter(Proposal.space_id == space_id)
    if status:
        q = q.filter(Proposal.status == status)
    rows = q.order_by(Proposal.created_at.desc()).all()
    matched = [
        p for p in rows
        if p.created_by_agent_id == agent_id or (p.payload_json or {}).get("agent_id") == agent_id
    ]
    return [proposal_to_out(p) for p in matched]


@router.post("/{agent_id}/config-proposals", response_model=ProposalOut, status_code=202)
def create_agent_config_proposal(
    agent_id: str,
    data: AgentConfigProposalCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    proposal = svc.create_config_update_proposal(agent_id, data, user_id=user_id)
    return proposal_to_out(proposal)


# ---------------------------------------------------------------------------
# Run status polling + history
# NOTE: /runs and /runs/{run_id} routes must be registered BEFORE /{agent_id}
# and /{agent_id}/runs to prevent FastAPI matching "runs" as an agent_id.
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=list[RunOut])
def list_all_runs(
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List all Runs in this space."""
    space_id, user_id = ids
    svc = RunService(db)
    return [run_to_out(db, r) for r in svc.list_runs(space_id=space_id, limit=limit)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Get a Run by ID, scoped to the request space."""
    space_id, _ = ids
    return run_to_out(db, RunService(db).get_run(run_id, space_id))


@router.get("/runs/{run_id}/chain", response_model=list[RunOut])
def get_run_lineage_chain(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Walk parent_run_id links to return the full run lineage ancestry, space-scoped."""
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
    return [run_to_out(db, r) for r in chain]


# ---------------------------------------------------------------------------
# Alternate run entrypoints (same enqueue path as POST /{agent_id}/runs)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/run", response_model=RunOut, status_code=202)
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
    from ..memory import ContextBuilder
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
            runtime_adapter_id=req.runtime_adapter_id,
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
            "runtime_adapter_id": req.runtime_adapter_id,
        },
        space_id=space_id,
        user_id=user_id,
        agent_id=agent_id,
    )
    return run_to_out(db, run)



@router.get("/{agent_id}/runs", response_model=list[RunOut])
def list_runs_for_agent(
    agent_id: str,
    limit: int = Query(50, le=200),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List Runs for a specific agent."""
    space_id, user_id = ids
    svc = RunService(db)
    return [run_to_out(db, r) for r in svc.list_runs(space_id=space_id, agent_id=agent_id, limit=limit)]


# ---------------------------------------------------------------------------
# Run creation
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/runs", response_model=RunOut, status_code=201)
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
    return run_to_out(db, run)


# ---------------------------------------------------------------------------
# Chat (synchronous Personal Assistant turn)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/chat", response_model=ChatTurnOut)
def chat_with_agent(
    agent_id: str,
    req: ChatTurnRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Run one synchronous chat turn against the agent and return the reply.

    Persists the turn to a Session, assembles space-aware context, creates and
    executes a Run in-process (the Assistant's no-tools ``model_api`` path), and
    returns the model reply. On a clean execution failure (e.g. no model provider
    configured) returns ``ok=False`` with an ``error_code`` instead of raising.
    """
    space_id, user_id = ids
    return run_chat_turn(db, agent_id=agent_id, space_id=space_id, user_id=user_id, req=req)


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
    """Direct AgentVersion advancement is disabled; use config proposals."""
    space_id, user_id = ids
    svc = AgentService(db)
    # Validate agent exists and belongs to this space
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    raise HTTPException(
        status_code=409,
        detail=(
            "Direct AgentVersion creation is disabled. "
            "Use POST /api/v1/agents/{agent_id}/config-proposals."
        ),
    )


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


@router.post("/{agent_id}/versions/{version_id}/restore", response_model=AgentOut)
def restore_agent_version(
    agent_id: str,
    version_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Restore a prior version by appending a NEW AgentVersion copied from it.

    The selected version is not mutated or reactivated; a fresh immutable version
    is created and becomes current, preserving the append-only history.
    """
    space_id, user_id = ids
    svc = AgentService(db)
    agent = svc.get_or_404(agent_id)
    if agent.space_id != space_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    updated = svc.restore_version(agent_id, version_id, user_id=user_id)
    return svc.to_agent_out(updated)
