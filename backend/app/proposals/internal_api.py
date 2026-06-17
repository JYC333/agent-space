"""Legacy internal proposal ports kept until Python backend deletion.

These routes are service-to-service boundaries only. The current TypeScript
control-plane proposal route no longer calls them; they remain for backend
compatibility and guard coverage until the Python service is retired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..memory import CodePatchApplyError, memory_proposal_apply_owned_by_ts
from ..participation.service import try_record_participation
from ..policy import ProposalRiskLevelError, get_policy_port
from ..schemas import ProposalAcceptOut, ProposalOut
from .api import _build_proposal_accept_out
from .approvals import (
    PersonalMemoryEgressApprovalError,
    infer_egress_grant_id,
    record_egress_granting_user_approval,
)
from .read_model import proposal_to_out
from .service import ProposalService


router = APIRouter(prefix="/internal/proposals-context", tags=["internal-proposals-context"])

_INTERNAL_TOKEN_HEADER = "x-agent-space-internal-token"

ProposalPortOperation = Literal[
    "proposal.accept",
    "proposal.reject",
    "proposal.egress_approval",
    "memory.apply_gate",
]


class ProposalPortDescriptor(BaseModel):
    operation: ProposalPortOperation
    owner: Literal["proposals"] = "proposals"
    implemented: bool
    auth: Literal["internal_service_token"] = "internal_service_token"
    writes: list[str] = Field(default_factory=list)
    notes: str | None = None


class ProposalPortsManifest(BaseModel):
    service: Literal["python_proposals_context_ports"] = "python_proposals_context_ports"
    ports: list[ProposalPortDescriptor]
    generated_at: datetime


class ProposalAcceptDispatchIn(BaseModel):
    proposal_id: str
    space_id: str
    user_id: str
    confirm_incomplete_patch: bool = False


class ProposalRejectDispatchIn(BaseModel):
    proposal_id: str
    space_id: str
    user_id: str


class ProposalEgressApprovalDispatchIn(BaseModel):
    proposal_id: str
    space_id: str
    user_id: str
    grant_id: str | None = None


class MemoryApplyGateIn(BaseModel):
    proposal_id: str
    space_id: str
    user_id: str


class MemoryApplyGateOut(BaseModel):
    """Gated, validated memory proposal returned to the TS apply path.

    The gate runs validation + the proposal.apply policy gate (writing the durable
    audit record) but does NOT apply or mark the proposal accepted — the TS accept
    path performs the active-memory writes and the accept state transition.
    """

    id: str
    space_id: str
    proposal_type: str
    payload_json: dict | None
    workspace_id: str | None
    created_by_user_id: str | None
    created_by_run_id: str | None
    title: str | None


_PORTS: tuple[ProposalPortDescriptor, ...] = (
    ProposalPortDescriptor(
        operation="proposal.accept",
        implemented=True,
        writes=[
            "proposals",
            "policy_decision_records",
            "memory/policy/tasks/agents/capabilities/knowledge per proposal type",
        ],
        notes=(
            "Wraps ProposalService.accept so policy gating, ProposalApplyService, "
            "code patch rollback, and participation side effects retain one "
            "Python transaction boundary while TS owns the public route."
        ),
    ),
    ProposalPortDescriptor(
        operation="proposal.reject",
        implemented=True,
        writes=["proposals", "participation_records best_effort"],
        notes="Wraps ProposalService.reject and the legacy best-effort participation side effect.",
    ),
    ProposalPortDescriptor(
        operation="proposal.egress_approval",
        implemented=True,
        writes=["proposal_approvals", "personal_memory_grant_events best_effort"],
        notes="Reuses grant-derived egress validation before writing the approval row.",
    ),
    ProposalPortDescriptor(
        operation="memory.apply_gate",
        implemented=True,
        writes=["policy_decision_records"],
        notes=(
            "Validates pending memory proposals and runs the proposal.apply policy "
            "gate for the TS memory apply path without mutating active memory or "
            "marking the proposal accepted."
        ),
    ),
)


def _require_internal_token(
    token: str | None = Header(default=None, alias=_INTERNAL_TOKEN_HEADER),
) -> None:
    configured = (settings.control_plane_internal_token or "").strip()
    presented = (token or "").strip()
    if not configured or not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/ports", response_model=ProposalPortsManifest)
def describe_proposal_context_ports(
    _: None = Depends(_require_internal_token),
) -> ProposalPortsManifest:
    return ProposalPortsManifest(ports=list(_PORTS), generated_at=datetime.now(UTC))


@router.post("/accept", response_model=ProposalAcceptOut)
def accept_proposal_via_internal_port(
    body: ProposalAcceptDispatchIn,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> ProposalAcceptOut:
    svc = ProposalService(db)

    visible_proposal = svc.get_proposal_for_viewer(body.proposal_id, body.space_id, body.user_id)
    # TS-owned memory proposal types must not be applied by this legacy Python
    # port. Check only after the space/viewer-scoped lookup so cross-space
    # proposal IDs still return 404 through the normal accept path instead of
    # leaking a 409 ownership signal.
    if visible_proposal is not None and memory_proposal_apply_owned_by_ts(
        visible_proposal.proposal_type
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Python no longer applies memory proposals; the TypeScript control "
                "plane applies memory_create/update/archive via its accept path."
            ),
        )

    if visible_proposal is not None and visible_proposal.proposal_type == "code_patch":
        payload = visible_proposal.payload_json or {}
        if payload.get("incomplete_patch") is True and not body.confirm_incomplete_patch:
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
        result = svc.accept(body.proposal_id, space_id=body.space_id, user_id=body.user_id)
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
        user_id=body.user_id,
        source_space_id=body.space_id,
        source_object_type="proposal",
        source_object_id=body.proposal_id,
        role="reviewed",
    )
    return _build_proposal_accept_out(result, space_id=body.space_id, user_id=body.user_id)


@router.post("/memory-apply-gate", response_model=MemoryApplyGateOut)
def memory_apply_gate_via_internal_port(
    body: MemoryApplyGateIn,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> MemoryApplyGateOut:
    """Validate + policy-gate an accepted memory proposal for the TS apply path.

    Legacy Stage 6 bridge retained for backend compatibility. It runs the same
    pending/preview/space validation and ``proposal.apply`` gate as
    ``ProposalService.accept`` (the gate writes the durable ALLOW record), but
    does not apply the proposal or mark it accepted. The current TS proposal
    apply path no longer calls this route.
    """
    svc = ProposalService(db)
    proposal = svc.get(body.proposal_id)
    if (
        proposal is None
        or proposal.status != "pending"
        or proposal.preview
        or proposal.space_id != body.space_id
    ):
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    if not memory_proposal_apply_owned_by_ts(proposal.proposal_type):
        raise HTTPException(
            status_code=409,
            detail="memory-apply-gate is only valid for TS-owned memory apply proposals",
        )

    try:
        get_policy_port(db).enforce_proposal_apply(
            user_id=body.user_id,
            space_id=body.space_id,
            proposal=proposal,
        )
    except ProposalRiskLevelError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_proposal_risk_level",
                "risk_value": exc.risk_value,
                "message": str(exc),
            },
        ) from exc
    # Persist the durable ALLOW audit the gate wrote (the apply transaction is TS).
    db.commit()

    return MemoryApplyGateOut(
        id=proposal.id,
        space_id=proposal.space_id,
        proposal_type=proposal.proposal_type,
        payload_json=proposal.payload_json,
        workspace_id=proposal.workspace_id,
        created_by_user_id=proposal.created_by_user_id,
        created_by_run_id=proposal.created_by_run_id,
        title=proposal.title,
    )


@router.post("/reject", response_model=ProposalOut)
def reject_proposal_via_internal_port(
    body: ProposalRejectDispatchIn,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> ProposalOut:
    svc = ProposalService(db)
    proposal = svc.reject(body.proposal_id, space_id=body.space_id, user_id=body.user_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    try_record_participation(
        db,
        user_id=body.user_id,
        source_space_id=body.space_id,
        source_object_type="proposal",
        source_object_id=body.proposal_id,
        role="reviewed",
    )
    return proposal_to_out(proposal, now=datetime.now(UTC))


@router.post("/approvals/egress-granting-user")
def approve_egress_granting_user_via_internal_port(
    body: ProposalEgressApprovalDispatchIn,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
):
    svc = ProposalService(db)
    proposal = svc.get(body.proposal_id)
    if proposal is None or proposal.space_id != body.space_id:
        raise HTTPException(status_code=404, detail="Proposal not found")

    grant_id = body.grant_id or infer_egress_grant_id(db, proposal)
    if not grant_id:
        raise HTTPException(status_code=422, detail="grant_id is required")
    try:
        approval = record_egress_granting_user_approval(
            db,
            proposal_id=body.proposal_id,
            grant_id=grant_id,
            approver_user_id=body.user_id,
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
