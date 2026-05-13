"""Persist runtime outputs into canonical artifact storage."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session
from ulid import ULID

from ..config import settings
from ..models import Artifact, Run


def _new_id() -> str:
    return str(ULID())


def _ensure_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact path escapes artifact_storage_root") from exc


class ArtifactPersistenceService:
    """Copy or write adapter outputs under ``artifact_storage_root``."""

    def __init__(self, db: Session):
        self.db = db

    def persist_text_file(
        self,
        *,
        run: Run,
        text: str,
        title: str,
        artifact_type: str = "runtime_output",
        preview: bool = False,
    ) -> Artifact:
        """Write UTF-8 text to persisted storage and create an ``Artifact`` row."""
        art_id = _new_id()
        rel = f"{run.space_id}/runs/{run.id}/{art_id}.txt"
        root = Path(settings.artifact_storage_root).resolve()
        dest = (root / rel).resolve()
        _ensure_under_root(dest, root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

        artifact = Artifact(
            id=art_id,
            space_id=run.space_id,
            run_id=run.id,
            artifact_type=artifact_type,
            title=title,
            content=None,
            mime_type="text/plain",
            exportable=True,
            preview=preview,
            storage_path=rel.replace("\\", "/"),
            storage_ref=None,
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact
