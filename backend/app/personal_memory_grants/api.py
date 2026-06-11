"""PersonalMemoryGrant HTTP API — grant lifecycle only.

Routes:
  POST /api/v1/personal-memory-grants/preview   — eligibility check, no grant created
  POST /api/v1/personal-memory-grants           — create active run-scoped grant
  GET  /api/v1/personal-memory-grants           — list caller's grants
  POST /api/v1/personal-memory-grants/{id}/revoke
  GET  /api/v1/personal-memory-grants/{id}/audit

Invariants:
  - ContextBuilder behavior is NOT changed here.
  - No cross-space memory reads are enabled.
  - No grant resolver is wired to run context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from .schemas import AuditOut, GrantCreate, GrantEventOut, GrantOut, GrantPreviewRequest, PreviewOut
from .service import (
    DuplicateGrantError,
    GrantAlreadyTerminalError,
    GrantNotFoundError,
    InvalidAccessModeError,
    PersonalSpaceNotFoundError,
    RateLimitExceededError,
    TargetRunNotFoundError,
    TargetRunOwnershipError,
    TargetRunSpaceMismatchError,
    TargetSpaceMembershipError,
    create_personal_memory_grant,
    list_personal_memory_grant_events,
    list_personal_memory_grants_for_user,
    preview_personal_memory_grant,
    revoke_personal_memory_grant,
)
from .validation import InvalidGrantFilterError

router = APIRouter(prefix="/personal-memory-grants", tags=["personal-memory-grants"])


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _to_grant_out(grant: object) -> GrantOut:
    return GrantOut(
        id=grant.id,  # type: ignore[attr-defined]
        granting_user_id=grant.granting_user_id,  # type: ignore[attr-defined]
        personal_space_id=grant.personal_space_id,  # type: ignore[attr-defined]
        target_space_id=grant.target_space_id,  # type: ignore[attr-defined]
        target_run_id=grant.target_run_id,  # type: ignore[attr-defined]
        target_agent_id=grant.target_agent_id,  # type: ignore[attr-defined]
        grant_scope=grant.grant_scope,  # type: ignore[attr-defined]
        access_mode=grant.access_mode,  # type: ignore[attr-defined]
        status=grant.status,  # type: ignore[attr-defined]
        memory_filter_json=grant.memory_filter_json,  # type: ignore[attr-defined]
        read_expires_at=grant.read_expires_at,  # type: ignore[attr-defined]
        revoked_at=grant.revoked_at,  # type: ignore[attr-defined]
        used_at=grant.used_at,  # type: ignore[attr-defined]
        created_at=grant.created_at,  # type: ignore[attr-defined]
        updated_at=grant.updated_at,  # type: ignore[attr-defined]
    )


def _to_event_out(ev: object) -> GrantEventOut:
    return GrantEventOut(
        id=ev.id,  # type: ignore[attr-defined]
        grant_id=ev.grant_id,  # type: ignore[attr-defined]
        event_type=ev.event_type,  # type: ignore[attr-defined]
        actor_user_id=ev.actor_user_id,  # type: ignore[attr-defined]
        run_id=ev.run_id,  # type: ignore[attr-defined]
        metadata_json=ev.metadata_json,  # type: ignore[attr-defined]
        created_at=ev.created_at,  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/preview", response_model=PreviewOut)
def preview_grant(
    body: GrantPreviewRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> PreviewOut:
    """Check grant eligibility without creating a grant row.

    Returns structural preview only. Does not read or return raw memory content.
    Does not change ContextBuilder behavior.
    """
    _auth_space_id, user_id = ids
    try:
        result = preview_personal_memory_grant(
            db,
            user_id=user_id,
            target_space_id=body.target_space_id,
            target_run_id=body.target_run_id,
            access_mode=body.access_mode,
            memory_filter=body.memory_filter,
            read_expires_in_seconds=body.read_expires_in_seconds,
        )
    except InvalidGrantFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidAccessModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalSpaceNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TargetSpaceMembershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (TargetRunNotFoundError, TargetRunSpaceMismatchError, TargetRunOwnershipError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PreviewOut(**result)


@router.post("", response_model=GrantOut, status_code=201)
def create_grant(
    body: GrantCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> GrantOut:
    """Create an active run-scoped summary_only grant.

    Server derives granting_user_id and personal_space_id — client must not supply them.
    Does not attach grant to run context.
    """
    _auth_space_id, user_id = ids
    try:
        grant = create_personal_memory_grant(
            db,
            user_id=user_id,
            target_space_id=body.target_space_id,
            target_run_id=body.target_run_id,
            access_mode=body.access_mode,
            memory_filter=body.memory_filter,
            read_expires_in_seconds=body.read_expires_in_seconds,
        )
    except InvalidGrantFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidAccessModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalSpaceNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TargetSpaceMembershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (TargetRunNotFoundError, TargetRunSpaceMismatchError, TargetRunOwnershipError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DuplicateGrantError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(grant)
    return _to_grant_out(grant)


@router.get("", response_model=list[GrantOut])
def list_grants(
    status: str | None = Query(None),
    target_space_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> list[GrantOut]:
    """List grants owned by the authenticated user. Never returns other users' grants."""
    _auth_space_id, user_id = ids
    grants = list_personal_memory_grants_for_user(
        db, user_id=user_id, status=status, target_space_id=target_space_id
    )
    return [_to_grant_out(g) for g in grants]


@router.post("/{grant_id}/revoke", response_model=GrantOut)
def revoke_grant(
    grant_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> GrantOut:
    """Revoke a grant owned by the authenticated user.

    Non-owner gets 403. Already-terminal grant gets 409.
    Does not affect run context.
    """
    _auth_space_id, user_id = ids
    try:
        grant = revoke_personal_memory_grant(db, user_id=user_id, grant_id=grant_id)
    except GrantNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GrantAlreadyTerminalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(grant)
    return _to_grant_out(grant)


@router.get("/{grant_id}/audit", response_model=AuditOut)
def get_audit(
    grant_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> AuditOut:
    """Return audit trail for a grant. Only the granting user may view it.

    Event metadata_json is content-safe — no raw memory text or generated summaries.
    """
    _auth_space_id, user_id = ids
    try:
        grant, events = list_personal_memory_grant_events(
            db, user_id=user_id, grant_id=grant_id
        )
    except GrantNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return AuditOut(
        grant=_to_grant_out(grant),
        events=[_to_event_out(e) for e in events],
    )
