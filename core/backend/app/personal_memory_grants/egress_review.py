"""PersonalMemoryGrant F2 — sanitized egress_review proposal builder.

When grant-derived output materialization is blocked by the egress guard for a
non-personal target space, this module creates a metadata-only egress_review
proposal for the granting user to review.

Safety invariants:
- Proposal payload contains NO output text, adapter output, artifact content,
  raw memory, generated summary, personal_context_block, memory IDs, or
  source memory titles/snippets.
- Only safe grant/run metadata is stored (IDs, counts, boolean flags, mode).
- grant_id and granting_user_id MUST be present; if either is missing the
  builder fails closed and returns None (caller falls back to error-only path).
- Only created when source_run.has_personal_grant_context is True.
- Only created for non-personal target spaces.
- Deduplication: returns an existing open egress_review proposal if one already
  exists for the same (created_by_run_id, target_space_id, target_object_type,
  operation, grant_id) tuple. A deterministic ``egress_review_dedupe_key`` is
  stored in the payload and matched in Python — no SQLite JSON path dependency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from ulid import ULID

log = logging.getLogger(__name__)

# Keys that must NEVER appear in egress_review proposal payload.
_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "content",
    "body",
    "raw_content",
    "payload",
    "summary",
    "generated_summary",
    "personal_context_block",
    "memory_text",
    "personal_memory_text",
    "artifact_payload",
    "output_text",
    "adapter_output",
    "source_snapshot",
    "memory_ids",
    "personal_memory_ids",
})


def _new_id() -> str:
    return str(ULID())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _write_egress_proposal_created_event(
    db: Session,
    *,
    grant_id: str,
    proposal_id: str,
    run_id: str,
    target_space_id: str,
    target_object_type: str,
    operation: str,
) -> None:
    """Write an 'egress_proposal_created' audit event. Never propagates on failure."""
    from ..models import PersonalMemoryGrantEvent
    from ..personal_memory_grants.validation import validate_grant_event_metadata

    metadata = {
        "proposal_id": str(proposal_id),
        "operation": str(operation)[:64],
        "target_object_type": str(target_object_type)[:64],
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
        "phase": "F2",
    }
    try:
        validate_grant_event_metadata(metadata)
    except Exception:
        log.warning("egress_proposal_created event metadata validation failed; skipping event write")
        return

    event = PersonalMemoryGrantEvent(
        id=_new_id(),
        grant_id=grant_id,
        event_type="egress_proposal_created",
        run_id=run_id,
        target_space_id=target_space_id,
        metadata_json=metadata,
    )
    db.add(event)
    try:
        db.flush()
    except Exception:
        log.warning(
            "Failed to write egress_proposal_created event for proposal %s; continuing",
            proposal_id,
            exc_info=True,
        )


def _assert_no_forbidden_keys(payload: dict) -> None:
    """Raise if any forbidden content key is present in the payload."""
    found = [k for k in _FORBIDDEN_PAYLOAD_KEYS if k in payload]
    if found:
        raise ValueError(
            f"egress_review proposal payload contains forbidden keys: {found!r}"
        )


def _compute_dedupe_key(
    *,
    run_id: str,
    target_space_id: str,
    target_object_type: str,
    operation: str,
    grant_id: str,
) -> str:
    """Compute a deterministic, content-free dedupe key from safe metadata IDs.

    The key contains only ULIDs/IDs and short operation-type labels — no personal
    content, no raw memory text, no output text.
    """
    return "|".join([
        str(run_id),
        str(target_space_id),
        str(target_object_type)[:64],
        str(operation)[:64],
        str(grant_id),
    ])


def _find_existing_open_proposal(
    db: Session,
    *,
    run_id: str,
    target_space_id: str,
    target_object_type: str,
    operation: str,
    grant_id: str,
) -> "Optional[object]":
    """Return an open egress_review proposal for the same run/space/type/op/grant, if any.

    Queries using only stable non-JSON-path columns (created_by_run_id, proposal_type,
    status), then filters candidates in Python by egress_review_dedupe_key. This avoids
    any SQLite JSON path dependency that may not be available on older SQLite versions.
    """
    from ..models import Proposal

    dedupe_key = _compute_dedupe_key(
        run_id=run_id,
        target_space_id=target_space_id,
        target_object_type=target_object_type,
        operation=operation,
        grant_id=grant_id,
    )

    # Use only stable ORM columns for the DB query — no JSON path operators
    candidates = (
        db.query(Proposal)
        .filter(
            Proposal.created_by_run_id == run_id,
            Proposal.proposal_type == "egress_review",
            Proposal.status == "pending",
        )
        .order_by(Proposal.created_at.desc())
        .limit(20)  # bounded; one run rarely has more than a few egress_review proposals
        .all()
    )

    for candidate in candidates:
        payload = candidate.payload_json
        if not isinstance(payload, dict):
            continue
        # Primary match: stable dedupe key stored at proposal creation time
        if payload.get("egress_review_dedupe_key") == dedupe_key:
            return candidate
        # Read-time tolerance: stored proposals written before F2.1 lack egress_review_dedupe_key
        if (
            payload.get("target_space_id") == target_space_id
            and payload.get("target_object_type") == target_object_type
            and payload.get("operation") == operation
            and payload.get("grant_id") == grant_id
        ):
            return candidate
    return None


def create_egress_review_proposal(
    db: Session,
    *,
    source_run,
    target_space_id: str,
    target_object_type: str,
    target_visibility: Optional[str] = None,
    operation: str,
    egress_result,
    materialization_kind: Optional[str] = None,
) -> "Optional[object]":
    """Create a sanitized egress_review proposal when grant-derived materialization is blocked.

    Returns the Proposal ORM object (new or existing), or None when the builder
    fails closed (e.g. missing grant_id/granting_user_id, personal target,
    non-grant-derived run).

    The returned proposal is flushed but NOT committed — callers own the
    transaction boundary.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    source_run:
        The Run ORM row that produced the blocked output.
    target_space_id:
        Target space where materialization was blocked.
    target_object_type:
        "artifact" | "memory_proposal" | etc.
    target_visibility:
        Optional visibility string of the target object.
    operation:
        Short operation label, e.g. "artifact_materialization".
    egress_result:
        EgressCheckResult from check_personal_memory_egress.
    materialization_kind:
        Optional hint about the kind of materialization (e.g. "adapter_artifact").
    """
    from ..models import Proposal, Space

    # --- Guard: only create when run has personal grant context ---
    if not getattr(source_run, "has_personal_grant_context", False):
        log.debug("create_egress_review_proposal: run %s has no personal grant context; skip", source_run.id)
        return None

    # --- Guard: only for non-personal targets ---
    target_space = db.query(Space).filter(Space.id == target_space_id).first()
    if target_space is not None and target_space.type == "personal":
        log.debug(
            "create_egress_review_proposal: target space %s is personal; no egress_review needed",
            target_space_id,
        )
        return None

    # --- Extract safe grant metadata from run context ---
    ctx = getattr(source_run, "personal_grant_context_json", None) or {}
    grant_id = ctx.get("grant_id") if isinstance(ctx, dict) else None
    granting_user_id = ctx.get("granting_user_id") if isinstance(ctx, dict) else None

    # --- Fail closed if essential metadata is missing ---
    if not grant_id or not granting_user_id:
        log.warning(
            "create_egress_review_proposal: run %s missing grant_id or granting_user_id; "
            "failing closed — no egress_review proposal created",
            source_run.id,
        )
        return None

    user_id = source_run.instructed_by_user_id or granting_user_id

    # --- Compute dedupe key before querying (content-free: IDs + operation types only) ---
    dedupe_key = _compute_dedupe_key(
        run_id=str(source_run.id),
        target_space_id=str(target_space_id),
        target_object_type=str(target_object_type)[:64],
        operation=str(operation)[:64],
        grant_id=str(grant_id),
    )

    # --- Deduplication: reuse open proposal for same run/space/type/op/grant ---
    existing = _find_existing_open_proposal(
        db,
        run_id=source_run.id,
        target_space_id=target_space_id,
        target_object_type=target_object_type,
        operation=operation,
        grant_id=grant_id,
    )
    if existing is not None:
        log.debug(
            "create_egress_review_proposal: reusing existing proposal %s for run %s",
            existing.id,
            source_run.id,
        )
        return existing

    # --- Build safe metadata-only payload ---
    now = _utcnow()
    payload: dict = {
        "source_run_id": str(source_run.id),
        "target_space_id": str(target_space_id),
        "target_object_type": str(target_object_type)[:64],
        "target_visibility": str(target_visibility or "unknown")[:32],
        "operation": str(operation)[:64],
        "grant_id": str(grant_id),
        "granting_user_id": str(granting_user_id),
        # Safe counts/flags from run context only
        "personal_space_id": str(ctx.get("personal_space_id", ""))[:64] or None,
        "access_mode": str(ctx.get("access_mode", "summary_only"))[:32],
        "memory_count": int(ctx.get("memory_count", 0)) if isinstance(ctx.get("memory_count"), (int, float)) else 0,
        # Safety flags — always False for F2
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
        "derived_from_personal_memory": True,
        "egress_guard_required": True,
        # Approval requirements
        "requires_approval_type": "egress_granting_user",
        "required_approver_user_id": str(granting_user_id),
        # Review status
        "review_status": "manual_required",
        "semantic_review_status": "not_performed",
        "content_attached": False,
        # Phase marker
        "phase": "F2",
        # Stable dedupe key for Python-side matching (content-free: IDs + types only)
        "egress_review_dedupe_key": dedupe_key,
    }
    if materialization_kind:
        payload["materialization_kind"] = str(materialization_kind)[:64]

    # Assert no forbidden keys slipped through
    _assert_no_forbidden_keys(payload)

    proposal = Proposal(
        id=_new_id(),
        space_id=target_space_id,
        proposal_type="egress_review",
        status="pending",
        risk_level="high",
        urgency="normal",
        title="Grant-derived egress review",
        summary=None,
        payload_json=payload,
        rationale=(
            "Grant-derived output was blocked from direct persistence to a non-personal target. "
            "Granting-user approval is required before any shared persistence can proceed."
        ),
        created_by_user_id=user_id,
        created_by_run_id=source_run.id,
        review_deadline=now + timedelta(hours=48),
        expires_at=now + timedelta(days=14),
    )
    db.add(proposal)
    try:
        db.flush()
    except Exception:
        log.warning(
            "create_egress_review_proposal: flush failed for run %s; falling back to error-only path",
            source_run.id,
            exc_info=True,
        )
        db.rollback()
        return None

    log.info(
        "create_egress_review_proposal: created proposal %s for run %s → target_space %s [%s]",
        proposal.id,
        source_run.id,
        target_space_id,
        target_object_type,
    )
    _write_egress_proposal_created_event(
        db,
        grant_id=grant_id,
        proposal_id=proposal.id,
        run_id=str(source_run.id),
        target_space_id=target_space_id,
        target_object_type=target_object_type,
        operation=operation,
    )
    return proposal
