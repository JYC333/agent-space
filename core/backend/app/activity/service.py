from __future__ import annotations
"""
ActivityService — manages ActivityRecord lifecycle and proposal generation.

ActivityRecords are the entry point for all incoming data. They may produce
memory proposals, but they must never become active memory directly.

source_type values:
  user_input | imported_chat | web_capture | file_import |
  agent_run  | task_log      | manual
"""

from datetime import datetime, UTC
from typing import Optional

from ulid import ULID
from sqlalchemy.orm import Session

from ..models import ActivityRecord, MemoryProposal


def _new_id() -> str:
    return str(ULID())


class ActivityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        space_id: str,
        source_type: str,
        content: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        title: str | None = None,
        source_run_id: str | None = None,
        source_task_id: str | None = None,
        source_session_id: str | None = None,
        source_url: str | None = None,
        metadata_json: dict | None = None,
    ) -> ActivityRecord:
        record = ActivityRecord(
            id=_new_id(),
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            source_type=source_type,
            title=title,
            content=content,
            source_run_id=source_run_id,
            source_task_id=source_task_id,
            source_session_id=source_session_id,
            source_url=source_url,
            status="raw",
            metadata_json=metadata_json,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, activity_id: str, space_id: str) -> Optional[ActivityRecord]:
        return (
            self.db.query(ActivityRecord)
            .filter(
                ActivityRecord.id == activity_id,
                ActivityRecord.space_id == space_id,
            )
            .first()
        )

    def list(
        self,
        space_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActivityRecord]:
        q = self.db.query(ActivityRecord).filter(ActivityRecord.space_id == space_id)
        if user_id:
            q = q.filter(ActivityRecord.user_id == user_id)
        if workspace_id:
            q = q.filter(ActivityRecord.workspace_id == workspace_id)
        if source_type:
            q = q.filter(ActivityRecord.source_type == source_type)
        if status:
            q = q.filter(ActivityRecord.status == status)
        return (
            q.order_by(ActivityRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_processed(self, activity_id: str, space_id: str) -> ActivityRecord:
        record = self._require(activity_id, space_id)
        record.status = "processed"
        record.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(record)
        return record

    def mark_archived(self, activity_id: str, space_id: str) -> ActivityRecord:
        record = self._require(activity_id, space_id)
        record.status = "archived"
        record.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Proposal generation
    # ------------------------------------------------------------------

    def create_proposals_from(
        self,
        activity_id: str,
        space_id: str,
        proposals: list[dict],
        user_id: str,
    ) -> list[MemoryProposal]:
        """
        Create memory proposals sourced from an activity record.
        Marks the record as proposals_generated on success.

        Each item in `proposals` must have:
          target_scope, target_namespace, memory_type,
          proposed_title, proposed_content, rationale

        Optional per-item fields:
          source_evidence, risk_level, target_visibility
        """
        record = self._require(activity_id, space_id)
        created: list[MemoryProposal] = []

        for p in proposals:
            proposal = MemoryProposal(
                id=_new_id(),
                space_id=space_id,
                user_id=user_id,
                workspace_id=record.workspace_id,
                source_activity_id=activity_id,
                source_run_id=record.source_run_id,
                source_task_id=record.source_task_id,
                source_session_id=record.source_session_id,
                target_scope=p["target_scope"],
                target_namespace=p["target_namespace"],
                target_visibility=p.get("target_visibility", "private"),
                memory_type=p["memory_type"],
                proposed_title=p["proposed_title"],
                proposed_content=p["proposed_content"],
                rationale=p["rationale"],
                source_evidence=p.get("source_evidence"),
                risk_level=p.get("risk_level", "low"),
                status="pending",
            )
            self.db.add(proposal)
            created.append(proposal)

        record.status = "proposals_generated"
        record.updated_at = datetime.now(UTC)
        self.db.commit()
        for p in created:
            self.db.refresh(p)
        return created

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require(self, activity_id: str, space_id: str) -> ActivityRecord:
        record = self.get(activity_id, space_id)
        if not record:
            raise ValueError(f"ActivityRecord {activity_id!r} not found in space {space_id!r}")
        return record
