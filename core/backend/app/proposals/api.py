"""Space-scoped proposal list (read-only filters)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..param_binding import wire_query
from .read_model import proposal_to_out
from ..memory.proposals import MemoryProposalService
from ..schemas import Page, ProposalOut

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("", response_model=Page[ProposalOut])
def list_proposals(
    status: str | None = Query(None),
    proposal_type: str | None = wire_query(None, wire_name="type"),
    urgency: str | None = Query(None),
    expired: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    now = datetime.now(UTC)
    svc = MemoryProposalService(db)
    total = svc.count_proposals(
        space_id,
        user_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        now=now,
    )
    items = svc.list_proposals(
        space_id,
        user_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        limit=limit,
        offset=offset,
        now=now,
    )
    return Page(
        items=[proposal_to_out(p, now=now) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{proposal_id}", response_model=ProposalOut)
def get_proposal(
    proposal_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Single proposal visible to the current user in this space (same rules as list)."""
    space_id, user_id = ids
    now = datetime.now(UTC)
    svc = MemoryProposalService(db)
    p = svc.get_proposal_for_viewer(proposal_id, space_id, user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal_to_out(p, now=now)
