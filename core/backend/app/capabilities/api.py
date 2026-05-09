from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import CapabilityOut, CapabilityReloadResponse
from .service import CapabilityService

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=list[CapabilityOut])
def list_capabilities(db: Session = Depends(get_db)):
    svc = CapabilityService(db)
    return svc.list()


@router.post("/reload", response_model=CapabilityReloadResponse)
def reload_capabilities(db: Session = Depends(get_db)):
    svc = CapabilityService(db)
    result = svc.reload()
    return CapabilityReloadResponse(**result)


@router.get("/{capability_id}", response_model=CapabilityOut)
def get_capability(capability_id: str, db: Session = Depends(get_db)):
    svc = CapabilityService(db)
    cap = svc.get(capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Capability not found")
    return cap
