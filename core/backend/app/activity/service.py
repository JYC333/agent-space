from __future__ import annotations
import uuid
"""
ActivityService — manages ActivityRecord lifecycle and proposal generation.

ActivityRecords are the entry point for all incoming data. They may produce
memory proposals, but they must never become active memory directly.

``activity_type`` (API field ``source_type``) uses the same canonical vocabulary
as ``ActivityRecord.source_kind``:
  user_capture | chat_message | external_chat | file_import | web_capture |
  run_event | workspace_event | system_event | external_source | intake

Consolidation runs via ``ActivityConsolidationService`` from
``POST /api/v1/activity/{id}/consolidate`` and ``POST /api/v1/memory/consolidation/run`` — not from ``ActivityService``.
"""

from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models import ActivityRecord, Run
from ..param_binding import duplicate_mapper
from ..visibility.auth import can_read_scoped_object
from ..projects.service import assert_project_in_space


def _new_id() -> str:
    return str(uuid.uuid4())


SOURCE_TYPE_ALIASES: dict[str, str] = {
    "user_input": "user_capture",
    "manual": "user_capture",
    "imported_chat": "external_chat",
    "agent_run": "run_event",
    "task_log": "workspace_event",
    # File and voice captures are stored as canonical ``file_import`` records; the
    # specific capture kind is preserved in metadata (``capture_kind``). This avoids
    # a new source-type vocabulary / DB check-constraint change.
    "file_capture": "file_import",
    "voice_capture": "file_import",
}

CANONICAL_SOURCE_TYPES = frozenset({
    "user_capture",
    "chat_message",
    "external_chat",
    "file_import",
    "web_capture",
    "run_event",
    "workspace_event",
    "system_event",
    "external_source",
    "intake",
})


def normalize_source_type(source_type: str) -> str:
    value = source_type.lower().strip()
    value = SOURCE_TYPE_ALIASES.get(value, value)
    if value not in CANONICAL_SOURCE_TYPES:
        raise ValueError(f"invalid source_type: {source_type!r}")
    return value


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
        owner_user_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ActivityRecord:
        now = datetime.now(UTC)
        record = ActivityRecord(
            id=_new_id(),
            space_id=space_id,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            activity_type=normalize_source_type(source_type),
            source_kind=normalize_source_type(source_type),
            title=title,
            content=content,
            source_run_id=source_run_id,
            source_task_id=source_task_id,
            session_id=source_session_id,
            source_url=source_url,
            status="raw",
            payload_json=metadata_json,
            occurred_at=occurred_at if occurred_at is not None else now,
            updated_at=now,
            owner_user_id=owner_user_id if owner_user_id is not None else user_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(
        self,
        activity_id: str,
        space_id: str,
        *,
        viewer_user_id: str | None = None,
    ) -> Optional[ActivityRecord]:
        row = (
            self.db.query(ActivityRecord)
            .filter(
                ActivityRecord.id == activity_id,
                ActivityRecord.space_id == space_id,
            )
            .first()
        )
        if row is None:
            return None
        if viewer_user_id is not None and not can_read_scoped_object(
            visibility=row.visibility,
            owner_user_id=row.owner_user_id,
            current_user_id=viewer_user_id,
            is_space_member=True,
        ):
            return None
        return row

    def list(
        self,
        space_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        viewer_user_id: str | None = None,
    ) -> list[ActivityRecord]:
        if project_id:
            assert_project_in_space(self.db, project_id, space_id)
        q = self.db.query(ActivityRecord).filter(ActivityRecord.space_id == space_id)
        if project_id:
            q = q.filter(ActivityRecord.project_id == project_id)
        if user_id:
            run_for_instructor = duplicate_mapper(Run)
            visible = or_(
                ActivityRecord.user_id == user_id,
                run_for_instructor.instructed_by_user_id == user_id,
            )
            q = (
                q.outerjoin(
                    run_for_instructor,
                    and_(
                        run_for_instructor.id == ActivityRecord.source_run_id,
                        run_for_instructor.space_id == space_id,
                    ),
                ).filter(visible)
            )
        if workspace_id:
            q = q.filter(ActivityRecord.workspace_id == workspace_id)
        if source_type:
            q = q.filter(ActivityRecord.activity_type == normalize_source_type(source_type))
        if status:
            q = q.filter(ActivityRecord.status == status)
        rows = q.order_by(ActivityRecord.created_at.desc()).all()
        if viewer_user_id is not None:
            rows = [
                r for r in rows
                if can_read_scoped_object(
                    visibility=r.visibility,
                    owner_user_id=r.owner_user_id,
                    current_user_id=viewer_user_id,
                    is_space_member=True,
                )
            ]
        return rows[offset : offset + limit]

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_reviewed(
        self, activity_id: str, space_id: str, *, viewer_user_id: str | None = None
    ) -> ActivityRecord:
        """Mark as reviewed (status-only transition; does not generate proposals).

        Sets consolidation_status="skipped" so run_pending consolidation ignores this record.
        """
        record = self._require(activity_id, space_id, viewer_user_id=viewer_user_id)
        now = datetime.now(UTC)
        record.status = "processed"
        # skipped: consolidation was bypassed by explicit user review
        record.consolidation_status = "skipped"
        record.processed_at = now
        record.updated_at = now
        self.db.commit()
        self.db.refresh(record)
        return record

    def mark_archived(
        self, activity_id: str, space_id: str, *, viewer_user_id: str | None = None
    ) -> ActivityRecord:
        record = self._require(activity_id, space_id, viewer_user_id=viewer_user_id)
        record.status = "archived"
        record.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require(
        self, activity_id: str, space_id: str, *, viewer_user_id: str | None = None
    ) -> ActivityRecord:
        record = self.get(activity_id, space_id, viewer_user_id=viewer_user_id)
        if not record:
            raise ValueError(f"ActivityRecord {activity_id!r} not found in space {space_id!r}")
        return record
