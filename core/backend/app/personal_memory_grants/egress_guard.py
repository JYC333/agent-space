"""PersonalMemoryGrant egress guard.

Prevents grant-derived output from being silently written to shared/non-personal targets.

MVP rule:
- If a run has has_personal_grant_context=True (set by ContextSnapshotPopulator), or
  if output_metadata contains grant-derived indicators, direct persistence to a
  non-personal target space is BLOCK.
- Personal-space targets are allowed.
- Public targets are always blocked for grant-derived output.
- Non-grant-derived output is unchanged.

Granting-user approval gate is enforced in ProposalApplyService via proposal_approvals.

Security invariants:
- Denied events never contain raw memory text, generated summary, or memory IDs.
- Grant detection uses only the persisted safe marker on Run, never re-reads personal memory.
- Unknown space type fails closed (treats as non-personal → block).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Keys in output_metadata that indicate grant-derived content.
_GRANT_DERIVED_INDICATOR_KEYS = frozenset({
    "derived_from_personal_memory",
    "personal_memory_grant_ids",
    "raw_private_memory_included",
    "personal_summary_persisted",
})


class EgressDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_REVIEW = "require_review"


@dataclass
class EgressCheckResult:
    decision: EgressDecision
    reason: str
    grant_id: Optional[str] = None
    requires_proposal: bool = False


class PersonalMemoryEgressError(Exception):
    """Raised when egress guard blocks direct persistence of grant-derived output.

    Callers of RunOutputMaterializer / ArtifactPersistenceService must not swallow
    this exception without logging — it signals a policy violation, not a transient error.
    """

    def __init__(self, reason: str, grant_id: Optional[str] = None) -> None:
        self.reason = reason
        self.grant_id = grant_id
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_grant_derived_from_run(run) -> bool:
    return bool(getattr(run, "has_personal_grant_context", False))


def _is_grant_derived_from_metadata(output_metadata: dict | None) -> bool:
    if not output_metadata:
        return False
    for key in _GRANT_DERIVED_INDICATOR_KEYS:
        val = output_metadata.get(key)
        if val:
            return True
    return False


def _get_grant_id_from_run(run) -> Optional[str]:
    ctx = getattr(run, "personal_grant_context_json", None) or {}
    return ctx.get("grant_id") if isinstance(ctx, dict) else None


def _is_non_personal_space(db: Session, space_id: str) -> bool:
    """True when space type is not 'personal'. Fails closed for unknown spaces."""
    from ..models import Space
    space = db.query(Space).filter(Space.id == space_id).first()
    if space is None:
        log.warning("Egress guard: space %r not found; treating as non-personal (fail-closed)", space_id)
        return True
    return space.type != "personal"


def _write_denied_event(
    db: Session,
    *,
    grant_id: str,
    run_id: Optional[str],
    target_space_id: str,
    target_object_type: str,
    reason: str,
    operation: str,
) -> None:
    """Write a 'denied' audit event to personal_memory_grant_events.

    Metadata never contains output text, personal summary, raw memory, or memory IDs.
    """
    from ..personal_memory_grants.validation import validate_grant_event_metadata
    from ..models import PersonalMemoryGrantEvent
    from ulid import ULID

    metadata = {
        "reason": reason[:256],
        "operation": operation[:64],
        "target_object_type": target_object_type[:64],
        "raw_private_memory_included": False,
        "requires_proposal": False,
        "phase": "D",
    }
    try:
        validate_grant_event_metadata(metadata)
    except Exception:
        log.warning("Egress denied event metadata validation failed; skipping event write")
        return

    event = PersonalMemoryGrantEvent(
        id=str(ULID()),
        grant_id=grant_id,
        event_type="denied",
        run_id=run_id,
        target_space_id=target_space_id,
        metadata_json=metadata,
    )
    db.add(event)
    try:
        db.flush()
    except Exception:
        log.warning("Failed to write egress denied event; proceeding with block", exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_personal_memory_egress(
    db: Session,
    *,
    run=None,
    target_space_id: str,
    target_object_type: str,
    target_visibility: Optional[str] = None,
    output_metadata: Optional[dict] = None,
    operation: str,
) -> EgressCheckResult:
    """Check whether output can be persisted to a target space/object.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    run:
        The source Run ORM row (may be None when checking without a run context).
    target_space_id:
        ID of the space where output would be persisted.
    target_object_type:
        Logical object type being persisted (e.g. "artifact", "memory", "source_pointer").
    target_visibility:
        Visibility string if known (e.g. "space_shared", "private", "public").
    output_metadata:
        Optional dict of output-level metadata that may carry grant-derived indicators.
    operation:
        Short label for the operation being attempted (e.g. "direct_persist", "proposal_create").

    Returns
    -------
    EgressCheckResult with decision == ALLOW or BLOCK.
    """
    # --- Determine grant-derived status ---
    is_grant_derived = False
    grant_id: Optional[str] = None
    run_id: Optional[str] = None

    if run is not None:
        if _is_grant_derived_from_run(run):
            is_grant_derived = True
            grant_id = _get_grant_id_from_run(run)
            run_id = getattr(run, "id", None)

    if not is_grant_derived and _is_grant_derived_from_metadata(output_metadata):
        is_grant_derived = True

    if not is_grant_derived:
        return EgressCheckResult(decision=EgressDecision.ALLOW, reason="no_grant_context")

    # --- Hard block: raw_private_memory_included in output metadata ---
    if (output_metadata or {}).get("raw_private_memory_included"):
        reason = "raw_private_memory_included_in_output"
        if grant_id:
            _write_denied_event(
                db,
                grant_id=grant_id,
                run_id=run_id,
                target_space_id=target_space_id,
                target_object_type=target_object_type,
                reason=reason,
                operation=operation,
            )
        return EgressCheckResult(
            decision=EgressDecision.BLOCK,
            reason=reason,
            grant_id=grant_id,
        )

    # --- Hard block: public target ---
    if target_visibility == "public":
        reason = "public_target_not_allowed_for_grant_derived_output"
        if grant_id:
            _write_denied_event(
                db,
                grant_id=grant_id,
                run_id=run_id,
                target_space_id=target_space_id,
                target_object_type=target_object_type,
                reason=reason,
                operation=operation,
            )
        return EgressCheckResult(
            decision=EgressDecision.BLOCK,
            reason=reason,
            grant_id=grant_id,
        )

    # --- Block non-personal target ---
    if _is_non_personal_space(db, target_space_id):
        reason = (
            "egress_review_required_phase_e: "
            "grant-derived output cannot be directly persisted to a non-personal target; "
            "granting-user approval is required before proposal apply"
        )
        if grant_id:
            _write_denied_event(
                db,
                grant_id=grant_id,
                run_id=run_id,
                target_space_id=target_space_id,
                target_object_type=target_object_type,
                reason="direct_persist_to_non_personal_blocked_phase_d",
                operation=operation,
            )
        return EgressCheckResult(
            decision=EgressDecision.BLOCK,
            reason=reason,
            grant_id=grant_id,
            requires_proposal=True,
        )

    # --- Allow personal-space target ---
    return EgressCheckResult(
        decision=EgressDecision.ALLOW,
        reason="personal_space_target_allowed",
        grant_id=grant_id,
    )


# ---------------------------------------------------------------------------
# Source pointer egress check
# ---------------------------------------------------------------------------

# Keys in SourcePointer metadata that must not appear when owner_space is non-personal.
_SOURCE_POINTER_GRANT_INDICATOR_KEYS = frozenset({
    "derived_from_personal_memory",
    "personal_memory_grant_ids",
    "raw_private_memory_included",
    "personal_summary_persisted",
})


def check_source_pointer_metadata_egress(
    db: Session,
    *,
    owner_space_id: str,
    metadata_json: Optional[dict],
) -> EgressCheckResult:
    """Reject SourcePointer creation if metadata carries grant-derived content indicators
    and the owner_space is non-personal.

    This prevents SourcePointer metadata from becoming an egress channel for
    grant-derived personal context into shared spaces.
    """
    if not metadata_json:
        return EgressCheckResult(decision=EgressDecision.ALLOW, reason="no_metadata")

    # Check for grant-derived indicator keys
    found_keys = [k for k in _SOURCE_POINTER_GRANT_INDICATOR_KEYS if k in metadata_json]
    if not found_keys:
        return EgressCheckResult(decision=EgressDecision.ALLOW, reason="no_grant_indicators")

    # Found grant-derived indicators — check owner space type
    if _is_non_personal_space(db, owner_space_id):
        reason = (
            f"source_pointer_metadata_contains_grant_derived_indicators={found_keys!r}; "
            "these keys are not allowed in non-personal owner_space"
        )
        return EgressCheckResult(
            decision=EgressDecision.BLOCK,
            reason=reason,
        )

    # Personal space — allow
    return EgressCheckResult(decision=EgressDecision.ALLOW, reason="personal_space_target_allowed")
