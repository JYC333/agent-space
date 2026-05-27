from __future__ import annotations
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..param_binding import wire_query
from ..schemas import (
    MemoryCreate,
    MemoryOut,
    MemorySearchRequest,
    MemoryUpdate,
    Page,
    ProposalOut,
)
from .store import MemoryStore
from .serialization import memory_entry_to_out
from .proposal_payload import merge_distinct_provenance_entries, user_confirmation_entry
from .proposals import ProposalService
from ..auth.api_key import get_identity
from ..proposals.read_model import proposal_to_out

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=Page[MemoryOut])
def list_memories(
    scope: str | None = Query(None),
    namespace: str | None = Query(None),
    memory_type: str | None = wire_query(None, wire_name="type"),
    status: str = Query("active"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    workspace_id: str | None = Query(None),
    project_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    try:
        total = store.count(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            scope=scope,
            namespace=namespace,
            memory_type=memory_type,
            status=status,
            project_id=project_id,
        )
        items = store.list(
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            scope=scope,
            namespace=namespace,
            memory_type=memory_type,
            status=status,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.get("/{memory_id}", response_model=MemoryOut)
def get_memory(
    memory_id: str,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get_for_space(space_id, memory_id)
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


# ---------------------------------------------------------------------------
# Write endpoints — proposal-only paths
#
# POST   /memory          → memory_create proposal  (202 Accepted)
# PATCH  /memory/{id}     → memory_update proposal  (202 Accepted)
# DELETE /memory/{id}     → memory_archive proposal (202 Accepted)
#
# None of these routes create, mutate, or delete a MemoryEntry directly.
# Durable writes happen only when the returned Proposal is accepted via
# POST /api/v1/proposals/{id}/accept.
# ---------------------------------------------------------------------------


@router.post("", response_model=ProposalOut, status_code=202)
def create_memory(
    data: MemoryCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Create a memory_create proposal.  Returns 202; MemoryEntry is created on acceptance."""
    space_id, user_id = ids
    effective_space_id = data.space_id or space_id
    if effective_space_id != space_id:
        raise HTTPException(status_code=403, detail="Cannot create memory proposal in another space")

    scope = data.scope or "user"
    if scope == "system":
        subject_user_id = None
        owner_user_id = None
    else:
        subject_user_id = data.subject_user_id or (user_id if scope == "user" else None)
        owner_user_id = data.owner_user_id

    payload: dict[str, Any] = {
        "operation": "create",
        "proposed_content": data.content,
        "memory_type": data.type,
        "target_scope": scope,
        "target_namespace": data.namespace,
        "target_visibility": data.visibility,
        "sensitivity_level": data.sensitivity_level,
        "provenance_entries": merge_distinct_provenance_entries(
            [
                user_confirmation_entry(
                    user_id=user_id,
                    evidence={"method": "POST", "path": "/memory"},
                )
            ],
        ),
    }
    if subject_user_id is not None:
        payload["subject_user_id"] = subject_user_id
    if owner_user_id is not None:
        payload["owner_user_id"] = owner_user_id
    if data.selected_user_ids is not None:
        payload["selected_user_ids"] = data.selected_user_ids
    if data.source_id is not None:
        payload["source_id"] = data.source_id

    proposal = ProposalService(db).create_user_proposal(
        space_id=effective_space_id,
        user_id=user_id,
        proposal_type="memory_create",
        title=data.title,
        payload_json=payload,
        rationale="Memory creation requested via public API.",
        workspace_id=data.workspace_id,
        risk_level="low",
        urgency="normal",
        target_scope=scope,
        target_visibility=data.visibility,
    )
    return proposal_to_out(proposal)


@router.patch("/{memory_id}", response_model=ProposalOut, status_code=202)
def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Create a memory_update proposal.  Returns 202; MemoryEntry is versioned on acceptance."""
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get_for_space(space_id, memory_id)
    if not mem or not store.can_read_entry(
        mem,
        space_id,
        user_id,
        workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")

    change_data = data.model_dump(exclude_none=True)
    payload: dict[str, Any] = {
        "operation": "update",
        "target_memory_id": memory_id,
        "target_scope": mem.scope_type,
        "target_namespace": mem.namespace or "user.default",
        "memory_type": mem.memory_type,
        "provenance_entries": merge_distinct_provenance_entries(
            [
                user_confirmation_entry(
                    user_id=user_id,
                    evidence={"method": "PATCH", "path": f"/memory/{memory_id}"},
                )
            ],
        ),
    }
    if "content" in change_data:
        payload["proposed_content"] = change_data["content"]
        payload["content"] = change_data["content"]
    if "title" in change_data:
        payload["proposed_title"] = change_data["title"]
        payload["title"] = change_data["title"]
    if "visibility" in change_data:
        payload["visibility"] = change_data["visibility"]
        payload["target_visibility"] = change_data["visibility"]
    if "sensitivity_level" in change_data:
        payload["sensitivity_level"] = change_data["sensitivity_level"]
    if "subject_user_id" in change_data:
        payload["subject_user_id"] = change_data["subject_user_id"]
    if "owner_user_id" in change_data:
        payload["owner_user_id"] = change_data["owner_user_id"]
    if "selected_user_ids" in change_data:
        payload["selected_user_ids"] = change_data["selected_user_ids"]
    if "scope" in change_data:
        payload["target_scope"] = change_data["scope"]
    if "namespace" in change_data:
        payload["target_namespace"] = change_data["namespace"]
    if "type" in change_data:
        payload["memory_type"] = change_data["type"]

    proposal_title = (
        change_data.get("title")
        or mem.title
        or f"Update: {memory_id[:8]}"
    )
    proposal = ProposalService(db).create_user_proposal(
        space_id=space_id,
        user_id=user_id,
        proposal_type="memory_update",
        title=proposal_title,
        payload_json=payload,
        rationale="Memory update requested via public API.",
        workspace_id=workspace_id or mem.workspace_id,
        risk_level="low",
        urgency="normal",
        target_scope=payload.get("target_scope"),
        target_visibility=payload.get("target_visibility") or payload.get("visibility"),
        target_memory_id=memory_id,
    )
    return proposal_to_out(proposal)


@router.delete("/{memory_id}", response_model=ProposalOut, status_code=202)
def delete_memory(
    memory_id: str,
    workspace_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Create a memory_archive proposal.  Returns 202; MemoryEntry is archived on acceptance."""
    space_id, user_id = ids
    store = MemoryStore(db)
    mem = store.get_for_space(space_id, memory_id)
    if not mem or not store.can_read_entry(
        mem,
        space_id,
        user_id,
        workspace_id,
        include_system_scope=(mem.scope_type == "system"),
    ):
        raise HTTPException(status_code=404, detail="Memory not found")

    payload: dict[str, Any] = {
        "operation": "archive",
        "target_memory_id": memory_id,
        "target_scope": mem.scope_type,
        "target_namespace": mem.namespace or "user.default",
        "memory_type": mem.memory_type,
        "proposed_content": mem.content or "",
        "provenance_entries": merge_distinct_provenance_entries(
            [
                user_confirmation_entry(
                    user_id=user_id,
                    evidence={"method": "DELETE", "path": f"/memory/{memory_id}"},
                )
            ],
        ),
    }

    proposal = ProposalService(db).create_user_proposal(
        space_id=space_id,
        user_id=user_id,
        proposal_type="memory_archive",
        title=f"Archive: {mem.title or memory_id[:8]}",
        payload_json=payload,
        rationale="Memory archive requested via public API.",
        workspace_id=workspace_id or mem.workspace_id,
        risk_level="low",
        urgency="normal",
        target_scope=mem.scope_type,
        target_visibility=mem.visibility,
        target_memory_id=memory_id,
    )
    return proposal_to_out(proposal)


class ConsolidationRunRequest(BaseModel):
    batch_limit: int = Field(default=50, ge=1, le=500)
    activity_ids: list[str] | None = None


@router.post("/consolidation/run")
def run_memory_consolidation(
    body: ConsolidationRunRequest | None = Body(default=None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Run batch activity consolidation: pending activities → classifier → validator → proposals."""
    from .consolidation.service import ActivityConsolidationService

    space_id, user_id = ids
    b = body or ConsolidationRunRequest()
    svc = ActivityConsolidationService(db)
    result = svc.run_pending(
        space_id=space_id,
        acting_user_id=user_id,
        batch_limit=b.batch_limit,
        activity_ids=b.activity_ids,
    )
    return {
        "consolidation_run_id": result.consolidation_run_id,
        "proposals_created": result.proposals_created,
        "activities_processed": result.activities_processed,
        "activities_skipped": result.activities_skipped,
        "activities_failed": result.activities_failed,
    }
