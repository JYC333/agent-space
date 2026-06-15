from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, or_
from sqlalchemy.orm import Session

from ..proposals import ProposalService
from ..models import (
    ActivityRecord,
    Artifact,
    EntityLink,
    KnowledgeItem,
    KnowledgeItemRelation,
    KnowledgeItemSource,
    Note,
    NoteCollection,
    NoteCollectionItem,
    Project,
    Proposal,
    Run,
    Source,
    Workspace,
)


class KnowledgeError(Exception):
    pass


class KnowledgeNotFound(KnowledgeError):
    pass


class KnowledgeValidationError(KnowledgeError):
    pass


class KnowledgeConflict(KnowledgeError):
    pass


def can_read_knowledge_item(
    item: KnowledgeItem,
    *,
    viewer_user_id: str,
    space_id: str,
    workspace_id: str | None = None,
) -> bool:
    if item.space_id != space_id:
        return False
    if item.visibility == "space_shared":
        return True
    if item.visibility == "workspace_shared":
        # TODO: narrow this to workspace roles once workspace membership exists.
        del workspace_id
        return True
    if item.visibility in {"private", "restricted"}:
        if item.owner_user_id is not None:
            return item.owner_user_id == viewer_user_id
        return item.created_by_user_id == viewer_user_id
    return False


