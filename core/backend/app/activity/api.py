from __future__ import annotations
"""
Activity Inbox API

Routes:
  POST   /activity              — ingest a new activity record
  GET    /activity              — list activity records for the current space
  GET    /activity/{id}         — get a single activity record
  PATCH  /activity/{id}/process — mark a record as processed
  PATCH  /activity/{id}/archive — archive a record
  POST   /activity/{id}/proposals — create memory proposals from this record
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..config import settings
from .service import ActivityService

router = APIRouter(prefix="/activity", tags=["activity"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ActivityCreate(BaseModel):
    source_type: str
    content: str
    title: Optional[str] = None
    user_id: Optional[str] = None
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


class ProposalSpec(BaseModel):
    target_scope: str
    target_namespace: str
    target_visibility: str = "private"
    memory_type: str
    proposed_title: str
    proposed_content: str
    rationale: str
    source_evidence: Optional[str] = None
    risk_level: str = "low"


class CreateProposalsRequest(BaseModel):
    user_id: str
    proposals: list[ProposalSpec]


class ProposalOut(BaseModel):
    id: str
    space_id: str
    user_id: str
    status: str
    proposed_title: str
    proposed_content: str
    rationale: str
    risk_level: str
    source_activity_id: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=ActivityOut)
def create_activity(
    body: ActivityCreate,
    space_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> ActivityOut:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    record = svc.create(
        space_id=effective_space,
        source_type=body.source_type,
        content=body.content,
        user_id=body.user_id,
        workspace_id=body.workspace_id,
        agent_id=body.agent_id,
        title=body.title,
        source_run_id=body.source_run_id,
        source_task_id=body.source_task_id,
        source_session_id=body.source_session_id,
        source_url=body.source_url,
        metadata_json=body.metadata_json,
    )
    return ActivityOut.from_orm_model(record)


@router.get("", response_model=list[ActivityOut])
def list_activities(
    space_id: str = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ActivityOut]:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    records = svc.list(
        space_id=effective_space,
        user_id=user_id,
        workspace_id=workspace_id,
        source_type=source_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [ActivityOut.from_orm_model(r) for r in records]


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(
    activity_id: str,
    space_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> ActivityOut:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    record = svc.get(activity_id, effective_space)
    if not record:
        raise HTTPException(status_code=404, detail="Activity record not found")
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/process", response_model=ActivityOut)
def mark_processed(
    activity_id: str,
    space_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> ActivityOut:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    try:
        record = svc.mark_processed(activity_id, effective_space)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/archive", response_model=ActivityOut)
def archive_activity(
    activity_id: str,
    space_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> ActivityOut:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    try:
        record = svc.mark_archived(activity_id, effective_space)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.post("/{activity_id}/proposals", response_model=list[ProposalOut])
def create_proposals(
    activity_id: str,
    body: CreateProposalsRequest,
    space_id: str = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ProposalOut]:
    effective_space = space_id or settings.default_space_id
    svc = ActivityService(db)
    try:
        created = svc.create_proposals_from(
            activity_id=activity_id,
            space_id=effective_space,
            proposals=[p.model_dump() for p in body.proposals],
            user_id=body.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [
        ProposalOut(
            id=p.id,
            space_id=p.space_id,
            user_id=p.user_id,
            status=p.status,
            proposed_title=p.proposed_title,
            proposed_content=p.proposed_content,
            rationale=p.rationale,
            risk_level=p.risk_level,
            source_activity_id=p.source_activity_id,
            created_at=p.created_at.isoformat(),
        )
        for p in created
    ]
