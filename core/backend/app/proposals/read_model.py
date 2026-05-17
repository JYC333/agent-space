"""Proposal HTTP read model: urgency, deadlines, and computed ``expired``.

Used by global proposal routes, run proposal sub-resources, **task proposal
lists**, memory review routes, and session reflect — not memory-store
specific logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..models import Proposal
from ..schemas import ProposalOut, ProposalSummaryOut

# Proposal statuses treated as still in human review for expiry semantics.
REVIEWABLE_PROPOSAL_STATUSES = frozenset({"pending"})


def _to_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_proposal_expired(proposal: Proposal, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if proposal.status not in REVIEWABLE_PROPOSAL_STATUSES:
        return False
    if proposal.expires_at is None:
        return False
    return _to_utc_aware(proposal.expires_at) < _to_utc_aware(now)


def _active_egress_approval(proposal: Proposal):
    for approval in proposal.approvals or []:
        if (
            approval.approval_type == "egress_granting_user"
            and approval.status == "approved"
            and approval.revoked_at is None
        ):
            return approval
    return None


def proposal_to_out(proposal: Proposal, *, now: datetime | None = None) -> ProposalOut:
    """Build canonical ProposalOut including computed ``expired`` (not persisted)."""
    from ..memory.proposal_payload import provenance_entries_from_payload

    now = now or datetime.now(UTC)
    expired = compute_proposal_expired(proposal, now=now)
    payload = proposal.payload_json or {}
    prov = provenance_entries_from_payload(payload)
    approval = _active_egress_approval(proposal)
    required_approver_user_id = payload.get("required_approver_user_id")
    if not isinstance(required_approver_user_id, str):
        required_approver_user_id = payload.get("granting_user_id")
    if not isinstance(required_approver_user_id, str):
        required_approver_user_id = None
    return ProposalOut(
        id=proposal.id,
        space_id=proposal.space_id,
        user_id=proposal.created_by_user_id or "",
        workspace_id=proposal.workspace_id,
        source_session_id=proposal.source_session_id,
        source_task_id=proposal.source_task_id,
        source_run_id=proposal.source_run_id,
        created_by_run_id=proposal.created_by_run_id,
        proposal_type=proposal.proposal_type,
        target_scope=proposal.target_scope,
        target_namespace=proposal.target_namespace,
        memory_type=proposal.memory_type,
        proposed_title=proposal.proposed_title,
        proposed_content=proposal.proposed_content,
        rationale=proposal.rationale or "",
        status=proposal.status,
        risk_level=proposal.risk_level,
        urgency=proposal.urgency,
        visibility=proposal.visibility,
        preview=bool(getattr(proposal, "preview", False)),
        review_deadline=proposal.review_deadline,
        expires_at=proposal.expires_at,
        expired=expired,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        resulting_memory_id=proposal.resulting_memory_id,
        owner_user_id=proposal.owner_user_id,
        subject_user_id=proposal.subject_user_id,
        sensitivity_level=proposal.sensitivity_level,
        selected_user_ids=proposal.selected_user_ids,
        provenance_entries=prov or None,
        source_activity_id=proposal.source_activity_id,
        grant_id=payload.get("grant_id") if isinstance(payload.get("grant_id"), str) else None,
        required_approver_user_id=required_approver_user_id,
        requires_approval_type=(
            payload.get("requires_approval_type")
            if isinstance(payload.get("requires_approval_type"), str)
            else None
        ),
        egress_approval_status=approval.status if approval else None,
        egress_approval_id=approval.id if approval else None,
    )


def proposal_to_summary_out(proposal: Proposal, *, now: datetime | None = None) -> ProposalSummaryOut:
    """Compact proposal row for task/session summaries; ``expired`` via ``compute_proposal_expired`` only."""
    now = now or datetime.now(UTC)
    expired = compute_proposal_expired(proposal, now=now)
    return ProposalSummaryOut(
        id=proposal.id,
        space_id=proposal.space_id,
        proposal_type=proposal.proposal_type,
        status=proposal.status,
        title=proposal.title,
        visibility=proposal.visibility,
        created_at=proposal.created_at,
        preview=bool(getattr(proposal, "preview", False)),
        urgency=proposal.urgency,
        review_deadline=proposal.review_deadline,
        expires_at=proposal.expires_at,
        expired=expired,
        created_by_run_id=proposal.created_by_run_id,
    )
