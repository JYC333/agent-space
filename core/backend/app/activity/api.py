from __future__ import annotations
"""
Activity Inbox API

Routes:
  POST   /activity                — ingest a new activity record
  GET    /activity                — list activity records for the current space
  GET    /activity/{id}           — get a single activity record
  PATCH  /activity/{id}/review    — mark a record as reviewed (status-only; no proposals)
  PATCH  /activity/{id}/archive   — archive a record
  POST   /activity/{id}/consolidate — generate proposals for this activity
  POST   /activity/summary-runs   — summarize selected activities into an Artifact

Space and authenticated user come from ``get_identity`` (same as Memory/Runs).
Optional query ``for_user_id`` limits the list to that user and must equal the
current user (cannot enumerate another user's inbox via query).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..memory.consolidation.service import ActivityConsolidationService
from ..participation.service import try_record_participation
from ..schemas import ProposalOut
from ..proposals.read_model import proposal_to_out
from .service import ActivityService
from .input_summary_service import (
    InputSummaryProviderMissingError,
    InputSummaryProviderCallError,
    InputSummaryNoContentError,
    InputSummaryCrossSpaceError,
    InputSummaryService,
)

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
    occurred_at: Optional[datetime] = Field(
        default=None,
        description="Real-world occurrence time. If omitted, defaults to server insertion time.",
    )


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
    visibility: str = "space_shared"
    occurred_at: Optional[str] = None
    created_at: str
    updated_at: str
    project_id: Optional[str] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, m: object) -> "ActivityOut":
        occ = getattr(m, "occurred_at", None)  # type: ignore[attr-defined]
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
            visibility=m.visibility,          # type: ignore[attr-defined]
            occurred_at=occ.isoformat() if occ is not None else None,
            created_at=m.created_at.isoformat(),   # type: ignore[attr-defined]
            updated_at=m.updated_at.isoformat(),   # type: ignore[attr-defined]
            project_id=getattr(m, "project_id", None),  # type: ignore[attr-defined]
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
            occurred_at=body.occurred_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try_record_participation(
        db,
        user_id=auth_user_id,
        source_space_id=space_id,
        source_object_type="activity",
        source_object_id=record.id,
        role="created",
    )
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
    project_id: Optional[str] = Query(default=None),
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
            project_id=project_id,
            limit=limit,
            offset=offset,
            viewer_user_id=auth_user_id,
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
    space_id, user_id = ids
    svc = ActivityService(db)
    record = svc.get(activity_id, space_id, viewer_user_id=user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Activity record not found")
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/review", response_model=ActivityOut)
def mark_reviewed(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    """Mark as reviewed (status-only, no proposal generation)."""
    space_id, user_id = ids
    svc = ActivityService(db)
    try:
        record = svc.mark_reviewed(activity_id, space_id, viewer_user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.patch("/{activity_id}/archive", response_model=ActivityOut)
def archive_activity(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ActivityOut:
    space_id, user_id = ids
    svc = ActivityService(db)
    try:
        record = svc.mark_archived(activity_id, space_id, viewer_user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ActivityOut.from_orm_model(record)


@router.post("/{activity_id}/consolidate", response_model=list[ProposalOut])
def consolidate_activity(
    activity_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[ProposalOut]:
    """Generate proposals for one activity (rule-based consolidation pipeline)."""
    space_id, auth_user_id = ids
    svc = ActivityService(db)
    if not svc.get(activity_id, space_id, viewer_user_id=auth_user_id):
        raise HTTPException(status_code=404, detail="Activity record not found")
    cons = ActivityConsolidationService(db)
    created = cons.run_for_activity_ids(
        space_id,
        [activity_id],
        acting_user_id=auth_user_id,
    )
    return [proposal_to_out(p) for p in created]


# ---------------------------------------------------------------------------
# Summary-runs: LLM-powered summarization into Artifact + optional proposals
# ---------------------------------------------------------------------------

class SummaryRunRequest(BaseModel):
    activity_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intake_item_ids: list[str] = Field(default_factory=list)
    summary_goal: Optional[str] = None
    create_memory_proposal: bool = False
    create_knowledge_proposal: bool = False


class SummaryRunOut(BaseModel):
    run_id: str
    artifact_id: str
    proposal_ids: list[str]
    status: str
    summary_preview: str


@router.post("/summary-runs", response_model=SummaryRunOut, status_code=201)
def create_activity_summary_run(
    body: SummaryRunRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> SummaryRunOut:
    """Summarize selected activity records (and optional evidence/intake items) into an Artifact.

    The summary is stored as an Artifact with artifact_type=summary. Optional proposals
    are created for review; no Memory or Knowledge is written directly.
    """
    space_id, auth_user_id = ids
    if not body.activity_ids and not body.evidence_ids and not body.intake_item_ids:
        raise HTTPException(
            status_code=422,
            detail="At least one of activity_ids, evidence_ids, or intake_item_ids is required.",
        )
    svc = InputSummaryService(db)
    try:
        result = svc.run(
            space_id=space_id,
            user_id=auth_user_id,
            activity_ids=body.activity_ids,
            evidence_ids=body.evidence_ids,
            intake_item_ids=body.intake_item_ids,
            summary_goal=body.summary_goal,
            create_memory_proposal=body.create_memory_proposal,
            create_knowledge_proposal=body.create_knowledge_proposal,
        )
    except InputSummaryProviderMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InputSummaryProviderCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except InputSummaryNoContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InputSummaryCrossSpaceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return SummaryRunOut(
        run_id=result.run_id,
        artifact_id=result.artifact_id,
        proposal_ids=result.proposal_ids,
        status=result.status,
        summary_preview=result.summary_preview,
    )
