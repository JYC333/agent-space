from __future__ import annotations

from ..models import KnowledgeItem, KnowledgeItemRelation, KnowledgeItemSource, Source
from .schemas import (
    KnowledgeItemOut,
    KnowledgeItemRelationOut,
    KnowledgeItemSourceOut,
    KnowledgeItemSummaryOut,
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
        item_type=item.item_type,  # type: ignore[arg-type]
        title=item.title,
        content=item.content,
        content_format=item.content_format,  # type: ignore[arg-type]
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
    )


def knowledge_item_to_summary_out(item: KnowledgeItem) -> KnowledgeItemSummaryOut:
    return KnowledgeItemSummaryOut(
        id=item.id,
        space_id=item.space_id,
        project_id=item.project_id,
        workspace_id=item.workspace_id,
        item_type=item.item_type,  # type: ignore[arg-type]
        title=item.title,
        content_preview=_preview(item.content),
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
        note=relation.note,
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
