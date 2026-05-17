"""Read-only artifact queries and safe path resolution for export."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Artifact
from ..schemas import ArtifactOut
from ..visibility.auth import can_read_scoped_object


def artifact_to_out(row: Artifact, *, include_content: bool = False) -> ArtifactOut:
    return ArtifactOut(
        id=row.id,
        space_id=row.space_id,
        run_id=row.run_id,
        proposal_id=row.proposal_id,
        artifact_type=row.artifact_type,
        title=row.title,
        mime_type=row.mime_type,
        exportable=row.exportable,
        preview=row.preview,
        storage_ref=row.storage_ref,
        storage_path=row.storage_path,
        metadata_json=dict(row.metadata_json) if row.metadata_json else None,
        has_inline_content=bool(row.content),
        visibility=row.visibility,
        owner_user_id=row.owner_user_id,
        content=(row.content if include_content else None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ArtifactReadService:
    def __init__(self, db: Session):
        self.db = db

    def list_artifacts(
        self,
        space_id: str,
        *,
        user_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Artifact]]:
        q = self.db.query(Artifact).filter(Artifact.space_id == space_id)
        if artifact_type:
            q = q.filter(Artifact.artifact_type == artifact_type)
        rows = q.order_by(Artifact.created_at.desc()).all()
        if user_id is not None:
            rows = [
                a for a in rows
                if can_read_scoped_object(
                    visibility=a.visibility,
                    owner_user_id=a.owner_user_id,
                    current_user_id=user_id,
                    is_space_member=True,
                )
            ]
        total = len(rows)
        return total, rows[offset : offset + limit]

    def get(self, artifact_id: str, space_id: str, *, user_id: str | None = None) -> Artifact | None:
        row = (
            self.db.query(Artifact)
            .filter(Artifact.id == artifact_id, Artifact.space_id == space_id)
            .first()
        )
        if row is None:
            return None
        if user_id is not None and not can_read_scoped_object(
            visibility=row.visibility,
            owner_user_id=row.owner_user_id,
            current_user_id=user_id,
            is_space_member=True,
        ):
            return None
        return row

    def resolve_stored_file(self, artifact: Artifact) -> Path | None:
        """
        Resolve ``storage_path`` under configured artifact storage root.

        Returns None if the path escapes the root, resolves inside the sandbox
        root, or is not an existing regular file.
        """
        if not artifact.storage_path:
            return None
        root = Path(settings.artifact_storage_root).resolve()
        sandbox_root = Path(settings.sandbox_root).resolve()
        candidate = (root / artifact.storage_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        try:
            candidate.relative_to(sandbox_root)
            return None
        except ValueError:
            pass
        if not candidate.is_file():
            return None
        return candidate