def can_apply_knowledge_mutation(item: KnowledgeItem, proposal: Proposal) -> bool:
    if item.space_id != proposal.space_id:
        return False
    if item.visibility in {"space_shared", "workspace_shared"}:
        return True
    if item.visibility in {"private", "restricted"}:
        actor_user_id = proposal.created_by_user_id
        if actor_user_id is None:
            return False
        owner_user_id = item.owner_user_id or item.created_by_user_id
        return owner_user_id == actor_user_id
    return False


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_items(
        self,
        *,
        space_id: str,
        viewer_user_id: str,
        item_type: str | None = None,
        status: str | None = None,
        visibility: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        tag: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[KnowledgeItem]]:
        query = self._db.query(KnowledgeItem).filter(KnowledgeItem.space_id == space_id)
        query = query.filter(self._readable_item_filter(viewer_user_id=viewer_user_id))
        if item_type:
            query = query.filter(KnowledgeItem.item_type == item_type)
        if status:
            query = query.filter(KnowledgeItem.status == status)
        if visibility:
            query = query.filter(KnowledgeItem.visibility == visibility)
        if project_id:
            query = query.filter(KnowledgeItem.project_id == project_id)
        if workspace_id:
            query = query.filter(KnowledgeItem.workspace_id == workspace_id)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(KnowledgeItem.title.ilike(like), KnowledgeItem.content.ilike(like)))
        if tag:
            # LIKE on JSON text for tag matching; upgrade to @> JSON containment
            # if this becomes a performance concern.
            query = query.filter(KnowledgeItem.tags_json.cast(String).like(f'%"{tag}"%'))
        total = query.count()
        items = (
            query.order_by(KnowledgeItem.updated_at.desc(), KnowledgeItem.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, items

    def get_item(self, *, space_id: str, item_id: str) -> KnowledgeItem | None:
        return self._base_item_query(space_id=space_id, item_id=item_id).first()

    def get_readable_item(self, *, space_id: str, viewer_user_id: str, item_id: str) -> KnowledgeItem | None:
        return (
            self._base_item_query(space_id=space_id, item_id=item_id)
            .filter(self._readable_item_filter(viewer_user_id=viewer_user_id))
            .first()
        )

    def get_relation(self, *, space_id: str, relation_id: str) -> KnowledgeItemRelation | None:
        return (
            self._db.query(KnowledgeItemRelation)
            .filter(KnowledgeItemRelation.id == relation_id, KnowledgeItemRelation.space_id == space_id)
            .first()
        )

    def list_item_relations(self, *, space_id: str, viewer_user_id: str, item_id: str) -> list[KnowledgeItemRelation]:
        if self.get_readable_item(space_id=space_id, viewer_user_id=viewer_user_id, item_id=item_id) is None:
            raise KnowledgeNotFound("Knowledge item not found")
        relations = (
            self._db.query(KnowledgeItemRelation)
            .filter(
                KnowledgeItemRelation.space_id == space_id,
                or_(KnowledgeItemRelation.from_item_id == item_id, KnowledgeItemRelation.to_item_id == item_id),
            )
            .order_by(KnowledgeItemRelation.created_at.desc())
            .all()
        )
        endpoint_ids = {r.from_item_id for r in relations} | {r.to_item_id for r in relations}
        if not endpoint_ids:
            return []
        endpoints = {
            row.id: row
            for row in self._db.query(KnowledgeItem)
            .filter(KnowledgeItem.space_id == space_id, KnowledgeItem.id.in_(endpoint_ids))
            .all()
        }
        readable_ids = {
            row_id
            for row_id, row in endpoints.items()
            if can_read_knowledge_item(row, viewer_user_id=viewer_user_id, space_id=space_id)
        }
        return [r for r in relations if r.from_item_id in readable_ids and r.to_item_id in readable_ids]

    def create_item_proposal(self, *, space_id: str, user_id: str, data: dict[str, Any]) -> Proposal:
        self._validate_optional_associations(space_id=space_id, data=data)
        source_run_id = data.get("source_run_id")
        source_artifact_id = data.get("source_artifact_id")
        source_activity_id = data.get("source_activity_id")
        self._assert_optional_run(space_id=space_id, run_id=source_run_id)
        self._assert_optional_activity(space_id=space_id, activity_id=source_activity_id)
        self._assert_optional_artifact(space_id=space_id, artifact_id=source_artifact_id)
        payload = {
            "operation": "create",
            "item_type": data["item_type"],
            "title": data["title"],
            "slug": data.get("slug"),
            "aliases": list(data.get("aliases") or []),
            "content": data["content"],
            "content_json": data.get("content_json"),
            "content_format": data["content_format"],
            "content_schema_version": data.get("content_schema_version") or 1,
            "visibility": data["visibility"],
            "owner_user_id": user_id,
            "project_id": data.get("project_id"),
            "workspace_id": data.get("workspace_id"),
            "tags": list(data.get("tags") or []),
            "confidence": data.get("confidence"),
            "source_url": data.get("source_url"),
            "source_refs": list(data.get("source_refs") or []),
            "source_activity_id": source_activity_id,
            "source_run_id": source_run_id,
            "source_artifact_id": source_artifact_id,
            "verification_status": data["verification_status"],
            "reflection_status": data["reflection_status"],
        }
        return ProposalService(self._db).create_user_proposal(
            space_id=space_id,
            user_id=user_id,
            proposal_type="knowledge_create",
            title=data["title"],
            payload_json=payload,
            rationale=data.get("rationale") or "Create Knowledge item",
            workspace_id=data.get("workspace_id"),
            risk_level="medium",
            target_visibility=data["visibility"],
            policy_metadata_json={"knowledge_operation": "create"},
        )

    def create_update_proposal(self, *, space_id: str, user_id: str, item_id: str, data: dict[str, Any]) -> Proposal:
        item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=item_id)
        if item is None:
            raise KnowledgeNotFound("Knowledge item not found")
        if item.status not in {"active", "draft"}:
            raise KnowledgeValidationError("target Knowledge item is not active")
        payload = {
            "operation": "update",
            "target_item_id": item_id,
            "title": data["title"],
            "slug": data.get("slug"),
            "aliases": list(data.get("aliases") or []),
            "content": data["content"],
            "content_json": data.get("content_json"),
            "content_format": data["content_format"],
            "content_schema_version": data.get("content_schema_version") or 1,
            "tags": list(data.get("tags") or []),
            "confidence": data.get("confidence"),
            "source_refs": list(data.get("source_refs") or []),
            "verification_status": data["verification_status"],
            "reflection_status": data["reflection_status"],
        }
        return ProposalService(self._db).create_user_proposal(
            space_id=space_id,
            user_id=user_id,
            proposal_type="knowledge_update",
            title=f"Update Knowledge: {item.title}",
            payload_json=payload,
            rationale=data.get("rationale") or "Update Knowledge item",
            workspace_id=item.workspace_id,
            risk_level="medium",
            target_visibility=item.visibility,
            policy_metadata_json={"knowledge_operation": "update", "target_item_id": item_id},
        )

    def create_archive_proposal(self, *, space_id: str, user_id: str, item_id: str) -> Proposal:
        item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=item_id)
        if item is None:
            raise KnowledgeNotFound("Knowledge item not found")
        if item.status not in {"active", "draft"}:
            raise KnowledgeValidationError("target Knowledge item is not active")
        return ProposalService(self._db).create_user_proposal(
            space_id=space_id,
            user_id=user_id,
            proposal_type="knowledge_archive",
            title=f"Archive Knowledge: {item.title}",
            payload_json={"operation": "archive", "target_item_id": item_id},
            rationale="Archive Knowledge item",
            workspace_id=item.workspace_id,
            risk_level="medium",
            target_visibility=item.visibility,
            policy_metadata_json={"knowledge_operation": "archive", "target_item_id": item_id},
        )

    def create_relation_proposal(self, *, space_id: str, user_id: str, data: dict[str, Any]) -> Proposal:
        from_item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=data["from_item_id"])
        to_item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=data["to_item_id"])
        if from_item is None or to_item is None:
            raise KnowledgeNotFound("Knowledge item not found")
        payload = {
            "operation": "relation_create",
            "from_item_id": data["from_item_id"],
            "to_item_id": data["to_item_id"],
            "relation_type": data["relation_type"],
            "confidence": data.get("confidence"),
            "evidence_summary": data.get("evidence_summary"),
            "status": data.get("status") or "active",
        }
        return ProposalService(self._db).create_user_proposal(
            space_id=space_id,
            user_id=user_id,
            proposal_type="knowledge_relation_create",
            title=f"Relate Knowledge: {from_item.title} -> {to_item.title}",
            payload_json=payload,
            rationale=data.get("rationale") or "Create Knowledge relation",
            risk_level="medium",
            policy_metadata_json={"knowledge_operation": "relation_create"},
        )

    def create_relation_delete_proposal(self, *, space_id: str, user_id: str, relation_id: str) -> Proposal:
        relation = self.get_relation(space_id=space_id, relation_id=relation_id)
        if relation is None:
            raise KnowledgeNotFound("Knowledge relation not found")
        from_item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=relation.from_item_id)
        to_item = self.get_readable_item(space_id=space_id, viewer_user_id=user_id, item_id=relation.to_item_id)
        if from_item is None or to_item is None:
            raise KnowledgeNotFound("Knowledge relation not found")
        return ProposalService(self._db).create_user_proposal(
            space_id=space_id,
            user_id=user_id,
            proposal_type="knowledge_relation_delete",
            title=f"Archive Knowledge relation: {relation.relation_type}",
            payload_json={"operation": "relation_delete", "relation_id": relation_id},
            rationale="Archive Knowledge relation",
            risk_level="medium",
            policy_metadata_json={"knowledge_operation": "relation_delete", "relation_id": relation_id},
        )

    def _validate_optional_associations(self, *, space_id: str, data: dict[str, Any]) -> None:
        project_id = data.get("project_id")
        if project_id is not None:
            exists = self._db.query(Project.id).filter(Project.id == project_id, Project.space_id == space_id).first()
            if not exists:
                raise KnowledgeValidationError("project_id does not belong to this space")
        workspace_id = data.get("workspace_id")
        if workspace_id is not None:
            exists = (
                self._db.query(Workspace.id)
                .filter(Workspace.id == workspace_id, Workspace.space_id == space_id)
                .first()
            )
            if not exists:
                raise KnowledgeValidationError("workspace_id does not belong to this space")

    def _assert_optional_run(self, *, space_id: str, run_id: str | None) -> None:
        if run_id is None:
            return
        exists = self._db.query(Run.id).filter(Run.id == run_id, Run.space_id == space_id).first()
        if not exists:
            raise KnowledgeValidationError("source_run_id does not belong to this space")

    def _assert_optional_artifact(self, *, space_id: str, artifact_id: str | None) -> None:
        if artifact_id is None:
            return
        exists = self._db.query(Artifact.id).filter(Artifact.id == artifact_id, Artifact.space_id == space_id).first()
        if not exists:
            raise KnowledgeValidationError("source_artifact_id does not belong to this space")

    def _assert_optional_activity(self, *, space_id: str, activity_id: str | None) -> None:
        if activity_id is None:
            return
        exists = (
            self._db.query(ActivityRecord.id)
            .filter(ActivityRecord.id == activity_id, ActivityRecord.space_id == space_id)
            .first()
        )
        if not exists:
            raise KnowledgeValidationError("source_activity_id does not belong to this space")

    def _base_item_query(self, *, space_id: str, item_id: str):
        return self._db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id, KnowledgeItem.space_id == space_id)

    @staticmethod
    def _readable_item_filter(*, viewer_user_id: str):
        return or_(
            KnowledgeItem.visibility.in_(("space_shared", "workspace_shared")),
            and_(KnowledgeItem.visibility.in_(("private", "restricted")), KnowledgeItem.owner_user_id == viewer_user_id),
            and_(
                KnowledgeItem.visibility.in_(("private", "restricted")),
                KnowledgeItem.owner_user_id.is_(None),
                KnowledgeItem.created_by_user_id == viewer_user_id,
            ),
        )


_VALID_ITEM_TYPES: frozenset[str] = frozenset({
    "concept", "claim", "lesson", "procedure",
    "decision", "question", "answer", "summary",
})
_VALID_CONTENT_FORMATS: frozenset[str] = frozenset({"markdown", "plain", "prosemirror_json"})
_VALID_VISIBILITY: frozenset[str] = frozenset({
    "private", "space_shared", "workspace_shared", "restricted",
})
_VALID_VERIFICATION_STATUS: frozenset[str] = frozenset({"unverified", "needs_review", "verified"})
_VALID_REFLECTION_STATUS: frozenset[str] = frozenset({"unreviewed", "reviewed", "distilled"})
_VALID_RELATION_TYPES: frozenset[str] = frozenset({
    "related_to", "explains", "depends_on", "prerequisite_of",
    "part_of", "example_of", "applies_to", "supports",
    "contradicts", "derived_from", "summarizes", "updates",
})
_VALID_RELATION_CREATE_STATUS: frozenset[str] = frozenset({"candidate", "active"})


