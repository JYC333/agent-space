from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..param_binding import wire_query
from ..schemas import MemoryCreate, MemoryUpdate, MemoryOut, MemorySearchRequest, ProposalOut, Page
from .store import MemoryStore
from .proposals import MemoryProposalService
from .serialization import memory_entry_to_out
from ..proposals.read_model import proposal_to_out
from ..auth.api_key import get_identity

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=Page[MemoryOut])
def list_memories(
    scope: str | None = Query(None),
    namespace: str | None = Query(None),
    memory_type: str | None = wire_query(None, wire_name="type"),
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
        space_id=space_id,
        user_id=user_id,
        workspace_id=workspace_id,
        scope=scope,
        namespace=namespace,
        memory_type=memory_type,
        status=status,
    )
    items = store.list(
        space_id=space_id,
        user_id=user_id,
        workspace_id=workspace_id,
        scope=scope,
        namespace=namespace,
        memory_type=memory_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    outs: list[MemoryOut] = []
    for m in items:
        out = memory_entry_to_out(
            m,
            viewer_user_id=user_id,
            space_id=space_id,
            workspace_id=workspace_id,
        )
        if out is not None:
            outs.append(out)
    return Page(items=outs, total=total, limit=limit, offset=offset)


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    data: MemoryCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    if not data.space_id:
        data.space_id = space_id
    if data.scope == "system":
        data.subject_user_id = None
        data.owner_user_id = None
    elif data.scope == "user" and data.subject_user_id is None:
        data.subject_user_id = user_id
    store = MemoryStore(db)
    mem = store.create(data, acting_user_id=user_id, created_by=str(user_id))
    out = memory_entry_to_out(
        mem,
        viewer_user_id=user_id,
        space_id=space_id,
        workspace_id=data.workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    )
    if out is None:
        raise HTTPException(status_code=400, detail="Created memory is not visible to the current user")
    return out


@router.get("/{memory_id}", response_model=MemoryOut)
def get_memory(
    memory_id: str,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get(memory_id)
    if not mem or not store.can_read_entry(
        mem,
        space_id,
        user_id,
        workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")
    store.log_explicit_read(
        mem,
        space_id=space_id,
        user_id=user_id,
        agent_id=None,
        run_id=None,
        access_type="explicit_read",
        reason=None,
    )
    out = memory_entry_to_out(
        mem,
        viewer_user_id=user_id,
        space_id=space_id,
        workspace_id=workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    )
    if out is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return out


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get(memory_id)
    if not mem or not store.can_read_entry(
        mem,
        space_id,
        user_id,
        workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = store.update(memory_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")
    out = memory_entry_to_out(
        updated,
        viewer_user_id=user_id,
        space_id=space_id,
        workspace_id=workspace_id,
        include_system_scope=(updated.scope_type == "system"),
    )
    if out is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return out


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get(memory_id)
    if not mem or not store.can_read_entry(
        mem,
        space_id,
        user_id,
        workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")
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
    rows = store.search(
        query=req.query,
        space_id=req.space_id or space_id,
        user_id=req.user_id or user_id,
        workspace_id=req.workspace_id,
        scope=req.scope,
        namespace=req.namespace,
        memory_type=req.type,
        limit=req.limit,
    )
    sid = req.space_id or space_id
    uid = req.user_id or user_id
    outs: list[MemoryOut] = []
    logged: list = []
    for m in rows:
        out = memory_entry_to_out(
            m,
            viewer_user_id=uid,
            space_id=sid,
            workspace_id=req.workspace_id,
            include_system_scope=(m.scope_type == "system"),
        )
        if out is not None:
            outs.append(out)
            logged.append(m)
    if logged:
        store.log_reads_batch(
            logged,
            space_id=sid,
            user_id=uid,
            agent_id=None,
            run_id=None,
            access_type="search_hit",
            reason="memory search",
        )
    return outs


# ---- Proposals ----


@router.get("/proposals", response_model=Page[ProposalOut])
def list_proposals(
    status: str | None = Query("pending"),
    proposal_type: str | None = wire_query(None, wire_name="type"),
    urgency: str | None = Query(None),
    expired: bool | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """List proposals for the memory review workflow (read surface).

    Canonical listing and filters: ``GET /api/v1/proposals``. This route is a
    memory-module convenience path and **defaults to** ``status=pending`` so
    existing memory-review clients keep the same behaviour.
    """
    space_id, user_id = ids
    now = datetime.now(UTC)
    svc = MemoryProposalService(db)
    total = svc.count_proposals(
        space_id=space_id,
        user_id=user_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        now=now,
    )
    items = svc.list_proposals(
        space_id=space_id,
        user_id=user_id,
        status=status,
        proposal_type=proposal_type,
        urgency=urgency,
        expired=expired,
        limit=limit,
        offset=offset,
        now=now,
    )
    return Page(
        items=[proposal_to_out(p, now=now) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    out = memory_entry_to_out(
        memory,
        viewer_user_id=user_id,
        space_id=space_id,
        workspace_id=memory.workspace_id,
        include_system_scope=(memory.scope_type == "system"),
    )
    if out is None:
        raise HTTPException(status_code=400, detail="Accepted memory is not visible to the current user")
    return out


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
    return proposal_to_out(proposal, now=datetime.now(UTC))
