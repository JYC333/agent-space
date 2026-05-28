from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, and_, or_
from sqlalchemy.orm import Session

from ..memory.proposals import ProposalService
from ..models import ActivityRecord, Artifact, KnowledgeItem, KnowledgeRelation, Project, Proposal, Run, Workspace


class KnowledgeError(Exception):
    pass


class KnowledgeNotFound(KnowledgeError):
    pass


class KnowledgeValidationError(KnowledgeError):
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
            # Portable enough for SQLite JSON text storage in this codebase; exact
            # JSON membership can be tightened when a DB-specific dialect is chosen.
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

    def get_relation(self, *, space_id: str, relation_id: str) -> KnowledgeRelation | None:
        return (
            self._db.query(KnowledgeRelation)
            .filter(KnowledgeRelation.id == relation_id, KnowledgeRelation.space_id == space_id)
            .first()
        )

    def list_item_relations(self, *, space_id: str, viewer_user_id: str, item_id: str) -> list[KnowledgeRelation]:
        if self.get_readable_item(space_id=space_id, viewer_user_id=viewer_user_id, item_id=item_id) is None:
            raise KnowledgeNotFound("Knowledge item not found")
        relations = (
            self._db.query(KnowledgeRelation)
            .filter(
                KnowledgeRelation.space_id == space_id,
                or_(KnowledgeRelation.from_item_id == item_id, KnowledgeRelation.to_item_id == item_id),
            )
            .order_by(KnowledgeRelation.created_at.desc())
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
            "content": data["content"],
            "content_format": data["content_format"],
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
            "content": data["content"],
            "content_format": data["content_format"],
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


class KnowledgeProposalApplier:
    def __init__(self, db: Session) -> None:
        self._db = db

    def apply_create(self, proposal: Proposal, *, user_id: str) -> KnowledgeItem:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "create")
        visibility = payload.get("visibility") or "space_shared"
        requested_owner_user_id = payload.get("owner_user_id")
        if requested_owner_user_id is not None and requested_owner_user_id != proposal.created_by_user_id:
            raise KnowledgeValidationError("Knowledge owner must be the proposal creator")
        if visibility in {"private", "restricted"} and proposal.created_by_user_id is None:
            raise KnowledgeValidationError("private or restricted Knowledge requires a human owner")
        item = KnowledgeItem(
            space_id=proposal.space_id,
            project_id=payload.get("project_id"),
            workspace_id=payload.get("workspace_id"),
            item_type=self._required_str(payload, "item_type"),
            title=self._required_str(payload, "title"),
            content=self._required_str(payload, "content"),
            content_format=payload.get("content_format") or "markdown",
            status="active",
            visibility=visibility,
            verification_status=payload.get("verification_status") or "unverified",
            reflection_status=payload.get("reflection_status") or "unreviewed",
            tags_json=list(payload.get("tags") or []),
            confidence=payload.get("confidence"),
            source_url=payload.get("source_url"),
            source_refs_json=list(payload.get("source_refs") or []),
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
        return item

    def apply_update(self, proposal: Proposal, *, user_id: str) -> KnowledgeItem:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "update")
        target = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "target_item_id"))
        if not can_apply_knowledge_mutation(target, proposal):
            raise KnowledgeValidationError("Knowledge item not found or not editable")
        if target.status not in {"active", "draft"}:
            raise KnowledgeValidationError("target Knowledge item is not active")
        now = datetime.now(UTC)
        root_id = target.root_item_id or target.id
        target.root_item_id = root_id
        target.status = "superseded"
        target.updated_at = now
        item = KnowledgeItem(
            space_id=proposal.space_id,
            project_id=target.project_id,
            workspace_id=target.workspace_id,
            root_item_id=root_id,
            supersedes_item_id=target.id,
            item_type=target.item_type,
            title=self._required_str(payload, "title"),
            content=self._required_str(payload, "content"),
            content_format=payload.get("content_format") or target.content_format,
            status="active",
            visibility=target.visibility,
            verification_status=payload.get("verification_status") or target.verification_status,
            reflection_status=payload.get("reflection_status") or target.reflection_status,
            tags_json=list(payload.get("tags") or []),
            confidence=payload.get("confidence"),
            source_url=target.source_url,
            source_refs_json=list(payload.get("source_refs") or []),
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
        return item

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

    def apply_relation_create(self, proposal: Proposal, *, user_id: str) -> KnowledgeRelation:
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "relation_create")
        from_item = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "from_item_id"))
        to_item = self._get_item_or_raise(proposal.space_id, self._required_str(payload, "to_item_id"))
        if from_item.space_id != to_item.space_id or from_item.space_id != proposal.space_id:
            raise KnowledgeValidationError("Knowledge relation endpoints must be in the same space")
        if not can_apply_knowledge_mutation(from_item, proposal) or not can_apply_knowledge_mutation(to_item, proposal):
            raise KnowledgeValidationError("Knowledge item not found")
        status = payload.get("status") or "active"
        relation_type = self._required_str(payload, "relation_type")
        if status == "active":
            existing = (
                self._db.query(KnowledgeRelation)
                .filter(
                    KnowledgeRelation.space_id == proposal.space_id,
                    KnowledgeRelation.from_item_id == from_item.id,
                    KnowledgeRelation.to_item_id == to_item.id,
                    KnowledgeRelation.relation_type == relation_type,
                    KnowledgeRelation.status == "active",
                )
                .first()
            )
            if existing is not None:
                raise KnowledgeValidationError("active Knowledge relation already exists")
        relation = KnowledgeRelation(
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

    def apply_relation_delete(self, proposal: Proposal, *, user_id: str) -> KnowledgeRelation:
        del user_id
        payload = proposal.payload_json or {}
        self._expect_operation(payload, "relation_delete")
        relation = (
            self._db.query(KnowledgeRelation)
            .filter(
                KnowledgeRelation.id == self._required_str(payload, "relation_id"),
                KnowledgeRelation.space_id == proposal.space_id,
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
