"""Space-scoped proposal list and review (accept/reject)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..memory.code_patch_apply import CodePatchApplyError
from ..memory.proposals import ProposalAcceptResult, ProposalService, UnsupportedProposalTypeError
from .list_params import resolve_proposal_list_status
from ..memory.serialization import memory_entry_to_out
from ..param_binding import wire_query
from ..schemas import Page, ProposalAcceptOut, ProposalOut
from .read_model import proposal_to_out

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _build_proposal_accept_out(
    result: ProposalAcceptResult,
    *,
    space_id: str,
    user_id: str,
) -> ProposalAcceptOut:
    now = datetime.now(UTC)
    prop_out = proposal_to_out(result.proposal, now=now)
    if result.updated_paths is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="code_patch_apply",
            result={"updated_paths": list(result.updated_paths)},
        )
    memory = result.memory
    assert memory is not None
    mem_out = memory_entry_to_out(
        memory,
        viewer_user_id=user_id,
        space_id=space_id,
        workspace_id=memory.workspace_id,
        include_system_scope=(memory.scope_type == "system"),
    )
    if mem_out is None:
        raise HTTPException(status_code=400, detail="Accepted memory is not visible to the current user")
    return ProposalAcceptOut(
        proposal=prop_out,
        result_type="memory_entry",
        result={"memory": mem_out.model_dump(mode="json")},
    )


@router.get("", response_model=Page[ProposalOut])
def list_proposals(
    status: str | None = Query(
        None,
        description="Proposal status filter. Omit for pending-only (review inbox default). "
        "Use `all` for every status; otherwise one of pending, accepted, rejected.",
    ),
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
    status_filter = resolve_proposal_list_status(status)
    svc = ProposalService(db)
    total = svc.count_proposals(
        space_id,
        user_id,
        status=status_filter,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        now=now,
    )
    items = svc.list_proposals(
        space_id,
        user_id,
        status=status_filter,
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
    svc = ProposalService(db)
    p = svc.get_proposal_for_viewer(proposal_id, space_id, user_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal_to_out(p, now=now)


@router.post("/{proposal_id}/accept", response_model=ProposalAcceptOut)
def accept_proposal(
    proposal_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ProposalService(db)
    try:
        result = svc.accept(proposal_id, space_id=space_id, user_id=user_id)
    except UnsupportedProposalTypeError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "unsupported_proposal_type",
                "proposal_type": exc.proposal_type,
            },
        ) from exc
    except CodePatchApplyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    return _build_proposal_accept_out(result, space_id=space_id, user_id=user_id)


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ProposalService(db)
    proposal = svc.reject(proposal_id, space_id=space_id, user_id=user_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    return proposal_to_out(proposal, now=datetime.now(UTC))
