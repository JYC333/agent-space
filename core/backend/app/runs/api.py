"""
Top-level Run API.

These routes are prefixed with /api/v1/runs (registered in modules/registry.py).
POST /api/v1/agents/{id}/runs lives in app.agents.api instead to keep agent
sub-resources grouped with agent CRUD.

Surface:
  - GET /api/v1/runs/{id}        — Run detail (no full context payload)
  - GET /api/v1/runs/{id}/status — lightweight status
  - POST /api/v1/runs/{id}/execute — execute queued Run via configured runtime adapters
  - PATCH /api/v1/runs/{id}/stop  — cancel (status change only, no runner interaction)
  - GET /api/v1/runs            — list runs (optional, simple)
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..param_binding import wire_query
from ..schemas import (
    ActivityRecordOut,
    ArtifactOut,
    Page,
    ProposalOut,
    RunOut,
    RunStatusOut,
    RunStepOut,
)
from ..auth import get_identity
from ..artifacts.service import artifact_to_out
from ..proposals.read_model import proposal_to_out
from ..memory.proposals import ProposalService
from .execution import RunExecutionService
from .read_model import run_to_out
from .run_service import RunService
from .removed_runtime_token import is_obsolete_runtime_override_token
from .steps import list_run_steps

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}/activities", response_model=Page[ActivityRecordOut])
def list_run_activities(
    run_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = RunService(db)
    total, items = svc.list_run_activities(run_id, space_id, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{run_id}/artifacts", response_model=Page[ArtifactOut])
def list_run_artifacts(
    run_id: str,
    artifact_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = RunService(db)
    total, rows = svc.list_run_artifacts(
        run_id, space_id, limit=limit, offset=offset, artifact_type=artifact_type
    )
    return Page(
        items=[artifact_to_out(a) for a in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}/proposals", response_model=Page[ProposalOut])
def list_run_proposals(
    run_id: str,
    status: str | None = Query(None),
    proposal_type: str | None = wire_query(None, wire_name="type"),
    urgency: str | None = Query(None),
    expired: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    RunService(db).get_run(run_id, space_id)
    now = datetime.now(UTC)
    psvc = ProposalService(db)
    total = psvc.count_proposals_for_run(
        run_id,
        space_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        now=now,
    )
    rows = psvc.list_proposals_for_run(
        run_id,
        space_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        limit=limit,
        offset=offset,
        now=now,
    )
    return Page(
        items=[proposal_to_out(p, now=now) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}/steps", response_model=Page[RunStepOut])
def list_run_steps_route(
    run_id: str,
    limit: int = Query(200, le=500),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    RunService(db).get_run(run_id, space_id)
    steps = list_run_steps(db, run_id, space_id)
    page = steps[offset : offset + limit]
    return Page(items=page, total=len(steps), limit=limit, offset=offset)


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = RunService(db)
    run = svc.get_run(run_id, space_id)
    return run_to_out(db, run)


@router.get("/{run_id}/status", response_model=RunStatusOut)
def get_run_status(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = RunService(db)
    run = svc.get_run(run_id, space_id)
    return run


@router.post("/{run_id}/execute", response_model=RunOut)
def execute_run_route(
    run_id: str,
    runtime: str | None = Query(
        None,
        description=(
            "Omit for normal adapter execution. Unknown values return 400; "
            "obsolete runtime overrides may return 410 Gone."
        ),
    ),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Drive a **queued** Run through ``RunExecutionService`` (registered adapters only)."""
    space_id, _ = ids
    RunService(db).get_run(run_id, space_id)
    if runtime is not None and is_obsolete_runtime_override_token(runtime):
        raise HTTPException(
            status_code=410,
            detail=(
                "Obsolete runtime override is no longer supported; omit the runtime "
                "query parameter or use a configured adapter (echo, capability, …)."
            ),
        )
    RunExecutionService(db).execute_run(run_id, space_id=space_id, runtime=runtime)
    return run_to_out(db, RunService(db).get_run(run_id, space_id))


@router.patch("/{run_id}/stop")
def stop_run(
    run_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = RunService(db)
    run, changed = svc.stop_run(run_id, space_id)
    return {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "run_type": run.run_type,
        "trigger_origin": run.trigger_origin,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "error_message": run.error_message,
        "changed": changed,
    }


@router.get("")
def list_runs(
    status: str | None = Query(None),
    mode: str | None = Query(None),
    agent_id: str | None = Query(None),
    workspace_id: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = RunService(db)
    try:
        runs = svc.list_runs(
            space_id=space_id,
            status=status,
            mode=mode,
            agent_id=agent_id,
            workspace_id=workspace_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [run_to_out(db, r) for r in runs]