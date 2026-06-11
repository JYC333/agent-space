from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..schemas import RuntimeAdapterCreate, RuntimeAdapterOut, RuntimeAdapterStatusOut, RuntimeAdapterUpdate
from .service import RuntimeAdapterService

router = APIRouter(prefix="/runtime-adapters", tags=["runtime-adapters"])


@router.get("/catalog", response_model=list[dict])
def catalog(_: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    return RuntimeAdapterService(db).catalog()


@router.get("/detect", response_model=list[RuntimeAdapterStatusOut])
def detect_all(ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    return RuntimeAdapterService(db).detect_all(space_id)


@router.get("", response_model=list[RuntimeAdapterOut])
def list_adapters(ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    return RuntimeAdapterService(db).list(space_id)


@router.post("", response_model=RuntimeAdapterOut, status_code=201)
def create_adapter(
    data: RuntimeAdapterCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        return RuntimeAdapterService(db).create(data, space_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{adapter_id}", response_model=RuntimeAdapterOut)
def get_adapter(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    row = RuntimeAdapterService(db).get(adapter_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return row


@router.patch("/{adapter_id}", response_model=RuntimeAdapterOut)
def update_adapter(
    adapter_id: str,
    data: RuntimeAdapterUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    try:
        row = RuntimeAdapterService(db).update(adapter_id, space_id, data)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return row


@router.delete("/{adapter_id}", status_code=204)
def delete_adapter(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    if not RuntimeAdapterService(db).delete(adapter_id, space_id):
        raise HTTPException(status_code=404, detail="Runtime adapter not found")


@router.get("/{adapter_type}/detect", response_model=RuntimeAdapterStatusOut)
def detect_adapter(adapter_type: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    svc = RuntimeAdapterService(db)
    try:
        return svc.detect_one(adapter_type, space_id=space_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Runtime adapter spec not found") from exc


@router.get("/{adapter_id}/status", response_model=RuntimeAdapterStatusOut)
def adapter_status(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    row = RuntimeAdapterService(db).get(adapter_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return RuntimeAdapterService(db).status(row)


@router.post("/{adapter_id}/probe", response_model=RuntimeAdapterStatusOut)
def probe_adapter(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    row = RuntimeAdapterService(db).get(adapter_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return RuntimeAdapterService(db).probe(row)


@router.get("/{adapter_id}/usage")
def adapter_usage(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    row = RuntimeAdapterService(db).get(adapter_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return RuntimeAdapterService(db).usage(row)


@router.post("/{adapter_id}/usage/refresh")
def refresh_adapter_usage(adapter_id: str, ids: tuple[str, str] = Depends(get_identity), db: Session = Depends(get_db)):
    space_id, _ = ids
    row = RuntimeAdapterService(db).get(adapter_id, space_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Runtime adapter not found")
    return RuntimeAdapterService(db).usage(row, refresh=True)
