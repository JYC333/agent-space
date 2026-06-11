from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..schemas import Page, ProposalOut
from ..proposals import proposal_to_out
from .read_model import (
    entity_link_to_out,
    knowledge_item_relation_to_out,
    knowledge_item_source_to_out,
    knowledge_item_to_out,
    knowledge_item_to_summary_out,
    note_collection_to_out,
    note_to_out,
    note_to_summary_out,
    source_to_out,
    source_to_summary_out,
)
from .schemas import (
    EntityLinkOut,
    KnowledgeCreateProposalIn,
    KnowledgeItemOut,
    KnowledgeItemRelationCreateProposalIn,
    KnowledgeItemRelationOut,
    KnowledgeItemSourceLinkIn,
    KnowledgeItemSourceOut,
    KnowledgeItemSummaryOut,
    KnowledgeSummaryOut,
    KnowledgeUpdateProposalIn,
    NoteCollectionCreateIn,
    NoteCollectionOut,
    NoteCollectionUpdateIn,
    NoteCreateIn,
    NoteLinkCreateIn,
    NoteOut,
    NoteSummaryOut,
    NoteUpdateIn,
    SourceCreateIn,
    SourceOut,
    SourceSummaryOut,
    SourceUpdateIn,
)
from .service import (
    EntityLinkService,
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeService,
    KnowledgeSummaryService,
    KnowledgeValidationError,
    NoteCollectionService,
    NoteService,
    SourceService,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
notes_router = APIRouter(prefix="/notes", tags=["notes"])
extra_routers = [notes_router]


def _proposal_out(proposal) -> ProposalOut:
    return proposal_to_out(proposal)


def _handle_knowledge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, KnowledgeConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@notes_router.get("/collections", response_model=list[NoteCollectionOut])
def list_note_collections(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    rows = NoteCollectionService(db).list_collections(space_id=space_id)
    return [note_collection_to_out(row) for row in rows]


@notes_router.post("/collections", response_model=NoteCollectionOut, status_code=201)
def create_note_collection(
    body: NoteCollectionCreateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        collection = NoteCollectionService(db).create_collection(space_id=space_id, data=body.model_dump(mode="json"))
    except (KnowledgeNotFound, KnowledgeValidationError, KnowledgeConflict) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return note_collection_to_out(collection)


@notes_router.patch("/collections/{collection_id}", response_model=NoteCollectionOut)
def update_note_collection(
    collection_id: str,
    body: NoteCollectionUpdateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        collection = NoteCollectionService(db).update_collection(
            space_id=space_id,
            collection_id=collection_id,
            data=body.model_dump(mode="json", exclude_unset=True),
        )
    except (KnowledgeNotFound, KnowledgeValidationError, KnowledgeConflict) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return note_collection_to_out(collection)


@notes_router.delete("/collections/{collection_id}", status_code=204)
def delete_note_collection(
    collection_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        NoteCollectionService(db).delete_collection(space_id=space_id, collection_id=collection_id)
    except (KnowledgeNotFound, KnowledgeValidationError, KnowledgeConflict) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return None


@router.get("/summary", response_model=KnowledgeSummaryOut)
def get_knowledge_summary(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    return KnowledgeSummaryService(db).summary(space_id=space_id, viewer_user_id=user_id)


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


@router.get("/items/{item_id}/backlinks", response_model=list[EntityLinkOut])
def get_knowledge_item_backlinks(
    item_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Generic EntityLink backlinks targeting this wiki KnowledgeItem.

    Returns the cross-object links (from Notes, Activities, Sources, Runs,
    Proposals, …) that point at this item. Item↔item semantic relations live on
    the separate ``/items/{id}/relations`` endpoint (KnowledgeItemRelation).
    """
    space_id, user_id = ids
    item = KnowledgeService(db).get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    links = EntityLinkService(db).list_links(
        space_id=space_id, entity_type="knowledge_item", entity_id=item_id, direction="backlinks"
    )
    return [entity_link_to_out(link) for link in links]


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


# ---------------------------------------------------------------------------
# Entity links (generic cross-object relation layer; read)
# ---------------------------------------------------------------------------


@router.get("/entity-links", response_model=list[EntityLinkOut])
def list_entity_links(
    source_type: str | None = Query(None),
    source_id: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Generic read over the EntityLink layer filtered by source/target endpoints."""
    space_id, _user_id = ids
    try:
        links = EntityLinkService(db).query_links(
            space_id=space_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    return [entity_link_to_out(link) for link in links]


# ---------------------------------------------------------------------------
# Notes (working knowledge; direct CRUD, not proposal-gated)
# ---------------------------------------------------------------------------


def _note_out_with_collection(db: Session, note) -> NoteOut:
    """Serialize a single note, resolving its collection membership."""
    collection_id = NoteService(db).collection_ids_for_notes(note_ids=[note.id]).get(note.id)
    return note_to_out(note, collection_id=collection_id)


@router.get("/notes", response_model=Page[NoteSummaryOut])
def list_notes(
    status: str | None = Query(None),
    project_id: str | None = Query(None),
    collection_id: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        total, notes = NoteService(db).list_notes(
            space_id=space_id,
            status=status,
            project_id=project_id,
            collection_id=collection_id,
            q=q,
            limit=limit,
            offset=offset,
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    collection_ids = NoteService(db).collection_ids_for_notes(note_ids=[n.id for n in notes])
    items = [note_to_summary_out(n, collection_id=collection_ids.get(n.id)) for n in notes]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/notes/deleted/purge")
def purge_deleted_notes(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    deleted = NoteService(db).purge_deleted_notes(space_id=space_id)
    db.commit()
    return {"deleted": deleted, "retention_days": 30}


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(
    body: NoteCreateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    try:
        note = NoteService(db).create_note(space_id=space_id, user_id=user_id, data=body.model_dump(mode="json"))
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return _note_out_with_collection(db, note)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(
    note_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    note = NoteService(db).get_note(space_id=space_id, note_id=note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _note_out_with_collection(db, note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: str,
    body: NoteUpdateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        note = NoteService(db).update_note(
            space_id=space_id,
            note_id=note_id,
            data=body.model_dump(mode="json", exclude_unset=True),
        )
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return _note_out_with_collection(db, note)


@router.delete("/notes/{note_id}", response_model=NoteOut)
def delete_note(
    note_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    try:
        note = NoteService(db).delete_note(space_id=space_id, note_id=note_id)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return _note_out_with_collection(db, note)


# ---------------------------------------------------------------------------
# Note links / backlinks (generic EntityLink layer, scoped to a note)
# ---------------------------------------------------------------------------


def _require_note(db: Session, *, space_id: str, note_id: str) -> None:
    if NoteService(db).get_note(space_id=space_id, note_id=note_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")


@router.get("/notes/{note_id}/links", response_model=list[EntityLinkOut])
def list_note_links(
    note_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    _require_note(db, space_id=space_id, note_id=note_id)
    links = EntityLinkService(db).list_links(space_id=space_id, entity_type="note", entity_id=note_id)
    return [entity_link_to_out(link) for link in links]


@router.get("/notes/{note_id}/backlinks", response_model=list[EntityLinkOut])
def list_note_backlinks(
    note_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    _require_note(db, space_id=space_id, note_id=note_id)
    links = EntityLinkService(db).list_links(
        space_id=space_id, entity_type="note", entity_id=note_id, direction="backlinks"
    )
    return [entity_link_to_out(link) for link in links]


@router.post("/notes/{note_id}/links", response_model=EntityLinkOut, status_code=201)
def create_note_link(
    note_id: str,
    body: NoteLinkCreateIn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    _require_note(db, space_id=space_id, note_id=note_id)
    if body.direction == "outgoing":
        link_data = {
            "source_type": "note",
            "source_id": note_id,
            "target_type": body.target_type,
            "target_id": body.target_id,
            "link_type": body.link_type,
            "confidence": body.confidence,
        }
    else:
        link_data = {
            "source_type": body.target_type,
            "source_id": body.target_id,
            "target_type": "note",
            "target_id": note_id,
            "link_type": body.link_type,
            "confidence": body.confidence,
        }
    try:
        link = EntityLinkService(db).create_link(space_id=space_id, user_id=user_id, data=link_data)
    except (KnowledgeNotFound, KnowledgeValidationError) as exc:
        raise _handle_knowledge_error(exc) from exc
    db.commit()
    return entity_link_to_out(link)


@router.delete("/notes/{note_id}/links/{link_id}", status_code=204)
def delete_note_link(
    note_id: str,
    link_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _user_id = ids
    _require_note(db, space_id=space_id, note_id=note_id)
    service = EntityLinkService(db)
    link = service.get_link(space_id=space_id, link_id=link_id)
    if link is None or not (
        (link.source_type == "note" and link.source_id == note_id)
        or (link.target_type == "note" and link.target_id == note_id)
    ):
        raise HTTPException(status_code=404, detail="Link not found")
    service.delete_link(space_id=space_id, link_id=link_id)
    db.commit()
