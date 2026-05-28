from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..schemas import Page, ProposalOut
from ..proposals.read_model import proposal_to_out
from .read_model import knowledge_item_to_out, knowledge_item_to_summary_out, knowledge_relation_to_out
from .schemas import (
    KnowledgeCreateProposalIn,
    KnowledgeItemOut,
    KnowledgeItemSummaryOut,
    KnowledgeRelationCreateProposalIn,
    KnowledgeRelationOut,
    KnowledgeUpdateProposalIn,
)
from .service import KnowledgeNotFound, KnowledgeService, KnowledgeValidationError

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _proposal_out(proposal) -> ProposalOut:
    return proposal_to_out(proposal)


def _handle_knowledge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/items", response_model=Page[KnowledgeItemSummaryOut])
def list_knowledge_items(
    item_type: str | None = Query(None),
    status: str | None = Query(None),
    visibility: str | None = Query(None),
    project_id: str | None = Query(None),
    workspace_id: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    total, items = KnowledgeService(db).list_items(
        space_id=space_id,
        viewer_user_id=user_id,
        item_type=item_type,
        status=status,
        visibility=visibility,
        project_id=project_id,
        workspace_id=workspace_id,
        tag=tag,
        q=q,
        limit=limit,
        offset=offset,
    )
    return Page(items=[knowledge_item_to_summary_out(i) for i in items], total=total, limit=limit, offset=offset)


@router.get("/items/{item_id}", response_model=KnowledgeItemOut)
def get_knowledge_item(
    item_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    item = KnowledgeService(db).get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return knowledge_item_to_out(item)


@router.get("/items/{item_id}/relations", response_model=list[KnowledgeRelationOut])
def get_knowledge_item_relations(
    item_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        relations = KnowledgeService(db).list_item_relations(space_id=space_id, viewer_user_id=user_id, item_id=item_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return [knowledge_relation_to_out(r) for r in relations]


@router.post("/items/proposals", response_model=ProposalOut, status_code=202)
def create_knowledge_item_proposal(
    body: KnowledgeCreateProposalIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        proposal = KnowledgeService(db).create_item_proposal(
            space_id=space_id,
            user_id=user_id,
            data=body.model_dump(mode="json"),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return _proposal_out(proposal)


@router.patch("/items/{item_id}/proposals", response_model=ProposalOut, status_code=202)
def create_knowledge_update_proposal(
    item_id: str,
    body: KnowledgeUpdateProposalIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        proposal = KnowledgeService(db).create_update_proposal(
            space_id=space_id,
            user_id=user_id,
            item_id=item_id,
            data=body.model_dump(mode="json"),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return _proposal_out(proposal)


@router.delete("/items/{item_id}", response_model=ProposalOut, status_code=202)
def create_knowledge_archive_proposal(
    item_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        proposal = KnowledgeService(db).create_archive_proposal(space_id=space_id, user_id=user_id, item_id=item_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return _proposal_out(proposal)


@router.post("/relations/proposals", response_model=ProposalOut, status_code=202)
def create_knowledge_relation_proposal(
    body: KnowledgeRelationCreateProposalIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        proposal = KnowledgeService(db).create_relation_proposal(
            space_id=space_id,
            user_id=user_id,
            data=body.model_dump(mode="json"),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return _proposal_out(proposal)


@router.delete("/relations/{relation_id}", response_model=ProposalOut, status_code=202)
def create_knowledge_relation_delete_proposal(
    relation_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        proposal = KnowledgeService(db).create_relation_delete_proposal(
            space_id=space_id,
            user_id=user_id,
            relation_id=relation_id,
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return _proposal_out(proposal)
