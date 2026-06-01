"""Proposal approval gates for grant-derived egress.

One first-class approval type is supported: ``egress_granting_user``. Approval
rows are metadata-only and are the only proof accepted by the proposal apply gate.
Payload flags such as ``approved_by_granting_user`` are intentionally ignored.
"""

from __future__ import annotations
import uuid

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import PersonalMemoryGrant, Proposal, ProposalApproval, Run
from ..personal_memory_grants.validation import validate_grant_event_metadata

APPROVAL_TYPE_EGRESS_GRANTING_USER = "egress_granting_user"
STATUS_APPROVED = "approved"
STATUS_REVOKED = "revoked"


class PersonalMemoryEgressApprovalError(ValueError):
    """Raised when a grant-derived proposal lacks a valid granting-user approval."""


class GrantingUserApprovalRequired(PersonalMemoryEgressApprovalError):
    """Raised when no valid egress_granting_user approval row exists."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_aware(value)
    if isinstance(value, str) and value.strip():
        try:
            return _as_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _payload(proposal: Proposal) -> dict[str, Any]:
    return proposal.payload_json if isinstance(proposal.payload_json, dict) else {}


def _source_run_id(proposal: Proposal) -> str | None:
    payload = _payload(proposal)
    value = payload.get("source_run_id") or proposal.created_by_run_id
    return str(value) if value else None


def infer_egress_grant_id(db: Session, proposal: Proposal) -> str | None:
    """Infer the relevant grant_id from safe proposal/run metadata only."""
    payload = _payload(proposal)
    grant_id = payload.get("grant_id")
    if isinstance(grant_id, str) and grant_id:
        return grant_id

    grant_ids = payload.get("personal_memory_grant_ids")
    if isinstance(grant_ids, list) and len(grant_ids) == 1 and isinstance(grant_ids[0], str):
        return grant_ids[0]

    source_run_id = _source_run_id(proposal)
    if not source_run_id:
        return None
    run = db.query(Run).filter(Run.id == source_run_id).first()
    if run is None:
        return None
    ctx = run.personal_grant_context_json if isinstance(run.personal_grant_context_json, dict) else {}
    value = ctx.get("grant_id")
    return str(value) if value else None


def is_grant_derived_proposal(db: Session, proposal: Proposal) -> bool:
    """Return True when a proposal requires granting-user egress approval."""
    payload = _payload(proposal)
    if proposal.proposal_type == "egress_review":
        return True
    for key in (
        "personal_context_derived",
        "egress_guard_required",
        "derived_from_personal_memory",
        "raw_private_memory_included",
        "personal_summary_persisted",
    ):
        if payload.get(key):
            return True
    if payload.get("grant_id") or payload.get("personal_memory_grant_ids"):
        return True

    source_run_id = _source_run_id(proposal)
    if not source_run_id:
        return False
    run = db.query(Run).filter(Run.id == source_run_id).first()
    return bool(run and run.has_personal_grant_context)


def _validate_safe_payload_markers(proposal: Proposal) -> None:
    payload = _payload(proposal)
    if payload.get("raw_private_memory_included") is True:
        raise PersonalMemoryEgressApprovalError("raw_private_memory_included cannot be applied")
    if payload.get("personal_summary_persisted") is True:
        raise PersonalMemoryEgressApprovalError("personal_summary_persisted cannot be applied")
    target_visibility = str(payload.get("target_visibility") or payload.get("visibility") or proposal.visibility or "")
    if target_visibility == "public":
        raise PersonalMemoryEgressApprovalError("public target not allowed for grant-derived proposal")


def _validate_proposal_grant_binding(
    db: Session,
    *,
    proposal: Proposal,
    grant: PersonalMemoryGrant,
    grant_id: str,
) -> None:
    payload = _payload(proposal)
    payload_grant_id = payload.get("grant_id")
    if payload_grant_id is not None and str(payload_grant_id) != grant_id:
        raise PersonalMemoryEgressApprovalError("proposal grant_id does not match approval grant_id")

    payload_grant_ids = payload.get("personal_memory_grant_ids")
    if isinstance(payload_grant_ids, list) and grant_id not in [str(v) for v in payload_grant_ids]:
        raise PersonalMemoryEgressApprovalError("proposal personal_memory_grant_ids does not include approval grant_id")

    if payload.get("target_space_id") is not None and str(payload["target_space_id"]) != grant.target_space_id:
        raise PersonalMemoryEgressApprovalError("proposal target_space_id does not match grant target_space_id")
    if proposal.space_id != grant.target_space_id:
        raise PersonalMemoryEgressApprovalError("proposal space_id does not match grant target_space_id")

    source_run_id = _source_run_id(proposal)
    if not source_run_id:
        raise PersonalMemoryEgressApprovalError("grant-derived proposal is missing source_run_id")
    if source_run_id != grant.target_run_id:
        raise PersonalMemoryEgressApprovalError("proposal source_run_id does not match grant target_run_id")

    run = db.query(Run).filter(Run.id == source_run_id).first()
    if run is not None:
        if run.space_id != grant.target_space_id:
            raise PersonalMemoryEgressApprovalError("source run space does not match grant target_space_id")
        if run.instructed_by_user_id != grant.granting_user_id:
            raise PersonalMemoryEgressApprovalError("source run user does not match granting user")
        ctx = run.personal_grant_context_json if isinstance(run.personal_grant_context_json, dict) else {}
        run_grant_id = ctx.get("grant_id")
        if run.has_personal_grant_context and run_grant_id and str(run_grant_id) != grant_id:
            raise PersonalMemoryEgressApprovalError("source run grant context does not match approval grant_id")


def _validate_grant_status_and_deadline(
    *,
    proposal: Proposal,
    grant: PersonalMemoryGrant,
    now: datetime,
) -> None:
    if grant.status in {"revoked", "expired", "failed"}:
        raise PersonalMemoryEgressApprovalError(f"grant status {grant.status!r} cannot approve egress")

    deadlines = [
        _as_aware(grant.egress_review_expires_at),
        _as_aware(proposal.expires_at),
        _as_aware(proposal.review_deadline),
        _parse_dt(_payload(proposal).get("egress_review_expires_at")),
        _parse_dt(_payload(proposal).get("expires_at")),
    ]
    for deadline in [d for d in deadlines if d is not None]:
        if deadline <= now:
            raise PersonalMemoryEgressApprovalError("egress review deadline has passed")


def _find_valid_approval(
    db: Session,
    *,
    proposal: Proposal,
    grant: PersonalMemoryGrant,
    grant_id: str,
) -> ProposalApproval | None:
    approval = (
        db.query(ProposalApproval)
        .filter(
            ProposalApproval.proposal_id == proposal.id,
            ProposalApproval.approval_type == APPROVAL_TYPE_EGRESS_GRANTING_USER,
            ProposalApproval.approver_user_id == grant.granting_user_id,
            ProposalApproval.grant_id == grant_id,
            ProposalApproval.status == STATUS_APPROVED,
            ProposalApproval.revoked_at.is_(None),
        )
        .order_by(ProposalApproval.created_at.desc())
        .first()
    )
    if approval is None:
        return None
    if approval.created_at and proposal.created_at:
        if _as_aware(approval.created_at) < _as_aware(proposal.created_at):
            return None
    return approval


def _write_egress_approved_event(
    db: Session,
    *,
    grant: PersonalMemoryGrant,
    approval: ProposalApproval,
) -> None:
    """Write an 'egress_approved' audit event. Never propagates on failure."""
    import logging
    from ..models import PersonalMemoryGrantEvent

    log = logging.getLogger(__name__)
    metadata = {
        "proposal_id": str(approval.proposal_id),
        "approval_type": APPROVAL_TYPE_EGRESS_GRANTING_USER,
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
        "phase": "E",
    }
    try:
        validate_grant_event_metadata(metadata)
    except Exception:
        log.warning("egress_approved event metadata validation failed; skipping event write")
        return

    event = PersonalMemoryGrantEvent(
        id=_new_id(),
        grant_id=grant.id,
        event_type="egress_approved",
        target_space_id=grant.target_space_id,
        metadata_json=metadata,
    )
    db.add(event)
    try:
        db.flush()
    except Exception:
        log.warning("Failed to write egress_approved event; continuing", exc_info=True)


def record_egress_granting_user_approval(
    db: Session,
    *,
    proposal_id: str,
    grant_id: str,
    approver_user_id: str,
) -> ProposalApproval:
    """Create or return an active egress_granting_user approval row.

    Only the grant's granting user can create this row. Space admins and other
    members cannot approve on their behalf.
    """
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    grant = db.query(PersonalMemoryGrant).filter(PersonalMemoryGrant.id == grant_id).first()
    if proposal is None:
        raise PersonalMemoryEgressApprovalError("proposal not found")
    if grant is None:
        raise PersonalMemoryEgressApprovalError("grant not found")
    if grant.granting_user_id != approver_user_id:
        raise PersonalMemoryEgressApprovalError("only granting_user_id can approve grant-derived egress")

    now = _utcnow()
    _validate_safe_payload_markers(proposal)
    _validate_proposal_grant_binding(db, proposal=proposal, grant=grant, grant_id=grant_id)
    _validate_grant_status_and_deadline(proposal=proposal, grant=grant, now=now)

    existing = _find_valid_approval(db, proposal=proposal, grant=grant, grant_id=grant_id)
    if existing is not None:
        return existing

    metadata = {
        "approval_type": APPROVAL_TYPE_EGRESS_GRANTING_USER,
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
    }
    validate_grant_event_metadata(metadata)

    approval = ProposalApproval(
        id=_new_id(),
        proposal_id=proposal.id,
        approval_type=APPROVAL_TYPE_EGRESS_GRANTING_USER,
        approver_user_id=approver_user_id,
        grant_id=grant_id,
        target_space_id=grant.target_space_id,
        status=STATUS_APPROVED,
        metadata_json=metadata,
    )
    db.add(approval)
    db.flush()
    _write_egress_approved_event(db, grant=grant, approval=approval)
    return approval


def has_valid_egress_granting_user_approval(
    db: Session,
    *,
    proposal_id: str,
    grant_id: str,
    granting_user_id: str,
) -> bool:
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    grant = db.query(PersonalMemoryGrant).filter(PersonalMemoryGrant.id == grant_id).first()
    if proposal is None or grant is None or grant.granting_user_id != granting_user_id:
        return False
    try:
        validate_egress_granting_user_approval(db, proposal=proposal, grant_id=grant_id)
    except PersonalMemoryEgressApprovalError:
        return False
    return True


def validate_egress_granting_user_approval(
    db: Session,
    *,
    proposal: Proposal,
    grant_id: str | None = None,
) -> ProposalApproval:
    """Return a valid granting-user approval or raise a gate error."""
    _validate_safe_payload_markers(proposal)
    effective_grant_id = grant_id or infer_egress_grant_id(db, proposal)
    if not effective_grant_id:
        raise GrantingUserApprovalRequired("GrantingUserApprovalRequired: missing grant_id for egress proposal")

    grant = db.query(PersonalMemoryGrant).filter(PersonalMemoryGrant.id == effective_grant_id).first()
    if grant is None:
        raise PersonalMemoryEgressApprovalError("grant not found")

    now = _utcnow()
    _validate_proposal_grant_binding(db, proposal=proposal, grant=grant, grant_id=effective_grant_id)
    _validate_grant_status_and_deadline(proposal=proposal, grant=grant, now=now)

    approval = _find_valid_approval(db, proposal=proposal, grant=grant, grant_id=effective_grant_id)
    if approval is None:
        raise GrantingUserApprovalRequired("GrantingUserApprovalRequired: egress_granting_user approval required")
    return approval


def revoke_proposal_approval(
    db: Session,
    *,
    approval_id: str,
    approver_user_id: str,
) -> ProposalApproval:
    approval = db.query(ProposalApproval).filter(ProposalApproval.id == approval_id).first()
    if approval is None or approval.approver_user_id != approver_user_id:
        raise PersonalMemoryEgressApprovalError("approval not found")
    approval.status = STATUS_REVOKED
    approval.revoked_at = _utcnow()
    db.flush()
    return approval


def list_proposal_approvals(db: Session, *, proposal_id: str) -> list[ProposalApproval]:
    return (
        db.query(ProposalApproval)
        .filter(ProposalApproval.proposal_id == proposal_id)
        .order_by(ProposalApproval.created_at.asc())
        .all()
    )
