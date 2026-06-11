from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import (
    SessionCreate, SessionOut, MessageCreate, MessageOut, ReflectResponse, ProposalOut, Page
)
from .service import SessionService
from ..memory import MemoryReflector
from ..proposals import proposal_to_out
from ..auth import get_identity

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    data: SessionCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    if not data.space_id:
        data.space_id = space_id
    if not data.user_id:
        data.user_id = user_id
    svc = SessionService(db)
    return svc.create_session(data)


@router.get("", response_model=Page[SessionOut])
def list_sessions(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = SessionService(db)
    total = svc.count_sessions(space_id=space_id, user_id=user_id)
    items = svc.list_sessions(space_id=space_id, user_id=user_id, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = SessionService(db)
    session = svc.get_session(session_id, space_id=space_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/messages", response_model=MessageOut, status_code=201)
def add_message(
    session_id: str,
    data: MessageCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = SessionService(db)
    msg = svc.add_message(session_id, data, space_id=space_id, user_id=user_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Session not found")
    return msg


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def get_messages(
    session_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = SessionService(db)
    session = svc.get_session(session_id, space_id=space_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return svc.get_messages(session_id, limit=limit, offset=offset)


@router.post("/{session_id}/reflect", response_model=ReflectResponse)
def reflect_session(
    session_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = SessionService(db)
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    reflector = MemoryReflector(db)
    proposals = reflector.reflect(
        session_id=session_id,
        space_id=space_id,
        user_id=user_id,
        workspace_id=session.workspace_id,
    )

    now = datetime.now(UTC)
    return ReflectResponse(
        session_id=session_id,
        proposals_created=len(proposals),
        proposals=[proposal_to_out(p, now=now) for p in proposals],
    )
