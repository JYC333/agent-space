"""PersonalMemoryGrant lifecycle service.

Creates, revokes, lists, and audits PersonalMemoryGrants.
Does NOT connect grants to ContextBuilder.
Does NOT implement grant resolver for memory retrieval.
Does NOT implement consuming/used transitions.
"""
from __future__ import annotations
import uuid

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    PersonalMemoryGrant,
    PersonalMemoryGrantEvent,
    Run,
    Space,
    SpaceMembership,
)
from .validation import (
    InvalidGrantEventMetadataError,
    InvalidGrantFilterError,
    validate_grant_event_metadata,
    validate_memory_filter,
)

# ---------------------------------------------------------------------------
# Rate limit constants
# ---------------------------------------------------------------------------

MAX_ACTIVE_CONSUMING_GRANTS = 10
MAX_GRANTS_PER_HOUR = 20


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class PersonalSpaceNotFoundError(ValueError):
    """User has no personal space (type='personal') with active membership."""


class TargetSpaceMembershipError(ValueError):
    """User is not an active member of target_space_id."""


class TargetRunNotFoundError(ValueError):
    """Target run does not exist."""


class TargetRunSpaceMismatchError(ValueError):
    """Target run is not in target_space_id."""


class TargetRunOwnershipError(ValueError):
    """run.instructed_by_user_id != granting_user_id."""


class InvalidAccessModeError(ValueError):
    """access_mode is not 'summary_only'."""


class RateLimitExceededError(ValueError):
    """Active/consuming or hourly grant rate limit exceeded."""


class DuplicateGrantError(ValueError):
    """Active/consuming grant already exists for (granting_user_id, target_run_id)."""


class GrantNotFoundError(ValueError):
    """Grant not found or not owned by the requesting user."""


class GrantAlreadyTerminalError(ValueError):
    """Grant is already in a terminal state (revoked/used/expired/failed)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _find_personal_space(db: Session, user_id: str) -> Space:
    """Return the user's personal space. Raises PersonalSpaceNotFoundError if none found."""
    space = (
        db.query(Space)
        .join(SpaceMembership, SpaceMembership.space_id == Space.id)
        .filter(
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
            Space.type == "personal",
        )
        .first()
    )
    if space is None:
        raise PersonalSpaceNotFoundError(
            f"No personal space found for user {user_id!r}"
        )
    return space


def _check_target_space_membership(db: Session, user_id: str, target_space_id: str) -> None:
    member = (
        db.query(SpaceMembership)
        .filter(
            SpaceMembership.space_id == target_space_id,
            SpaceMembership.user_id == user_id,
            SpaceMembership.status == "active",
        )
        .first()
    )
    if member is None:
        raise TargetSpaceMembershipError(
            f"User {user_id!r} is not a member of space {target_space_id!r}"
        )


def _fetch_and_validate_run(
    db: Session, user_id: str, target_run_id: str, target_space_id: str
) -> Run:
    run = db.query(Run).filter(Run.id == target_run_id).first()
    if run is None:
        raise TargetRunNotFoundError(f"Run {target_run_id!r} not found")
    if run.space_id != target_space_id:
        raise TargetRunSpaceMismatchError(
            f"Run {target_run_id!r} is not in space {target_space_id!r}"
        )
    if run.instructed_by_user_id != user_id:
        raise TargetRunOwnershipError(
            f"Run {target_run_id!r} is not instructed by user {user_id!r}"
        )
    return run


def _check_rate_limits(db: Session, user_id: str) -> None:
    active_count = (
        db.query(func.count(PersonalMemoryGrant.id))
        .filter(
            PersonalMemoryGrant.granting_user_id == user_id,
            PersonalMemoryGrant.status.in_(["active", "consuming"]),
        )
        .scalar()
    ) or 0
    if active_count >= MAX_ACTIVE_CONSUMING_GRANTS:
        raise RateLimitExceededError(
            f"Maximum {MAX_ACTIVE_CONSUMING_GRANTS} active/consuming grants reached"
        )

    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    hourly_count = (
        db.query(func.count(PersonalMemoryGrant.id))
        .filter(
            PersonalMemoryGrant.granting_user_id == user_id,
            PersonalMemoryGrant.created_at >= one_hour_ago,
        )
        .scalar()
    ) or 0
    if hourly_count >= MAX_GRANTS_PER_HOUR:
        raise RateLimitExceededError(
            f"Maximum {MAX_GRANTS_PER_HOUR} grants per rolling hour reached"
        )


