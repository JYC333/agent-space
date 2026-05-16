from __future__ import annotations
"""
Activity Inbox API

Routes:
  POST   /activity              — ingest a new activity record
  GET    /activity              — list activity records for the current space
  GET    /activity/{id}         — get a single activity record
  PATCH  /activity/{id}/process — mark a record as processed
  PATCH  /activity/{id}/archive — archive a record
  POST   /activity/{id}/consolidate — run consolidation for this activity only (no body)

Space and authenticated user come from ``get_identity`` (same as Memory/Runs).
Optional query ``for_user_id`` limits the list to that user and must equal the
current user (cannot enumerate another user's inbox via query).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..memory.consolidation.service import ActivityConsolidationService
from ..schemas import ProposalOut
from ..proposals.read_model import proposal_to_out
from .service import ActivityService

router = APIRouter(prefix="/activity", tags=["activity"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ActivityCreate(BaseModel):
    source_type: str
    content: str
    title: Optional[str] = None
    user_id: Optional[str] = Field(
        default=None,
        description="Deprecated: ignored for authorization; row user_id is always the authenticated user.",
    )
    workspace_id: Optional[str] = None
    agent_id: Optional[str] = None
    source_run_id: Optional[str] = None
    source_task_id: Optional[str] = None
    source_session_id: Optional[str] = None
    source_url: Optional[str] = None
    metadata_json: Optional[dict] = None


class ActivityOut(BaseModel):
    id: str
    space_id: str
    user_id: Optional[str]
    workspace_id: Optional[str]
    agent_id: Optional[str]
    source_type: str
    title: Optional[str]
    content: str
    source_run_id: Optional[str]
    source_task_id: Optional[str]
    source_session_id: Optional[str]
    source_url: Optional[str]
    status: str
    metadata_json: Optional[dict]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, m: object) -> "ActivityOut":
        return cls(
            id=m.id,                          # type: ignore[attr-defined]
            space_id=m.space_id,              # type: ignore[attr-defined]
            user_id=m.user_id,                # type: ignore[attr-defined]
            workspace_id=m.workspace_id,      # type: ignore[attr-defined]
            agent_id=m.agent_id,              # type: ignore[attr-defined]
            source_type=m.source_type,        # type: ignore[attr-defined]
            title=m.title,                    # type: ignore[attr-defined]
            content=m.content or "",          # type: ignore[attr-defined]
            source_run_id=m.source_run_id,    # type: ignore[attr-defined]
            source_task_id=m.source_task_id,  # type: ignore[attr-defined]
            source_session_id=m.source_session_id,  # type: ignore[attr-defined]
            source_url=m.source_url,          # type: ignore[attr-defined]
            status=m.status,                  # type: ignore[attr-defined]
            metadata_json=m.metadata_json,    # type: ignore[attr-defined]
            created_at=m.created_at.isoformat(),   # type: ignore[attr-defined]
            updated_at=m.updated_at.isoformat(),   # type: ignore[attr-defined]
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=ActivityOut)
def create_activity(
    body: ActivityCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    space_id, auth_user_id = ids
    if body.user_id is not None and body.user_id != auth_user_id:
        raise HTTPException(
            status_code=403,
            detail="user_id in body must match the authenticated user",
        )
    svc = ActivityService(db)
    try:
        record = svc.create(
            space_id=space_id,
            source_type=body.source_type,
            content=body.content,
            user_id=auth_user_id,
            workspace_id=body.workspace_id,
            agent_id=body.agent_id,
            title=body.title,
            source_run_id=body.source_run_id,
            source_task_id=body.source_task_id,
            source_session_id=body.source_session_id,
            source_url=body.source_url,
            metadata_json=body.metadata_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ActivityOut.from_orm_model(record)


@router.get("", response_model=list[ActivityOut])
def list_activities(
    ids: tuple[str, str] = Depends(get_identity),
    for_user_id: Optional[str] = Query(
        default=None,
        description="If set, restrict listing to this user; must equal the authenticated user.",
    ),
    workspace_id: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ActivityOut]:
    space_id, auth_user_id = ids
    if for_user_id is not None and for_user_id != auth_user_id:
        raise HTTPException(
            status_code=403,
            detail="for_user_id must match the authenticated user",
        )
    svc = ActivityService(db)
    try:
        records = svc.list(
            space_id=space_id,
            user_id=for_user_id,
            workspace_id=workspace_id,
            source_type=source_type,
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [ActivityOut.from_orm_model(r) for r in records]


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    space_id, _ = ids
    svc = ActivityService(db)
    record = svc.get(activity_id, space_id)
    if not record:
        raise HTTPException(status_code=404, detail="Activity record not found")
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/process", response_model=ActivityOut)
def mark_processed(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    space_id, _ = ids
    svc = ActivityService(db)
    try:
        record = svc.mark_processed(activity_id, space_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/archive", response_model=ActivityOut)
def archive_activity(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    space_id, _ = ids
    svc = ActivityService(db)
    try:
        record = svc.mark_archived(activity_id, space_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.post("/{activity_id}/consolidate", response_model=list[ProposalOut])
def consolidate_activity(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[ProposalOut]:
    """Run consolidation for exactly one activity; same pipeline as ``POST /memory/consolidation/run``."""
    space_id, auth_user_id = ids
    svc = ActivityService(db)
    if not svc.get(activity_id, space_id):
        raise HTTPException(status_code=404, detail="Activity record not found")
    cons = ActivityConsolidationService(db)
    created = cons.run_for_activity_ids(
        space_id,
        [activity_id],
        acting_user_id=auth_user_id,
    )
    return [proposal_to_out(p) for p in created]
