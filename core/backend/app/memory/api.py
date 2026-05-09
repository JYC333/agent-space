from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import MemoryCreate, MemoryUpdate, MemoryOut, MemorySearchRequest, ProposalOut, Page
from .store import MemoryStore
from .proposals import MemoryProposalService
from ..auth.api_key import get_identity

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=Page[MemoryOut])
def list_memories(
    scope: str | None = Query(None),
    namespace: str | None = Query(None),
    memory_type: str | None = Query(None, alias="type"),
    status: str = Query("active"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    total = store.count(
        space_id=space_id, user_id=user_id, workspace_id=workspace_id,
        scope=scope, namespace=namespace, memory_type=memory_type, status=status,
    )
    items = store.list(
        space_id=space_id, user_id=user_id, workspace_id=workspace_id,
        scope=scope, namespace=namespace, memory_type=memory_type,
        status=status, limit=limit, offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    data: MemoryCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    if not data.space_id:
        data.space_id = space_id
    if not data.owner_user_id:
        data.owner_user_id = user_id
    store = MemoryStore(db)
    return store.create(data)


@router.get("/{memory_id}", response_model=MemoryOut)
def get_memory(memory_id: str, db: Session = Depends(get_db)):
    store = MemoryStore(db)
    mem = store.get(memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, data: MemoryUpdate, db: Session = Depends(get_db)):
    store = MemoryStore(db)
    mem = store.update(memory_id, data)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    store = MemoryStore(db)
    if not store.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/search", response_model=list[MemoryOut])
def search_memories(
    req: MemorySearchRequest,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    return store.search(
        query=req.query,
        space_id=req.space_id or space_id,
        user_id=req.user_id or user_id,
        workspace_id=req.workspace_id,
        scope=req.scope,
        namespace=req.namespace,
        memory_type=req.type,
        limit=req.limit,
    )


# ---- Proposals ----

@router.get("/proposals", response_model=Page[ProposalOut])
def list_proposals(
    status: str | None = Query("pending"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = MemoryProposalService(db)
    total = svc.count_proposals(space_id=space_id, user_id=user_id, status=status)
    items = svc.list_proposals(space_id=space_id, user_id=user_id, status=status, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/proposals/{proposal_id}/accept", response_model=MemoryOut)
def accept_proposal(
    proposal_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = MemoryProposalService(db)
    result = svc.accept(proposal_id, space_id=space_id, user_id=user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    _, memory = result
    return memory


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = MemoryProposalService(db)
    proposal = svc.reject(proposal_id, space_id=space_id, user_id=user_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already decided")
    return proposal