def _write_event(
    db: Session,
    *,
    grant_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    run_id: str | None = None,
    source_space_id: str | None = None,
    target_space_id: str | None = None,
    metadata_json: dict | None = None,
) -> PersonalMemoryGrantEvent:
    """Write a content-safe audit event."""
    if metadata_json is not None:
        validate_grant_event_metadata(metadata_json)
    event = PersonalMemoryGrantEvent(
        id=_new_id(),
        grant_id=grant_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        run_id=run_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        metadata_json=metadata_json,
    )
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def preview_personal_memory_grant(
    db: Session,
    *,
    user_id: str,
    target_space_id: str,
    target_run_id: str,
    access_mode: str = "summary_only",
    memory_filter: dict | None = None,
    read_expires_in_seconds: int | None = None,
) -> dict:
    """Validate grant eligibility without creating a grant row.

    Returns a structural preview dict. Does not read raw memory content.
    Does not change ContextBuilder behavior.
    """
    if access_mode != "summary_only":
        raise InvalidAccessModeError(
            f"access_mode must be 'summary_only', got {access_mode!r}"
        )

    validate_memory_filter(memory_filter)

    _find_personal_space(db, user_id)
    _check_target_space_membership(db, user_id, target_space_id)
    _fetch_and_validate_run(db, user_id, target_run_id, target_space_id)

    warnings: list[str] = []

    active_count = (
        db.query(func.count(PersonalMemoryGrant.id))
        .filter(
            PersonalMemoryGrant.granting_user_id == user_id,
            PersonalMemoryGrant.status.in_(["active", "consuming"]),
        )
        .scalar()
    ) or 0
    if active_count >= MAX_ACTIVE_CONSUMING_GRANTS:
        warnings.append(
            f"Active/consuming grant limit ({MAX_ACTIVE_CONSUMING_GRANTS}) reached; create would be rejected"
        )

    proposed_expires_at = None
    if read_expires_in_seconds is not None:
        proposed_expires_at = datetime.now(UTC) + timedelta(seconds=read_expires_in_seconds)

    max_items = (memory_filter or {}).get("max_items")

    return {
        "eligible": True,
        "target_space_id": target_space_id,
        "target_run_id": target_run_id,
        "access_mode": access_mode,
        "proposed_read_expires_at": proposed_expires_at,
        "warnings": warnings,
        "excluded_sensitivity_levels": ["restricted", "highly_restricted"],
        "max_items": max_items,
    }


def create_personal_memory_grant(
    db: Session,
    *,
    user_id: str,
    target_space_id: str,
    target_run_id: str,
    access_mode: str = "summary_only",
    memory_filter: dict | None = None,
    read_expires_in_seconds: int,
) -> PersonalMemoryGrant:
    """Create an active run-scoped summary_only grant.

    - Server derives granting_user_id from user_id (authenticated identity).
    - Server derives personal_space_id from the user's personal space.
    - Does not attach grant to run context.
    """
    if access_mode != "summary_only":
        raise InvalidAccessModeError(
            f"access_mode must be 'summary_only', got {access_mode!r}"
        )

    validate_memory_filter(memory_filter)

    personal_space = _find_personal_space(db, user_id)
    _check_target_space_membership(db, user_id, target_space_id)
    _fetch_and_validate_run(db, user_id, target_run_id, target_space_id)
    _check_rate_limits(db, user_id)

    read_expires_at = datetime.now(UTC) + timedelta(seconds=read_expires_in_seconds)

    grant = PersonalMemoryGrant(
        id=_new_id(),
        granting_user_id=user_id,
        personal_space_id=personal_space.id,
        target_space_id=target_space_id,
        target_run_id=target_run_id,
        target_agent_id=None,
        grant_scope="run",
        access_mode="summary_only",
        status="active",
        memory_filter_json=memory_filter,
        read_expires_at=read_expires_at,
    )
    try:
        db.add(grant)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateGrantError(
            f"Active/consuming grant already exists for user {user_id!r} and run {target_run_id!r}"
        ) from exc

    _write_event(
        db,
        grant_id=grant.id,
        event_type="created",
        actor_user_id=user_id,
        run_id=target_run_id,
        source_space_id=personal_space.id,
        target_space_id=target_space_id,
        metadata_json={"access_mode": "summary_only", "grant_scope": "run"},
    )

    return grant


def list_personal_memory_grants_for_user(
    db: Session,
    *,
    user_id: str,
    status: str | None = None,
    target_space_id: str | None = None,
) -> list[PersonalMemoryGrant]:
    """Return grants where granting_user_id == user_id. Other users' grants are never returned."""
    q = db.query(PersonalMemoryGrant).filter(
        PersonalMemoryGrant.granting_user_id == user_id
    )
    if status is not None:
        q = q.filter(PersonalMemoryGrant.status == status)
    if target_space_id is not None:
        q = q.filter(PersonalMemoryGrant.target_space_id == target_space_id)
    return q.order_by(PersonalMemoryGrant.created_at.desc()).all()


def revoke_personal_memory_grant(
    db: Session,
    *,
    user_id: str,
    grant_id: str,
) -> PersonalMemoryGrant:
    """Revoke a grant owned by user_id. Returns 409 if already terminal."""
    grant = db.query(PersonalMemoryGrant).filter(
        PersonalMemoryGrant.id == grant_id
    ).first()

    if grant is None or grant.granting_user_id != user_id:
        raise GrantNotFoundError(
            f"Grant {grant_id!r} not found or not owned by current user"
        )

    if grant.status in ("revoked", "used", "expired", "failed"):
        raise GrantAlreadyTerminalError(
            f"Grant {grant_id!r} is already in terminal state: {grant.status!r}"
        )

    grant.status = "revoked"
    grant.revoked_at = datetime.now(UTC)
    db.flush()

    _write_event(
        db,
        grant_id=grant.id,
        event_type="revoked",
        actor_user_id=user_id,
        metadata_json={"previous_status": "active"},
    )

    return grant


def list_personal_memory_grant_events(
    db: Session,
    *,
    user_id: str,
    grant_id: str,
) -> tuple[PersonalMemoryGrant, list[PersonalMemoryGrantEvent]]:
    """Return (grant, events) for audit. Only granting_user_id may view the audit trail."""
    grant = db.query(PersonalMemoryGrant).filter(
        PersonalMemoryGrant.id == grant_id
    ).first()

    if grant is None or grant.granting_user_id != user_id:
        raise GrantNotFoundError(
            f"Grant {grant_id!r} not found or not owned by current user"
        )

    events = (
        db.query(PersonalMemoryGrantEvent)
        .filter(PersonalMemoryGrantEvent.grant_id == grant_id)
        .order_by(PersonalMemoryGrantEvent.created_at.asc())
        .all()
    )

    return grant, events