def _flatten_content_json(node: Any) -> str:
    """Best-effort plain-text extraction from structured editor JSON.

    Collects every ``text`` leaf in document order; unknown shapes contribute
    nothing rather than raising, so the projection never blocks a write.
    """

    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                parts.append(text)
            walk(value.get("content"))
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return " ".join(parts)


def derive_knowledge_projection(
    *,
    title: str | None,
    content: str | None,
    content_json: Any | None = None,
    summary: str | None = None,
    excerpt_limit: int = 280,
) -> tuple[str | None, str | None]:
    """Derive the stored ``plain_text`` / ``excerpt`` projections for a KnowledgeItem.

    ``plain_text`` flattens title + body (preferring structured ``content_json``
    text when present, else the markdown/plain ``content``) for search/preview;
    ``excerpt`` is a short preview taken from ``plain_text`` (or ``summary``).
    These are stored at write time so list/search reads never re-parse content.
    """

    body = _flatten_content_json(content_json) if content_json else ""
    if not body.strip():
        body = content or ""
    segments = [seg for seg in (title, body) if seg and seg.strip()]
    plain_text = " ".join(" ".join(seg.split()) for seg in segments) or None
    excerpt = derive_note_excerpt(plain_text or summary, limit=excerpt_limit)
    return plain_text, excerpt


