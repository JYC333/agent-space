from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..schemas import CapabilityOut, CapabilityReloadResponse
from .service import CapabilityService

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=list[CapabilityOut])
def list_capabilities(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = CapabilityService(db)
    return svc.list(space_id=space_id)


@router.post("/reload", response_model=CapabilityReloadResponse)
def reload_capabilities(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = CapabilityService(db)
    result = svc.reload(space_id=space_id)
    return CapabilityReloadResponse(**result)


@router.get("/{capability_id}", response_model=CapabilityOut)
def get_capability(
    capability_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    svc = CapabilityService(db)
    cap = svc.get(capability_id, space_id=space_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Capability not found")
    return cap
