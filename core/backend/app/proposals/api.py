"""Space-scoped proposal list and review (accept/reject)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..memory.code_patch_apply import CodePatchApplyError
from ..memory.proposals import (
    ProposalAcceptResult,
    ProposalService,
)
from ..policy.proposal_apply import ProposalRiskLevelError
from ..participation.service import try_record_participation
from .list_params import resolve_proposal_list_status
from ..memory.serialization import memory_entry_to_out
from ..param_binding import wire_query
from ..schemas import Page, ProposalAcceptOut, ProposalOut
from .read_model import proposal_to_out
from ..knowledge.read_model import knowledge_item_to_out, knowledge_relation_to_out

router = APIRouter(prefix="/proposals", tags=["proposals"])


class EgressGrantingUserApprovalIn(BaseModel):
    grant_id: str | None = None


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

    if result.policy is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="policy_version",
            result={"policy_id": result.policy.id, "policy_version": result.policy.policy_version},
        )

    if result.egress_review:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="egress_review",
            result={"approved_egress_review": True},
        )

    if result.task is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="follow_up_task",
            result={"task_id": result.task.id, "title": result.task.title},
        )

    if result.agent_version is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="agent_version",
            result={
                "agent_id": result.agent_version.agent_id,
                "agent_version_id": result.agent_version.id,
                "version_label": result.agent_version.version_label,
            },
        )

    if result.knowledge_item is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="knowledge_item",
            result={"knowledge_item": knowledge_item_to_out(result.knowledge_item).model_dump(mode="json")},
        )

    if result.knowledge_relation is not None:
        return ProposalAcceptOut(
            proposal=prop_out,
            result_type="knowledge_relation",
            result={"knowledge_relation": knowledge_relation_to_out(result.knowledge_relation).model_dump(mode="json")},
        )

    # memory_create, memory_update, memory_archive all surface the MemoryEntry.
    memory = result.memory
    if memory is None:
        raise HTTPException(status_code=500, detail="Accepted proposal produced no result")
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
    project_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    now = datetime.now(UTC)
    status_filter = resolve_proposal_list_status(status)
    svc = ProposalService(db)
    try:
        total = svc.count_proposals(
            space_id,
            user_id,
            status=status_filter,
            proposal_type=proposal_type,
            urgency=urgency,
            expired=expired,
            project_id=project_id,
            now=now,
        )
        items = svc.list_proposals(
            space_id,
            user_id,
            status=status_filter,
            proposal_type=proposal_type,
            urgency=urgency,
            expired=expired,
            project_id=project_id,
            limit=limit,
            offset=offset,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.post("/{proposal_id}/approvals/egress-granting-user")
def approve_egress_granting_user(
    proposal_id: str,
    body: EgressGrantingUserApprovalIn | None = None,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Record the granting user's explicit approval for one grant-derived proposal.

    The authenticated user must be the PersonalMemoryGrant.granting_user_id.
    """
    _, user_id = ids
    from .approvals import (
        PersonalMemoryEgressApprovalError,
        infer_egress_grant_id,
        record_egress_granting_user_approval,
    )

    svc = ProposalService(db)
    proposal = svc.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    grant_id = body.grant_id if body else None
    if not grant_id:
        grant_id = infer_egress_grant_id(db, proposal)
    if not grant_id:
        raise HTTPException(status_code=422, detail="grant_id is required")
    try:
        approval = record_egress_granting_user_approval(
            db,
            proposal_id=proposal_id,
            grant_id=grant_id,
            approver_user_id=user_id,
        )
        db.commit()
        db.refresh(approval)
    except PersonalMemoryEgressApprovalError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "id": approval.id,
        "proposal_id": approval.proposal_id,
        "approval_type": approval.approval_type,
        "approver_user_id": approval.approver_user_id,
        "grant_id": approval.grant_id,
        "target_space_id": approval.target_space_id,
        "status": approval.status,
        "metadata_json": approval.metadata_json,
        "created_at": approval.created_at,
        "revoked_at": approval.revoked_at,
    }


@router.post("/{proposal_id}/accept", response_model=ProposalAcceptOut)
def accept_proposal(
    proposal_id: str,
    confirm_incomplete_patch: bool = Query(
        False,
        description=(
            "Set to true to apply a code_patch proposal that has incomplete_patch=true "
            "(i.e. some agent file changes were skipped and the patch is partial). "
            "Omitting this flag or passing false causes the request to fail with "
            "incomplete_patch_requires_confirmation when the proposal is incomplete."
        ),
    ),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ProposalService(db)

    # Guard: incomplete code_patch proposals require explicit opt-in.
    # Use space-scoped visibility lookup to avoid leaking proposal existence across spaces.
    visible_proposal = svc.get_proposal_for_viewer(proposal_id, space_id, user_id)
    if visible_proposal is not None and visible_proposal.proposal_type == "code_patch":
        payload = visible_proposal.payload_json or {}
        if payload.get("incomplete_patch") is True and not confirm_incomplete_patch:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "incomplete_patch_requires_confirmation",
                    "message": (
                        "This code_patch proposal has incomplete_patch=true: some agent file "
                        "changes were skipped and the patch is partial. Pass "
                        "confirm_incomplete_patch=true to apply it anyway."
                    ),
                    "skipped_changes": payload.get("skipped_changes") or [],
                },
            )

    try:
        result = svc.accept(proposal_id, space_id=space_id, user_id=user_id)
    except ProposalRiskLevelError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_proposal_risk_level",
                "risk_value": exc.risk_value,
                "message": str(exc),
            },
        ) from exc
    except CodePatchApplyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    try_record_participation(
        db,
        user_id=user_id,
        source_space_id=space_id,
        source_object_type="proposal",
        source_object_id=proposal_id,
        role="reviewed",
    )
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
    try_record_participation(
        db,
        user_id=user_id,
        source_space_id=space_id,
        source_object_type="proposal",
        source_object_id=proposal_id,
        role="reviewed",
    )
    return proposal_to_out(proposal, now=datetime.now(UTC))
