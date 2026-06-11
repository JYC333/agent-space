"""
SourcePointer HTTP API.

Membership-gated metadata management only. Never resolves source object content.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..auth import can_manage_space_resources, can_use_space
from ..db import get_db
from ..schemas import Page
from .schemas import SourcePointerCreate, SourcePointerOut
from .service import (
    InvalidSourcePointerAccessModeError,
    InvalidSourcePointerExpiresAtError,
    create_source_pointer,
    delete_source_pointer,
    get_source_pointer_by_id,
    list_source_pointers_for_user,
)
from .validation import InvalidSourcePointerMetadataError

router = APIRouter(prefix="/source-pointers", tags=["source-pointers"])


def _pointer_to_out(ptr: object) -> SourcePointerOut:
    return SourcePointerOut(
        id=ptr.id,  # type: ignore[attr-defined]
        owner_space_id=ptr.owner_space_id,  # type: ignore[attr-defined]
        source_space_id=ptr.source_space_id,  # type: ignore[attr-defined]
        source_object_type=ptr.source_object_type,  # type: ignore[attr-defined]
        source_object_id=ptr.source_object_id,  # type: ignore[attr-defined]
        access_mode=ptr.access_mode,  # type: ignore[attr-defined]
        granted_by_user_id=ptr.granted_by_user_id,  # type: ignore[attr-defined]
        expires_at=ptr.expires_at,  # type: ignore[attr-defined]
        metadata_json=ptr.metadata_json,  # type: ignore[attr-defined]
        created_at=ptr.created_at,  # type: ignore[attr-defined]
    )


def _require_use_space(db: Session, user_id: str, space_id: str) -> None:
    if not can_use_space(db, user_id, space_id):
        raise HTTPException(status_code=403, detail="Not a member of this space")


def _require_admin_owner_space(db: Session, user_id: str, owner_space_id: str) -> None:
    if not can_manage_space_resources(db, user_id, owner_space_id):
        raise HTTPException(status_code=403, detail="Requires admin role in owner space")


@router.post("", response_model=SourcePointerOut, status_code=201)
def create_pointer(
    body: SourcePointerCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> SourcePointerOut:
    """Create provenance pointer metadata. Does not validate or return source content."""
    _auth_space_id, user_id = ids
    _require_use_space(db, user_id, body.owner_space_id)
    _require_use_space(db, user_id, body.source_space_id)
    try:
        ptr = create_source_pointer(
            db,
            owner_space_id=body.owner_space_id,
            source_space_id=body.source_space_id,
            source_object_type=body.source_object_type,
            source_object_id=body.source_object_id,
            access_mode=body.access_mode,
            granted_by_user_id=user_id,
            expires_at=body.expires_at,
            metadata_json=body.metadata_json,
        )
    except InvalidSourcePointerAccessModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidSourcePointerMetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidSourcePointerExpiresAtError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(ptr)
    return _pointer_to_out(ptr)


@router.get("", response_model=Page[SourcePointerOut])
def list_pointers(
    owner_space_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> Page[SourcePointerOut]:
    """List pointer metadata for owner spaces the user belongs to."""
    _auth_space_id, user_id = ids
    if owner_space_id is not None:
        if not can_use_space(db, user_id, owner_space_id):
            raise HTTPException(status_code=403, detail="Not a member of this space")
    rows = list_source_pointers_for_user(
        db, user_id=user_id, owner_space_id=owner_space_id
    )
    total = len(rows)
    page = rows[offset : offset + limit]
    return Page(
        items=[_pointer_to_out(p) for p in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{pointer_id}", response_model=SourcePointerOut)
def get_pointer(
    pointer_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
) -> SourcePointerOut:
    """Return pointer metadata when the user is a member of owner_space_id."""
    _auth_space_id, user_id = ids
    ptr = get_source_pointer_by_id(db, pointer_id=pointer_id)
    if ptr is None:
        raise HTTPException(status_code=404, detail="Source pointer not found")
    if not can_use_space(db, user_id, ptr.owner_space_id):
        raise HTTPException(status_code=404, detail="Source pointer not found")
    return _pointer_to_out(ptr)


@router.delete("/{pointer_id}", status_code=204)
def delete_pointer(
    pointer_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Delete pointer metadata. Requires admin/owner role in owner_space. Does not delete source object."""
    _auth_space_id, user_id = ids
    ptr = get_source_pointer_by_id(db, pointer_id=pointer_id)
    if ptr is None:
        raise HTTPException(status_code=404, detail="Source pointer not found")
    _require_admin_owner_space(db, user_id, ptr.owner_space_id)
    delete_source_pointer(db, pointer_id=pointer_id)
    db.commit()
