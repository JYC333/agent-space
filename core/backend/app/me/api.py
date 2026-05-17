"""
PersonalView API — cross-space aggregation for the authenticated user.

Endpoints:
  GET /me/summary   — lightweight cross-space dashboard counts
  GET /me/timeline  — participation record timeline (pointer ledger only)
  GET /me/tasks     — tasks assigned/created/claimed by current user across spaces
  GET /me/pending   — pending proposals across spaces where user is a member

Rules:
  - No space_id required.
  - All readable spaces are derived from SpaceMembership.
  - No raw artifact payloads, full memory content, or raw team data returned.
  - Existing visibility / membership checks are not bypassed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..models import (
    ActivityRecord,
    ParticipationRecord,
    Proposal,
    Run,
    Space,
    SpaceMembership,
    Task,
)
from ..visibility.auth import can_read_scoped_object

router = APIRouter(prefix="/me", tags=["me"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member_space_ids(db: Session, user_id: str) -> list[str]:
    """Return IDs of all spaces where user_id is an active member."""
    rows = (
        db.query(SpaceMembership.space_id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .all()
    )
    return [r.space_id for r in rows]


def _is_member(db: Session, *, user_id: str, space_id: str) -> bool:
    return (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.space_id == space_id,
            SpaceMembership.status == "active",
        )
        .first()
    ) is not None


def _task_owner_user_id(task: Task) -> str | None:
    return task.created_by_user_id


def _run_owner_user_id(run: Run) -> str | None:
    return run.instructed_by_user_id


def _proposal_owner_user_id(proposal: Proposal) -> str | None:
    return proposal.created_by_user_id


# ---------------------------------------------------------------------------
# Response schemas (minimal — no raw content fields)
# ---------------------------------------------------------------------------


class RecentRunMinimal(BaseModel):
    id: str
    space_id: str
    agent_id: str
    status: str
    mode: str
    run_type: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecentParticipationMinimal(BaseModel):
    id: str
    user_id: str
    personal_space_id: str
    source_space_id: str
    source_object_type: str
    source_object_id: str
    role: str
    occurred_at: datetime
    created_at: datetime


class MeSummaryOut(BaseModel):
    pending_proposals_count: int
    assigned_tasks_count: int
    recent_runs: list[RecentRunMinimal]
    recent_participation: list[RecentParticipationMinimal]
    accessible_spaces_count: int


class TimelineEntryOut(BaseModel):
    id: str
    entry_type: str
    source_space_id: str | None
    source_object_type: str | None
    source_object_id: str | None
    role: str | None
    occurred_at: datetime
    created_at: datetime


class TaskMinimalOut(BaseModel):
    id: str
    space_id: str
    title: str
    status: str
    priority: str
    visibility: str
    created_by_user_id: str | None
    assigned_user_id: str | None
    created_at: datetime
    updated_at: datetime


class ProposalMinimalOut(BaseModel):
    id: str
    space_id: str
    proposal_type: str
    status: str
    urgency: str
    title: str
    visibility: str
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=MeSummaryOut)
def get_me_summary(
    recent_runs_limit: int = Query(5, ge=1, le=20),
    recent_participation_limit: int = Query(5, ge=1, le=20),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> MeSummaryOut:
    """Lightweight cross-space summary for the authenticated user."""
    _space_id, user_id = ids
    space_ids = _member_space_ids(db, user_id)

    if not space_ids:
        return MeSummaryOut(
            pending_proposals_count=0,
            assigned_tasks_count=0,
            recent_runs=[],
            recent_participation=[],
            accessible_spaces_count=0,
        )

    pending_proposals_count = (
        db.query(Proposal)
        .filter(
            Proposal.space_id.in_(space_ids),
            Proposal.status == "pending",
        )
        .count()
    )

    assigned_tasks_count = (
        db.query(Task)
        .filter(
            Task.space_id.in_(space_ids),
            Task.deleted_at.is_(None),
            or_(
                Task.assigned_user_id == user_id,
                Task.created_by_user_id == user_id,
                Task.claimed_by_user_id == user_id,
            ),
        )
        .count()
    )

    recent_runs = (
        db.query(Run)
        .filter(
            Run.space_id.in_(space_ids),
            Run.instructed_by_user_id == user_id,
        )
        .order_by(Run.created_at.desc())
        .limit(recent_runs_limit)
        .all()
    )

    recent_participation = (
        db.query(ParticipationRecord)
        .filter(ParticipationRecord.user_id == user_id)
        .order_by(ParticipationRecord.occurred_at.desc())
        .limit(recent_participation_limit)
        .all()
    )

    return MeSummaryOut(
        pending_proposals_count=pending_proposals_count,
        assigned_tasks_count=assigned_tasks_count,
        recent_runs=[
            RecentRunMinimal(
                id=r.id,
                space_id=r.space_id,
                agent_id=r.agent_id,
                status=r.status,
                mode=r.mode,
                run_type=r.run_type,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in recent_runs
        ],
        recent_participation=[
            RecentParticipationMinimal(
                id=p.id,
                user_id=p.user_id,
                personal_space_id=p.personal_space_id,
                source_space_id=p.source_space_id,
                source_object_type=p.source_object_type,
                source_object_id=p.source_object_id,
                role=p.role,
                occurred_at=p.occurred_at,
                created_at=p.created_at,
            )
            for p in recent_participation
        ],
        accessible_spaces_count=len(space_ids),
    )


@router.get("/timeline", response_model=list[TimelineEntryOut])
def get_me_timeline(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[TimelineEntryOut]:
    """Ordered timeline from participation records.

    Returns pointer metadata only — no raw content from shared objects.
    """
    _space_id, user_id = ids

    participation_rows = (
        db.query(ParticipationRecord)
        .filter(ParticipationRecord.user_id == user_id)
        .order_by(ParticipationRecord.occurred_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        TimelineEntryOut(
            id=p.id,
            entry_type="participation",
            source_space_id=p.source_space_id,
            source_object_type=p.source_object_type,
            source_object_id=p.source_object_id,
            role=p.role,
            occurred_at=p.occurred_at,
            created_at=p.created_at,
        )
        for p in participation_rows
    ]


@router.get("/tasks", response_model=list[TaskMinimalOut])
def get_me_tasks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[TaskMinimalOut]:
    """Tasks across spaces where current user is assigned, created, or claimed.

    Applies visibility filter: private tasks only visible to owner.
    """
    _space_id, user_id = ids
    space_ids = _member_space_ids(db, user_id)
    if not space_ids:
        return []

    rows = (
        db.query(Task)
        .filter(
            Task.space_id.in_(space_ids),
            Task.deleted_at.is_(None),
            or_(
                Task.assigned_user_id == user_id,
                Task.created_by_user_id == user_id,
                Task.claimed_by_user_id == user_id,
            ),
        )
        .order_by(Task.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for task in rows:
        if not can_read_scoped_object(
            visibility=task.visibility,
            owner_user_id=_task_owner_user_id(task),
            current_user_id=user_id,
            is_space_member=True,  # already filtered to member spaces
        ):
            continue
        result.append(
            TaskMinimalOut(
                id=task.id,
                space_id=task.space_id,
                title=task.title,
                status=task.status,
                priority=task.priority,
                visibility=task.visibility,
                created_by_user_id=task.created_by_user_id,
                assigned_user_id=task.assigned_user_id,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
    return result


@router.get("/pending", response_model=list[ProposalMinimalOut])
def get_me_pending(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[ProposalMinimalOut]:
    """Pending proposals across spaces where current user is a member.

    Applies visibility filter: private proposals only visible to creator.
    """
    _space_id, user_id = ids
    space_ids = _member_space_ids(db, user_id)
    if not space_ids:
        return []

    rows = (
        db.query(Proposal)
        .filter(
            Proposal.space_id.in_(space_ids),
            Proposal.status == "pending",
        )
        .order_by(Proposal.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for proposal in rows:
        if not can_read_scoped_object(
            visibility=proposal.visibility,
            owner_user_id=_proposal_owner_user_id(proposal),
            current_user_id=user_id,
            is_space_member=True,  # already filtered to member spaces
        ):
            continue
        result.append(
            ProposalMinimalOut(
                id=proposal.id,
                space_id=proposal.space_id,
                proposal_type=proposal.proposal_type,
                status=proposal.status,
                urgency=proposal.urgency,
                title=proposal.title,
                visibility=proposal.visibility,
                created_by_user_id=proposal.created_by_user_id,
                created_at=proposal.created_at,
                updated_at=proposal.updated_at,
            )
        )
    return result