class KnowledgeProposalApplier:
    def __init__(self, db: Session) -> None:
        self._db = db

    def apply_create(self, proposal: Proposal, *, user_id: str) -> KnowledgeItem:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "create")
        item_type = self._required_str(payload, "item_type")
        if item_type not in _VALID_ITEM_TYPES:
            raise KnowledgeValidationError(f"invalid item_type: {item_type!r}")
        content_format = payload.get("content_format") or "markdown"
        if content_format not in _VALID_CONTENT_FORMATS:
            raise KnowledgeValidationError(f"invalid content_format: {content_format!r}")
        visibility = payload.get("visibility") or "space_shared"
        if visibility not in _VALID_VISIBILITY:
            raise KnowledgeValidationError(f"invalid visibility: {visibility!r}")
        verification_status = payload.get("verification_status") or "unverified"
        if verification_status not in _VALID_VERIFICATION_STATUS:
            raise KnowledgeValidationError(f"invalid verification_status: {verification_status!r}")
        reflection_status = payload.get("reflection_status") or "unreviewed"
        if reflection_status not in _VALID_REFLECTION_STATUS:
            raise KnowledgeValidationError(f"invalid reflection_status: {reflection_status!r}")
        self._validate_confidence(payload)
        requested_owner_user_id = payload.get("owner_user_id")
        if requested_owner_user_id is not None and requested_owner_user_id != proposal.created_by_user_id:
            raise KnowledgeValidationError("Knowledge owner must be the proposal creator")
        if visibility in {"private", "restricted"} and proposal.created_by_user_id is None:
            raise KnowledgeValidationError("private or restricted Knowledge requires a human owner")
        title = self._required_str(payload, "title")
        content = self._required_str(payload, "content")
        content_json = payload.get("content_json")
        plain_text, excerpt = derive_knowledge_projection(
            title=title, content=content, content_json=content_json
        )
        item = KnowledgeItem(
            space_id=proposal.space_id,
            project_id=payload.get("project_id"),
            workspace_id=payload.get("workspace_id"),
            item_type=item_type,
            slug=payload.get("slug"),
            aliases_json=list(payload.get("aliases") or []) or None,
            title=title,
            content=content,
            content_json=content_json,
            content_format=content_format,
            content_schema_version=payload.get("content_schema_version") or 1,
            plain_text=plain_text,
            excerpt=excerpt,
            status="active",
            visibility=visibility,
            verification_status=verification_status,
            reflection_status=reflection_status,
            tags_json=list(payload.get("tags") or []),
            confidence=payload.get("confidence"),
            source_url=payload.get("source_url"),
            owner_user_id=proposal.created_by_user_id,
            created_by_user_id=proposal.created_by_user_id,
            created_by_agent_id=proposal.created_by_agent_id,
            created_by_run_id=payload.get("source_run_id") or proposal.created_by_run_id,
            source_activity_id=payload.get("source_activity_id"),
            source_artifact_id=payload.get("source_artifact_id"),
            created_from_proposal_id=proposal.id,
            approved_by_user_id=user_id,
            version=1,
        )
        self._db.add(item)
        self._db.flush()
        item.root_item_id = item.id
        self._db.flush()
        self._write_source_provenance(item, payload)
        return item

    def apply_update(self, proposal: Proposal, *, user_id: str) -> KnowledgeItem:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "update")
        target = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "target_item_id"))
        if not can_apply_knowledge_mutation(target, proposal):
            raise KnowledgeValidationError("Knowledge item not found or not editable")
        if target.status not in {"active", "draft"}:
            raise KnowledgeValidationError("target Knowledge item is not active")
        if payload.get("content_format") and payload["content_format"] not in _VALID_CONTENT_FORMATS:
            raise KnowledgeValidationError(f"invalid content_format: {payload['content_format']!r}")
        if payload.get("verification_status") and payload["verification_status"] not in _VALID_VERIFICATION_STATUS:
            raise KnowledgeValidationError(f"invalid verification_status: {payload['verification_status']!r}")
        if payload.get("reflection_status") and payload["reflection_status"] not in _VALID_REFLECTION_STATUS:
            raise KnowledgeValidationError(f"invalid reflection_status: {payload['reflection_status']!r}")
        self._validate_confidence(payload)
        now = datetime.now(UTC)
        root_id = target.root_item_id or target.id
        target.root_item_id = root_id
        target.status = "superseded"
        target.updated_at = now
        title = self._required_str(payload, "title")
        content = self._required_str(payload, "content")
        content_json = payload.get("content_json")
        slug = payload.get("slug") or target.slug
        aliases = list(payload.get("aliases") or []) or (target.aliases_json or None)
        plain_text, excerpt = derive_knowledge_projection(
            title=title, content=content, content_json=content_json
        )
        item = KnowledgeItem(
            space_id=proposal.space_id,
            project_id=target.project_id,
            workspace_id=target.workspace_id,
            root_item_id=root_id,
            supersedes_item_id=target.id,
            item_type=target.item_type,
            slug=slug,
            aliases_json=aliases,
            title=title,
            content=content,
            content_json=content_json,
            content_format=payload.get("content_format") or target.content_format,
            content_schema_version=payload.get("content_schema_version") or target.content_schema_version,
            plain_text=plain_text,
            excerpt=excerpt,
            status="active",
            visibility=target.visibility,
            verification_status=payload.get("verification_status") or target.verification_status,
            reflection_status=payload.get("reflection_status") or target.reflection_status,
            tags_json=list(payload.get("tags") or []),
            confidence=payload.get("confidence"),
            source_url=target.source_url,
            owner_user_id=target.owner_user_id or target.created_by_user_id,
            created_by_user_id=proposal.created_by_user_id,
            created_by_agent_id=proposal.created_by_agent_id,
            created_by_run_id=proposal.created_by_run_id,
            source_activity_id=target.source_activity_id,
            source_artifact_id=target.source_artifact_id,
            created_from_proposal_id=proposal.id,
            approved_by_user_id=user_id,
            version=target.version + 1,
        )
        self._db.add(item)
        self._db.flush()
        self._write_source_provenance(item, payload)
        return item

    def _write_source_provenance(self, item: KnowledgeItem, payload: dict[str, Any]) -> None:
        """Persist free-form payload ``source_refs`` as ProvenanceLink rows for this item.

        Internal provenance pointers (activity/run/artifact/...) now live on the
        first-class ProvenanceLink table (target_type="knowledge"); the wiki
        Source/KnowledgeItemSource layer handles curated external evidence.
        """
        from ..memory import (
            TARGET_KNOWLEDGE,
            source_refs_to_provenance_entries,
            write_provenance_links,
        )

        entries = source_refs_to_provenance_entries(payload.get("source_refs"))
        if entries:
            write_provenance_links(
                self._db,
                space_id=item.space_id,
                target_type=TARGET_KNOWLEDGE,
                target_id=item.id,
                entries=entries,
            )
            self._db.flush()

    def apply_archive(self, proposal: Proposal, *, user_id: str) -> KnowledgeItem:
        del user_id
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "archive")
        item = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "target_item_id"))
        if not can_apply_knowledge_mutation(item, proposal):
            raise KnowledgeValidationError("Knowledge item not found or not editable")
        if item.status not in {"active", "draft"}:
            raise KnowledgeValidationError("target Knowledge item is not active")
        item.status = "archived"
        item.archived_at = datetime.now(UTC)
        item.updated_at = item.archived_at
        self._db.flush()
        return item

    def apply_relation_create(self, proposal: Proposal, *, user_id: str) -> KnowledgeItemRelation:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "relation_create")
        relation_type = self._required_str(payload, "relation_type")
        if relation_type not in _VALID_RELATION_TYPES:
            raise KnowledgeValidationError(f"invalid relation_type: {relation_type!r}")
        status = payload.get("status") or "active"
        if status not in _VALID_RELATION_CREATE_STATUS:
            raise KnowledgeValidationError(
                f"invalid relation status for creation: {status!r}; must be 'candidate' or 'active'"
            )
        self._validate_confidence(payload)
        from_item = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "from_item_id"))
        to_item = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "to_item_id"))
        if from_item.space_id != to_item.space_id or from_item.space_id != proposal.space_id:
            raise KnowledgeValidationError("Knowledge relation endpoints must be in the same space")
        if not can_apply_knowledge_mutation(from_item, proposal) or not can_apply_knowledge_mutation(to_item, proposal):
            raise KnowledgeValidationError("Knowledge item not found")
        if status == "active":
            existing = (
                self._db.query(KnowledgeItemRelation)
                .filter(
                    KnowledgeItemRelation.space_id == proposal.space_id,
                    KnowledgeItemRelation.from_item_id == from_item.id,
                    KnowledgeItemRelation.to_item_id == to_item.id,
                    KnowledgeItemRelation.relation_type == relation_type,
                    KnowledgeItemRelation.status == "active",
                )
                .first()
            )
            if existing is not None:
                raise KnowledgeValidationError("active Knowledge relation already exists")
        relation = KnowledgeItemRelation(
            space_id=proposal.space_id,
            from_item_id=from_item.id,
            to_item_id=to_item.id,
            relation_type=relation_type,
            status=status,
            confidence=payload.get("confidence"),
            evidence_summary=payload.get("evidence_summary"),
            source_proposal_id=proposal.id,
            created_by_user_id=proposal.created_by_user_id or user_id,
            created_by_agent_id=proposal.created_by_agent_id,
        )
        self._db.add(relation)
        self._db.flush()
        return relation

    def apply_relation_delete(self, proposal: Proposal, *, user_id: str) -> KnowledgeItemRelation:
        del user_id
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "relation_delete")
        relation = (
            self._db.query(KnowledgeItemRelation)
            .filter(
                KnowledgeItemRelation.id == self._required_str(payload, "relation_id"),
                KnowledgeItemRelation.space_id == proposal.space_id,
            )
            .first()
        )
        if relation is None:
            raise KnowledgeNotFound("Knowledge relation not found")
        from_item = self._get_item_or_raise(proposal.space_id, relation.from_item_id)
        to_item = self._get_item_or_raise(proposal.space_id, relation.to_item_id)
        if from_item.space_id != to_item.space_id or from_item.space_id != proposal.space_id:
            raise KnowledgeValidationError("Knowledge relation not found")
        if not can_apply_knowledge_mutation(from_item, proposal) or not can_apply_knowledge_mutation(to_item, proposal):
            raise KnowledgeValidationError("Knowledge relation not found")
        relation.status = "archived"
        relation.updated_at = datetime.now(UTC)
        self._db.flush()
        return relation

    def _get_item_or_raise(self, space_id: str, item_id: str) -> KnowledgeItem:
        item = (
            self._db.query(KnowledgeItem)
            .filter(KnowledgeItem.id == item_id, KnowledgeItem.space_id == space_id)
            .first()
        )
        if item is None:
            raise KnowledgeNotFound("Knowledge item not found")
        return item

    @staticmethod
    def _expect_operation(payload: dict[str, Any], operation: str) -> None:
        if payload.get("operation") != operation:
            raise KnowledgeValidationError(f"expected operation={operation!r}")

    @staticmethod
    def _required_str(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeValidationError(f"missing required {key!r}")
        return value

    @staticmethod
    def _validate_confidence(payload: dict[str, Any]) -> None:
        confidence = payload.get("confidence")
        if confidence is None:
            return
        if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
            raise KnowledgeValidationError(
                f"confidence must be a number between 0 and 1, got {confidence!r}"
            )


_VALID_SOURCE_TYPES: frozenset[str] = frozenset({
    "activity_record", "chat_capture", "webpage", "article", "paper",
    "pdf", "file", "email", "manual_reference", "external_note",
})
_VALID_SOURCE_STATUS: frozenset[str] = frozenset({"raw", "processing", "processed", "archived", "error"})
_VALID_ITEM_SOURCE_RELATION_TYPES: frozenset[str] = frozenset({
    "derived_from", "supported_by", "cites", "summarizes", "mentions",
})


class SourceService:
    """Direct (non-proposal) CRUD for provenance/evidence Sources and the
    KnowledgeItemSource evidence links between wiki items and Sources.

    Sources are raw material/evidence, not semantic wiki content, so they do not
    flow through the proposal → approval workflow that governs KnowledgeItem.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ----- Source CRUD ----------------------------------------------------
    def create_source(self, *, space_id: str, user_id: str | None, data: dict[str, Any]) -> Source:
        source_type = data.get("source_type")
        if source_type not in _VALID_SOURCE_TYPES:
            raise KnowledgeValidationError(f"invalid source_type: {source_type!r}")
        status = data.get("status") or "raw"
        if status not in _VALID_SOURCE_STATUS:
            raise KnowledgeValidationError(f"invalid source status: {status!r}")
        activity_id = data.get("source_activity_id")
        if activity_id is not None:
            exists = (
                self._db.query(ActivityRecord.id)
                .filter(ActivityRecord.id == activity_id, ActivityRecord.space_id == space_id)
                .first()
            )
            if not exists:
                raise KnowledgeValidationError("source_activity_id does not belong to this space")
        source = Source(
            space_id=space_id,
            source_type=source_type,
            title=data["title"],
            uri=data.get("uri"),
            content_ref=data.get("content_ref"),
            raw_text=data.get("raw_text"),
            summary=data.get("summary"),
            metadata_json=dict(data.get("metadata") or {}),
            status=status,
            source_activity_id=activity_id,
            created_by_user_id=user_id,
        )
        self._db.add(source)
        self._db.flush()
        return source

    def list_sources(
        self,
        *,
        space_id: str,
        source_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Source]]:
        query = self._db.query(Source).filter(Source.space_id == space_id)
        if source_type:
            query = query.filter(Source.source_type == source_type)
        if status:
            query = query.filter(Source.status == status)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Source.title.ilike(like), Source.summary.ilike(like)))
        total = query.count()
        rows = (
            query.order_by(Source.updated_at.desc(), Source.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, rows

    def get_source(self, *, space_id: str, source_id: str) -> Source | None:
        return (
            self._db.query(Source)
            .filter(Source.id == source_id, Source.space_id == space_id)
            .first()
        )

    def update_source(self, *, space_id: str, source_id: str, data: dict[str, Any]) -> Source:
        source = self.get_source(space_id=space_id, source_id=source_id)
        if source is None:
            raise KnowledgeNotFound("Source not found")
        if "status" in data and data["status"] is not None:
            if data["status"] not in _VALID_SOURCE_STATUS:
                raise KnowledgeValidationError(f"invalid source status: {data['status']!r}")
            source.status = data["status"]
        for field in ("title", "uri", "content_ref", "raw_text", "summary"):
            if field in data and data[field] is not None:
                setattr(source, field, data[field])
        if "metadata" in data and data["metadata"] is not None:
            source.metadata_json = dict(data["metadata"])
        source.updated_at = datetime.now(UTC)
        self._db.flush()
        return source

    def archive_source(self, *, space_id: str, source_id: str) -> Source:
        source = self.get_source(space_id=space_id, source_id=source_id)
        if source is None:
            raise KnowledgeNotFound("Source not found")
        source.status = "archived"
        source.updated_at = datetime.now(UTC)
        self._db.flush()
        return source

    # ----- Item <-> Source evidence links --------------------------------
    def link_source(
        self, *, space_id: str, user_id: str | None, item_id: str, data: dict[str, Any]
    ) -> KnowledgeItemSource:
        item = self._get_item(space_id=space_id, item_id=item_id)
        if item is None:
            raise KnowledgeNotFound("Knowledge item not found")
        source_id = data.get("source_id")
        source = self.get_source(space_id=space_id, source_id=source_id) if source_id else None
        if source is None:
            raise KnowledgeNotFound("Source not found")
        relation_type = data.get("relation_type") or "derived_from"
        if relation_type not in _VALID_ITEM_SOURCE_RELATION_TYPES:
            raise KnowledgeValidationError(f"invalid relation_type: {relation_type!r}")
        confidence = data.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            raise KnowledgeValidationError("confidence must be between 0 and 1")
        existing = (
            self._db.query(KnowledgeItemSource)
            .filter(
                KnowledgeItemSource.knowledge_item_id == item_id,
                KnowledgeItemSource.source_id == source_id,
                KnowledgeItemSource.relation_type == relation_type,
            )
            .first()
        )
        if existing is not None:
            raise KnowledgeValidationError("evidence link already exists")
        link = KnowledgeItemSource(
            space_id=space_id,
            knowledge_item_id=item_id,
            source_id=source_id,
            relation_type=relation_type,
            locator=data.get("locator"),
            quote=data.get("quote"),
            note=data.get("note"),
            confidence=confidence,
            created_by_user_id=user_id,
        )
        self._db.add(link)
        self._db.flush()
        return link

    def unlink_source(self, *, space_id: str, item_id: str, link_id: str) -> None:
        link = (
            self._db.query(KnowledgeItemSource)
            .filter(
                KnowledgeItemSource.id == link_id,
                KnowledgeItemSource.space_id == space_id,
                KnowledgeItemSource.knowledge_item_id == item_id,
            )
            .first()
        )
        if link is None:
            raise KnowledgeNotFound("Evidence link not found")
        self._db.delete(link)
        self._db.flush()

    def list_item_sources(self, *, space_id: str, item_id: str) -> list[KnowledgeItemSource]:
        if self._get_item(space_id=space_id, item_id=item_id) is None:
            raise KnowledgeNotFound("Knowledge item not found")
        return (
            self._db.query(KnowledgeItemSource)
            .filter(
                KnowledgeItemSource.space_id == space_id,
                KnowledgeItemSource.knowledge_item_id == item_id,
            )
            .order_by(KnowledgeItemSource.created_at.desc())
            .all()
        )

    def list_items_for_source(self, *, space_id: str, source_id: str) -> list[KnowledgeItemSource]:
        if self.get_source(space_id=space_id, source_id=source_id) is None:
            raise KnowledgeNotFound("Source not found")
        return (
            self._db.query(KnowledgeItemSource)
            .filter(
                KnowledgeItemSource.space_id == space_id,
                KnowledgeItemSource.source_id == source_id,
            )
            .order_by(KnowledgeItemSource.created_at.desc())
            .all()
        )

    def _get_item(self, *, space_id: str, item_id: str) -> KnowledgeItem | None:
        return (
            self._db.query(KnowledgeItem)
            .filter(KnowledgeItem.id == item_id, KnowledgeItem.space_id == space_id)
            .first()
        )


# ---------------------------------------------------------------------------
# Notes (working knowledge; direct CRUD, not proposal-gated)
# ---------------------------------------------------------------------------

NOTE_DELETED_RETENTION_DAYS = 30

_VALID_NOTE_STATUS: frozenset[str] = frozenset({"active", "archived", "deleted"})
_VALID_NOTE_CONTENT_FORMATS: frozenset[str] = frozenset({"markdown", "plain", "prosemirror_json"})


def derive_note_excerpt(text: str | None, *, limit: int = 280) -> str | None:
    if not text:
        return None
    normalized = " ".join(text.split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def derive_note_projection(
    *,
    content_json: Any | None = None,
    plain_text: str | None = None,
    excerpt: str | None = None,
) -> tuple[str | None, str | None]:
    """Derive stored note text projections from structured JSON or stored plain text."""

    projected_plain_text = _flatten_content_json(content_json) if content_json is not None else plain_text
    if projected_plain_text is not None and not projected_plain_text.strip():
        projected_plain_text = None
    return projected_plain_text, excerpt or derive_note_excerpt(projected_plain_text)


class NoteCollectionService:
    """CRUD and invariants for the space-scoped Notes collection tree."""

    _SYSTEM_ROLES = frozenset({"inbox", "archive"})

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_collections(self, *, space_id: str) -> list[NoteCollection]:
        return (
            self._db.query(NoteCollection)
            .filter(NoteCollection.space_id == space_id)
            .order_by(NoteCollection.parent_id.asc().nullsfirst(), NoteCollection.sort_order.asc(), NoteCollection.name.asc())
            .all()
        )

    def get_collection(self, *, space_id: str, collection_id: str) -> NoteCollection | None:
        return (
            self._db.query(NoteCollection)
            .filter(NoteCollection.id == collection_id, NoteCollection.space_id == space_id)
            .first()
        )

    def get_inbox_collection(self, *, space_id: str) -> NoteCollection:
        inbox = (
            self._db.query(NoteCollection)
            .filter(NoteCollection.space_id == space_id, NoteCollection.system_role == "inbox")
            .first()
        )
        if inbox is not None:
            return inbox

        from .seeder import seed_default_note_collections

        seed_default_note_collections(self._db, space_id)
        inbox = (
            self._db.query(NoteCollection)
            .filter(NoteCollection.space_id == space_id, NoteCollection.system_role == "inbox")
            .first()
        )
        if inbox is None:
            raise KnowledgeValidationError("Inbox collection is not initialized")
        return inbox

    def create_collection(self, *, space_id: str, data: dict[str, Any]) -> NoteCollection:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise KnowledgeValidationError("missing required 'name'")
        parent_id = data.get("parent_id")
        self._assert_optional_parent(space_id=space_id, parent_id=parent_id, collection_id=None)
        collection = NoteCollection(
            space_id=space_id,
            parent_id=parent_id,
            name=name.strip(),
            system_role="normal",
            sort_order=self._next_sort_order(space_id=space_id, parent_id=parent_id)
            if data.get("sort_order") is None
            else int(data["sort_order"]),
            is_system=False,
            is_hidden=False,
        )
        self._db.add(collection)
        self._db.flush()
        return collection

    def update_collection(self, *, space_id: str, collection_id: str, data: dict[str, Any]) -> NoteCollection:
        collection = self.get_collection(space_id=space_id, collection_id=collection_id)
        if collection is None:
            raise KnowledgeNotFound("Collection not found")

        protected = collection.system_role in self._SYSTEM_ROLES
        if data.get("name") is not None:
            name = str(data["name"]).strip()
            if not name:
                raise KnowledgeValidationError("name cannot be empty")
            collection.name = name

        if "parent_id" in data:
            if protected and data["parent_id"] != collection.parent_id:
                raise KnowledgeValidationError("system collections cannot be moved")
            self._assert_optional_parent(space_id=space_id, parent_id=data["parent_id"], collection_id=collection.id)
            collection.parent_id = data["parent_id"]

        if data.get("sort_order") is not None:
            collection.sort_order = int(data["sort_order"])

        if data.get("is_hidden") is not None:
            is_hidden = bool(data["is_hidden"])
            if protected and is_hidden != collection.is_hidden:
                raise KnowledgeValidationError("system collections cannot be hidden")
            collection.is_hidden = is_hidden

        collection.updated_at = datetime.now(UTC)
        self._db.flush()
        return collection

    def delete_collection(self, *, space_id: str, collection_id: str) -> None:
        collection = self.get_collection(space_id=space_id, collection_id=collection_id)
        if collection is None:
            raise KnowledgeNotFound("Collection not found")
        if collection.system_role in self._SYSTEM_ROLES or collection.is_system:
            raise KnowledgeValidationError("system collections cannot be deleted")
        child_count = (
            self._db.query(NoteCollection.id)
            .filter(NoteCollection.space_id == space_id, NoteCollection.parent_id == collection.id)
            .count()
        )
        item_count = (
            self._db.query(NoteCollectionItem.id)
            .filter(NoteCollectionItem.collection_id == collection.id)
            .count()
        )
        if child_count or item_count:
            raise KnowledgeConflict("collection is not empty")
        self._db.delete(collection)
        self._db.flush()

    def _next_sort_order(self, *, space_id: str, parent_id: str | None) -> int:
        rows = (
            self._db.query(NoteCollection.sort_order)
            .filter(NoteCollection.space_id == space_id, NoteCollection.parent_id == parent_id)
            .all()
        )
        if not rows:
            return 0
        return max(row[0] for row in rows) + 100

    def _assert_optional_parent(
        self,
        *,
        space_id: str,
        parent_id: str | None,
        collection_id: str | None,
    ) -> None:
        if parent_id is None:
            return
        if parent_id == collection_id:
            raise KnowledgeValidationError("collection cannot be its own parent")
        parent = self.get_collection(space_id=space_id, collection_id=parent_id)
        if parent is None:
            raise KnowledgeValidationError("parent_id does not belong to this space")
        seen: set[str] = set()
        current = parent
        while current.parent_id is not None:
            if current.id in seen:
                raise KnowledgeValidationError("collection tree contains a cycle")
            seen.add(current.id)
            if current.parent_id == collection_id:
                raise KnowledgeValidationError("collection cannot be moved under its descendant")
            next_parent = self.get_collection(space_id=space_id, collection_id=current.parent_id)
            if next_parent is None:
                return
            current = next_parent


class NoteService:
    """Direct (non-proposal) CRUD for working-knowledge Notes.

    Notes are working material that evolves freely, so unlike KnowledgeItem they
    are not governed by the proposal -> approval workflow. They are space-scoped;
    per-user visibility narrowing can be layered on later without changing callers.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_notes(
        self,
        *,
        space_id: str,
        status: str | None = None,
        project_id: str | None = None,
        collection_id: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Note]]:
        query = self._db.query(Note).filter(Note.space_id == space_id)
        if status:
            if status not in _VALID_NOTE_STATUS:
                raise KnowledgeValidationError(f"invalid note status: {status!r}")
            query = query.filter(Note.status == status)
        else:
            query = query.filter(Note.status != "deleted")
        if project_id:
            query = query.filter(Note.primary_project_id == project_id)
        if collection_id:
            if NoteCollectionService(self._db).get_collection(space_id=space_id, collection_id=collection_id) is None:
                raise KnowledgeNotFound("Collection not found")
            query = query.join(NoteCollectionItem, NoteCollectionItem.note_id == Note.id).filter(
                NoteCollectionItem.collection_id == collection_id
            )
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Note.title.ilike(like), Note.plain_text.ilike(like)))
        total = query.count()
        rows = (
            query.order_by(Note.updated_at.desc(), Note.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, rows

    def get_note(self, *, space_id: str, note_id: str) -> Note | None:
        return self._db.query(Note).filter(Note.id == note_id, Note.space_id == space_id).first()

    def collection_ids_for_notes(self, *, note_ids: list[str]) -> dict[str, str]:
        """Map each note id to its collection id (first membership by sort order).

        Notes are created in exactly one collection, but the membership table
        permits more than one; we surface a single deterministic collection so
        the Notes tree can nest each note under its folder without an N+1 query
        per row.
        """
        if not note_ids:
            return {}
        rows = (
            self._db.query(NoteCollectionItem.note_id, NoteCollectionItem.collection_id)
            .filter(NoteCollectionItem.note_id.in_(note_ids))
            .order_by(
                NoteCollectionItem.note_id,
                NoteCollectionItem.sort_order,
                NoteCollectionItem.created_at,
            )
            .all()
        )
        mapping: dict[str, str] = {}
        for note_id, collection_id in rows:
            mapping.setdefault(note_id, collection_id)
        return mapping

    def create_note(self, *, space_id: str, user_id: str | None, data: dict[str, Any]) -> Note:
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise KnowledgeValidationError("missing required 'title'")
        content_format = data.get("content_format") or "markdown"
        if content_format not in _VALID_NOTE_CONTENT_FORMATS:
            raise KnowledgeValidationError(f"invalid content_format: {content_format!r}")
        status = data.get("status") or "active"
        if status not in _VALID_NOTE_STATUS:
            raise KnowledgeValidationError(f"invalid note status: {status!r}")
        if status != "active":
            raise KnowledgeValidationError("notes can only be created with status 'active'")
        project_id = data.get("primary_project_id")
        self._assert_optional_project(space_id=space_id, project_id=project_id)
        activity_id = data.get("created_from_activity_id")
        self._assert_optional_activity(space_id=space_id, activity_id=activity_id)
        content_json = data.get("content_json")
        plain_text, excerpt = derive_note_projection(
            content_json=content_json,
            plain_text=data.get("plain_text"),
            excerpt=data.get("excerpt"),
        )
        collection_id = data.get("collection_id")
        if collection_id is None:
            collection = NoteCollectionService(self._db).get_inbox_collection(space_id=space_id)
            collection_id = collection.id
        else:
            collection = NoteCollectionService(self._db).get_collection(space_id=space_id, collection_id=collection_id)
            if collection is None:
                raise KnowledgeValidationError("collection_id does not belong to this space")
        note = Note(
            space_id=space_id,
            title=title,
            content_json=content_json,
            content_format=content_format,
            content_schema_version=data.get("content_schema_version") or 1,
            plain_text=plain_text,
            excerpt=excerpt,
            status=status,
            primary_project_id=project_id,
            created_from_activity_id=activity_id,
            created_by_user_id=user_id,
        )
        self._db.add(note)
        self._db.flush()
        self._db.add(
            NoteCollectionItem(
                collection_id=collection_id,
                note_id=note.id,
                sort_order=self._next_collection_item_sort_order(collection_id=collection_id),
            )
        )
        self._db.flush()
        return note

    def update_note(self, *, space_id: str, note_id: str, data: dict[str, Any]) -> Note:
        note = self.get_note(space_id=space_id, note_id=note_id)
        if note is None:
            raise KnowledgeNotFound("Note not found")
        if data.get("title") is not None:
            if not str(data["title"]).strip():
                raise KnowledgeValidationError("title cannot be empty")
            note.title = data["title"]
        if data.get("content_format") is not None:
            if data["content_format"] not in _VALID_NOTE_CONTENT_FORMATS:
                raise KnowledgeValidationError(f"invalid content_format: {data['content_format']!r}")
            note.content_format = data["content_format"]
        if data.get("status") is not None:
            if data["status"] not in _VALID_NOTE_STATUS:
                raise KnowledgeValidationError(f"invalid note status: {data['status']!r}")
            note.status = data["status"]
            now = datetime.now(UTC)
            note.archived_at = now if data["status"] == "archived" else None
            note.deleted_at = now if data["status"] == "deleted" else None
        if "primary_project_id" in data:
            self._assert_optional_project(space_id=space_id, project_id=data["primary_project_id"])
            note.primary_project_id = data["primary_project_id"]
        if "content_json" in data:
            note.content_json = data["content_json"]
        if data.get("content_schema_version") is not None:
            note.content_schema_version = data["content_schema_version"]
        if "content_json" in data and data["content_json"] is not None:
            note.plain_text, note.excerpt = derive_note_projection(
                content_json=data["content_json"],
                plain_text=data.get("plain_text"),
                excerpt=data.get("excerpt"),
            )
        elif "plain_text" in data:
            note.plain_text = data["plain_text"]
            if "excerpt" not in data:
                note.excerpt = derive_note_excerpt(data["plain_text"])
        if "excerpt" in data:
            note.excerpt = data["excerpt"]
        note.updated_at = datetime.now(UTC)
        self._db.flush()
        return note

    def delete_note(self, *, space_id: str, note_id: str) -> Note:
        note = self.get_note(space_id=space_id, note_id=note_id)
        if note is None:
            raise KnowledgeNotFound("Note not found")
        note.status = "deleted"
        note.archived_at = None
        note.deleted_at = datetime.now(UTC)
        note.updated_at = note.deleted_at
        self._db.flush()
        return note

    def purge_deleted_notes(
        self,
        *,
        space_id: str,
        retention_days: int = NOTE_DELETED_RETENTION_DAYS,
        now: datetime | None = None,
    ) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        rows = (
            self._db.query(Note.id)
            .filter(
                Note.space_id == space_id,
                Note.status == "deleted",
                Note.deleted_at.is_not(None),
                Note.deleted_at <= cutoff,
            )
            .all()
        )
        note_ids = [row[0] for row in rows]
        if not note_ids:
            return 0

        self._db.query(EntityLink).filter(
            EntityLink.space_id == space_id,
            or_(
                and_(EntityLink.source_type == "note", EntityLink.source_id.in_(note_ids)),
                and_(EntityLink.target_type == "note", EntityLink.target_id.in_(note_ids)),
            ),
        ).delete(synchronize_session=False)
        self._db.query(NoteCollectionItem).filter(NoteCollectionItem.note_id.in_(note_ids)).delete(
            synchronize_session=False
        )
        deleted_count = self._db.query(Note).filter(Note.id.in_(note_ids), Note.space_id == space_id).delete(
            synchronize_session=False
        )
        self._db.flush()
        return int(deleted_count)

    def _assert_optional_project(self, *, space_id: str, project_id: str | None) -> None:
        if project_id is None:
            return
        exists = self._db.query(Project.id).filter(Project.id == project_id, Project.space_id == space_id).first()
        if not exists:
            raise KnowledgeValidationError("primary_project_id does not belong to this space")

    def _assert_optional_activity(self, *, space_id: str, activity_id: str | None) -> None:
        if activity_id is None:
            return
        exists = (
            self._db.query(ActivityRecord.id)
            .filter(ActivityRecord.id == activity_id, ActivityRecord.space_id == space_id)
            .first()
        )
        if not exists:
            raise KnowledgeValidationError("created_from_activity_id does not belong to this space")

    def _next_collection_item_sort_order(self, *, collection_id: str) -> int:
        rows = (
            self._db.query(NoteCollectionItem.sort_order)
            .filter(NoteCollectionItem.collection_id == collection_id)
            .all()
        )
        if not rows:
            return 0
        return max(row[0] for row in rows) + 100


# ---------------------------------------------------------------------------
# Entity links (generic cross-object relation layer; direct CRUD)
# ---------------------------------------------------------------------------

_ENTITY_MODELS: dict[str, Any] = {
    "note": Note,
    "knowledge_item": KnowledgeItem,
    "source": Source,
    "project": Project,
    "workspace": Workspace,
    "activity": ActivityRecord,
    "run": Run,
    "proposal": Proposal,
}
_VALID_ENTITY_TYPES: frozenset[str] = frozenset(_ENTITY_MODELS)
_VALID_LINK_TYPES: frozenset[str] = frozenset(
    {"references", "related_to", "belongs_to", "captured_from", "source_for", "derived_from"}
)
_VALID_LINK_STATUS: frozenset[str] = frozenset({"suggested", "accepted", "rejected"})


class EntityLinkService:
    """Direct CRUD for the generic EntityLink cross-object relation layer.

    Endpoints are validated to exist within the same space; ``source_id`` /
    ``target_id`` are polymorphic and resolved through ``_ENTITY_MODELS``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_link(self, *, space_id: str, user_id: str | None, data: dict[str, Any]) -> EntityLink:
        source_type = data.get("source_type")
        target_type = data.get("target_type")
        if source_type not in _VALID_ENTITY_TYPES:
            raise KnowledgeValidationError(f"invalid source_type: {source_type!r}")
        if target_type not in _VALID_ENTITY_TYPES:
            raise KnowledgeValidationError(f"invalid target_type: {target_type!r}")
        link_type = data.get("link_type") or "related_to"
        if link_type not in _VALID_LINK_TYPES:
            raise KnowledgeValidationError(f"invalid link_type: {link_type!r}")
        status = data.get("status") or "accepted"
        if status not in _VALID_LINK_STATUS:
            raise KnowledgeValidationError(f"invalid link status: {status!r}")
        confidence = data.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            raise KnowledgeValidationError("confidence must be between 0 and 1")
        source_id = data.get("source_id")
        target_id = data.get("target_id")
        if not source_id or not target_id:
            raise KnowledgeValidationError("source_id and target_id are required")
        if source_type == target_type and source_id == target_id:
            raise KnowledgeValidationError("cannot link an entity to itself")
        self._assert_entity_exists(space_id=space_id, entity_type=source_type, entity_id=source_id)
        self._assert_entity_exists(space_id=space_id, entity_type=target_type, entity_id=target_id)
        if status == "accepted":
            existing = (
                self._db.query(EntityLink)
                .filter(
                    EntityLink.space_id == space_id,
                    EntityLink.source_type == source_type,
                    EntityLink.source_id == source_id,
                    EntityLink.target_type == target_type,
                    EntityLink.target_id == target_id,
                    EntityLink.link_type == link_type,
                    EntityLink.status == "accepted",
                )
                .first()
            )
            if existing is not None:
                raise KnowledgeValidationError("link already exists")
        link = EntityLink(
            space_id=space_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            link_type=link_type,
            confidence=confidence,
            status=status,
            created_by_user_id=user_id,
        )
        self._db.add(link)
        self._db.flush()
        return link

    def list_links(
        self, *, space_id: str, entity_type: str, entity_id: str, direction: str = "all"
    ) -> list[EntityLink]:
        query = self._db.query(EntityLink).filter(EntityLink.space_id == space_id)
        as_source = and_(EntityLink.source_type == entity_type, EntityLink.source_id == entity_id)
        as_target = and_(EntityLink.target_type == entity_type, EntityLink.target_id == entity_id)
        if direction == "outgoing":
            query = query.filter(as_source)
        elif direction == "backlinks":
            query = query.filter(as_target)
        else:
            query = query.filter(or_(as_source, as_target))
        return query.order_by(EntityLink.created_at.desc()).all()

    def query_links(
        self,
        *,
        space_id: str,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[EntityLink]:
        """Generic read of entity links filtered by any combination of endpoints.

        At least one of the source_* / target_* filters should be supplied by the
        caller; with none, returns all links in the space (newest first).
        """
        for field, value in (("source_type", source_type), ("target_type", target_type)):
            if value is not None and value not in _VALID_ENTITY_TYPES:
                raise KnowledgeValidationError(f"invalid {field}: {value!r}")
        query = self._db.query(EntityLink).filter(EntityLink.space_id == space_id)
        if source_type is not None:
            query = query.filter(EntityLink.source_type == source_type)
        if source_id is not None:
            query = query.filter(EntityLink.source_id == source_id)
        if target_type is not None:
            query = query.filter(EntityLink.target_type == target_type)
        if target_id is not None:
            query = query.filter(EntityLink.target_id == target_id)
        return query.order_by(EntityLink.created_at.desc()).all()

    def get_link(self, *, space_id: str, link_id: str) -> EntityLink | None:
        return (
            self._db.query(EntityLink)
            .filter(EntityLink.id == link_id, EntityLink.space_id == space_id)
            .first()
        )

    def delete_link(self, *, space_id: str, link_id: str) -> None:
        link = self.get_link(space_id=space_id, link_id=link_id)
        if link is None:
            raise KnowledgeNotFound("Link not found")
        self._db.delete(link)
        self._db.flush()

    def _assert_entity_exists(self, *, space_id: str, entity_type: str, entity_id: str) -> None:
        model = _ENTITY_MODELS.get(entity_type)
        if model is None:
            raise KnowledgeValidationError(f"invalid entity type: {entity_type!r}")
        exists = (
            self._db.query(model.id)
            .filter(model.id == entity_id, model.space_id == space_id)
            .first()
        )
        if not exists:
            raise KnowledgeNotFound(f"{entity_type} not found in this space")


# ---------------------------------------------------------------------------
# Knowledge overview summary
# ---------------------------------------------------------------------------


class KnowledgeSummaryService:
    """Aggregate counts backing the Knowledge module Overview page."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def summary(self, *, space_id: str, viewer_user_id: str) -> dict[str, Any]:
        note_counts = {
            status: self._db.query(Note)
            .filter(Note.space_id == space_id, Note.status == status)
            .count()
            for status in ("active", "archived", "deleted")
        }
        wiki_active = (
            self._db.query(KnowledgeItem)
            .filter(KnowledgeItem.space_id == space_id, KnowledgeItem.status == "active")
            .filter(KnowledgeService._readable_item_filter(viewer_user_id=viewer_user_id))
            .count()
        )
        sources_total = (
            self._db.query(Source)
            .filter(Source.space_id == space_id, Source.status != "archived")
            .count()
        )
        return {
            "notes": {
                "active": note_counts["active"],
                "archived": note_counts["archived"],
                "deleted": note_counts["deleted"],
                "total": note_counts["active"] + note_counts["archived"],
            },
            "wiki": {"active": wiki_active},
            "sources": {"total": sources_total},
        }
