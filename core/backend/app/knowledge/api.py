from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..db import get_db
from ..schemas import Page, ProposalOut
from ..proposals.read_model import proposal_to_out
from .read_model import (
    knowledge_item_relation_to_out,
    knowledge_item_source_to_out,
    knowledge_item_to_out,
    knowledge_item_to_summary_out,
    source_to_out,
    source_to_summary_out,
)
from .schemas import (
    KnowledgeCreateProposalIn,
    KnowledgeItemOut,
    KnowledgeItemRelationCreateProposalIn,
    KnowledgeItemRelationOut,
    KnowledgeItemSourceLinkIn,
    KnowledgeItemSourceOut,
    KnowledgeItemSummaryOut,
    KnowledgeUpdateProposalIn,
    SourceCreateIn,
    SourceOut,
    SourceSummaryOut,
    SourceUpdateIn,
)
from .service import KnowledgeNotFound, KnowledgeService, KnowledgeValidationError, SourceService

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


@router.get("/items/{item_id}/relations", response_model=list[KnowledgeItemRelationOut])
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
    return [knowledge_item_relation_to_out(r) for r in relations]


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
    body: KnowledgeItemRelationCreateProposalIn,
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


# ---------------------------------------------------------------------------
# Sources (provenance / evidence layer; direct CRUD, not proposal-gated)
# ---------------------------------------------------------------------------


@router.get("/sources", response_model=Page[SourceSummaryOut])
def list_sources(
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    total, sources = SourceService(db).list_sources(
        space_id=space_id,
        source_type=source_type,
        status=status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return Page(items=[source_to_summary_out(s) for s in sources], total=total, limit=limit, offset=offset)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(
    source_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    source = SourceService(db).get_source(space_id=space_id, source_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source_to_out(source)


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(
    body: SourceCreateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        source = SourceService(db).create_source(
            space_id=space_id,
            user_id=user_id,
            data=body.model_dump(mode="json"),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return source_to_out(source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: str,
    body: SourceUpdateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        source = SourceService(db).update_source(
            space_id=space_id,
            source_id=source_id,
            data=body.model_dump(mode="json", exclude_unset=True),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return source_to_out(source)


@router.delete("/sources/{source_id}", response_model=SourceOut)
def archive_source(
    source_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        source = SourceService(db).archive_source(space_id=space_id, source_id=source_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return source_to_out(source)


@router.get("/sources/{source_id}/items", response_model=list[KnowledgeItemSourceOut])
def list_items_for_source(
    source_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        links = SourceService(db).list_items_for_source(space_id=space_id, source_id=source_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return [knowledge_item_source_to_out(link) for link in links]


# ---------------------------------------------------------------------------
# Item <-> Source evidence links
# ---------------------------------------------------------------------------


@router.get("/items/{item_id}/sources", response_model=list[KnowledgeItemSourceOut])
def list_item_sources(
    item_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        links = SourceService(db).list_item_sources(space_id=space_id, item_id=item_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return [knowledge_item_source_to_out(link) for link in links]


@router.post("/items/{item_id}/sources", response_model=KnowledgeItemSourceOut, status_code=201)
def link_source_to_item(
    item_id: str,
    body: KnowledgeItemSourceLinkIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        link = SourceService(db).link_source(
            space_id=space_id,
            user_id=user_id,
            item_id=item_id,
            data=body.model_dump(mode="json"),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return knowledge_item_source_to_out(link)


@router.delete("/items/{item_id}/sources/{link_id}", status_code=204)
def unlink_source_from_item(
    item_id: str,
    link_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        SourceService(db).unlink_source(space_id=space_id, item_id=item_id, link_id=link_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
