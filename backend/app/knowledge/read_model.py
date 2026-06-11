from __future__ import annotations

from ..models import EntityLink, KnowledgeItem, KnowledgeItemRelation, KnowledgeItemSource, Note, NoteCollection, Source
from .schemas import (
    EntityLinkOut,
    KnowledgeItemOut,
    KnowledgeItemRelationOut,
    KnowledgeItemSourceOut,
    KnowledgeItemSummaryOut,
    NoteCollectionOut,
    NoteOut,
    NoteSummaryOut,
    SourceOut,
    SourceSummaryOut,
)


def _preview(content: str, *, limit: int = 240) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def knowledge_item_to_out(item: KnowledgeItem) -> KnowledgeItemOut:
    return KnowledgeItemOut(
        id=item.id,
        space_id=item.space_id,
        project_id=item.project_id,
        workspace_id=item.workspace_id,
        root_item_id=item.root_item_id,
        supersedes_item_id=item.supersedes_item_id,
        redirect_to_item_id=item.redirect_to_item_id,
        item_type=item.item_type,  # type: ignore[arg-type]
        slug=item.slug,
        aliases=list(item.aliases_json or []),
        title=item.title,
        content=item.content,
        content_json=item.content_json,
        content_format=item.content_format,  # type: ignore[arg-type]
        content_schema_version=item.content_schema_version,
        plain_text=item.plain_text,
        excerpt=item.excerpt,
        status=item.status,  # type: ignore[arg-type]
        visibility=item.visibility,  # type: ignore[arg-type]
        verification_status=item.verification_status,  # type: ignore[arg-type]
        reflection_status=item.reflection_status,  # type: ignore[arg-type]
        tags=list(item.tags_json or []),
        confidence=item.confidence,
        source_url=item.source_url,
        owner_user_id=item.owner_user_id,
        created_by_user_id=item.created_by_user_id,
        created_by_agent_id=item.created_by_agent_id,
        created_by_run_id=item.created_by_run_id,
        source_activity_id=item.source_activity_id,
        source_artifact_id=item.source_artifact_id,
        created_from_proposal_id=item.created_from_proposal_id,
        approved_by_user_id=item.approved_by_user_id,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
        archived_at=item.archived_at,
        deprecated_at=item.deprecated_at,
    )


def knowledge_item_to_summary_out(item: KnowledgeItem) -> KnowledgeItemSummaryOut:
    return KnowledgeItemSummaryOut(
        id=item.id,
        space_id=item.space_id,
        project_id=item.project_id,
        workspace_id=item.workspace_id,
        item_type=item.item_type,  # type: ignore[arg-type]
        slug=item.slug,
        title=item.title,
        content_preview=_preview(item.content),
        excerpt=item.excerpt,
        status=item.status,  # type: ignore[arg-type]
        visibility=item.visibility,  # type: ignore[arg-type]
        verification_status=item.verification_status,  # type: ignore[arg-type]
        reflection_status=item.reflection_status,  # type: ignore[arg-type]
        tags=list(item.tags_json or []),
        confidence=item.confidence,
        version=item.version,
        updated_at=item.updated_at,
    )


def knowledge_item_relation_to_out(relation: KnowledgeItemRelation) -> KnowledgeItemRelationOut:
    return KnowledgeItemRelationOut(
        id=relation.id,
        space_id=relation.space_id,
        from_item_id=relation.from_item_id,
        to_item_id=relation.to_item_id,
        relation_type=relation.relation_type,  # type: ignore[arg-type]
        status=relation.status,  # type: ignore[arg-type]
        confidence=relation.confidence,
        evidence_summary=relation.evidence_summary,
        source_proposal_id=relation.source_proposal_id,
        created_by_user_id=relation.created_by_user_id,
        created_by_agent_id=relation.created_by_agent_id,
        created_from_assessment_id=relation.created_from_assessment_id,
        created_at=relation.created_at,
        updated_at=relation.updated_at,
    )


def source_to_out(source: Source) -> SourceOut:
    return SourceOut(
        id=source.id,
        space_id=source.space_id,
        source_type=source.source_type,  # type: ignore[arg-type]
        title=source.title,
        uri=source.uri,
        content_ref=source.content_ref,
        raw_text=source.raw_text,
        summary=source.summary,
        metadata=dict(source.metadata_json or {}),
        status=source.status,  # type: ignore[arg-type]
        source_activity_id=source.source_activity_id,
        created_by_user_id=source.created_by_user_id,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def source_to_summary_out(source: Source) -> SourceSummaryOut:
    return SourceSummaryOut(
        id=source.id,
        space_id=source.space_id,
        source_type=source.source_type,  # type: ignore[arg-type]
        title=source.title,
        uri=source.uri,
        status=source.status,  # type: ignore[arg-type]
        source_activity_id=source.source_activity_id,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def knowledge_item_source_to_out(link: KnowledgeItemSource) -> KnowledgeItemSourceOut:
    return KnowledgeItemSourceOut(
        id=link.id,
        space_id=link.space_id,
        knowledge_item_id=link.knowledge_item_id,
        source_id=link.source_id,
        relation_type=link.relation_type,  # type: ignore[arg-type]
        locator=link.locator,
        quote=link.quote,
        note=link.note,
        confidence=link.confidence,
        created_by_user_id=link.created_by_user_id,
        created_at=link.created_at,
    )


def note_to_out(note: Note, *, collection_id: str | None = None) -> NoteOut:
    return NoteOut(
        id=note.id,
        space_id=note.space_id,
        title=note.title,
        content_json=note.content_json,
        content_format=note.content_format,  # type: ignore[arg-type]
        content_schema_version=note.content_schema_version,
        plain_text=note.plain_text,
        excerpt=note.excerpt,
        status=note.status,  # type: ignore[arg-type]
        primary_project_id=note.primary_project_id,
        collection_id=collection_id,
        created_from_activity_id=note.created_from_activity_id,
        created_by_user_id=note.created_by_user_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        archived_at=note.archived_at,
        deleted_at=note.deleted_at,
    )


def note_to_summary_out(note: Note, *, collection_id: str | None = None) -> NoteSummaryOut:
    return NoteSummaryOut(
        id=note.id,
        space_id=note.space_id,
        title=note.title,
        excerpt=note.excerpt,
        status=note.status,  # type: ignore[arg-type]
        content_format=note.content_format,  # type: ignore[arg-type]
        primary_project_id=note.primary_project_id,
        collection_id=collection_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        deleted_at=note.deleted_at,
    )


def note_collection_to_out(collection: NoteCollection) -> NoteCollectionOut:
    return NoteCollectionOut(
        id=collection.id,
        space_id=collection.space_id,
        parent_id=collection.parent_id,
        name=collection.name,
        system_role=collection.system_role,  # type: ignore[arg-type]
        sort_order=collection.sort_order,
        is_system=collection.is_system,
        is_hidden=collection.is_hidden,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def entity_link_to_out(link: EntityLink) -> EntityLinkOut:
    return EntityLinkOut(
        id=link.id,
        space_id=link.space_id,
        source_type=link.source_type,  # type: ignore[arg-type]
        source_id=link.source_id,
        target_type=link.target_type,  # type: ignore[arg-type]
        target_id=link.target_id,
        link_type=link.link_type,  # type: ignore[arg-type]
        confidence=link.confidence,
        status=link.status,  # type: ignore[arg-type]
        created_by_user_id=link.created_by_user_id,
        created_at=link.created_at,
    )
