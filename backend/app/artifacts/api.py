"""Artifact list and export (read-only)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..auth import get_identity
from ..db import get_db
from ..schemas import ArtifactOut, Page
from .service import ArtifactReadService, artifact_to_out

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _export_filename(artifact) -> str:
    raw = (artifact.title or "artifact").strip() or "artifact"
    safe = re.sub(r"[^\w.\-]+", "_", raw, flags=re.ASCII)[:200]
    return safe or "artifact"


@router.get("", response_model=Page[ArtifactOut])
def list_artifacts(
    artifact_type: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    svc = ArtifactReadService(db)
    try:
        total, rows = svc.list_artifacts(
            space_id, user_id=user_id, artifact_type=artifact_type,
            project_id=project_id, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Page(
        items=[artifact_to_out(a) for a in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{artifact_id}", response_model=ArtifactOut)
def get_artifact(
    artifact_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Single artifact in the current space (JSON; distinct from ``…/export``)."""
    space_id, user_id = ids
    svc = ArtifactReadService(db)
    art = svc.get(artifact_id, space_id, user_id=user_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact_to_out(art, include_content=True)


@router.get("/{artifact_id}/export")
def export_artifact(
    artifact_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Download inline ``content`` or stream from instance artifact storage.

    Does not mutate the Artifact row. Space-scoped.
    """
    space_id, user_id = ids
    svc = ArtifactReadService(db)
    art = svc.get(artifact_id, space_id, user_id=user_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    filename = _export_filename(art)
    disposition = f'attachment; filename="{filename}"'

    if art.content:
        body = art.content
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        media = art.mime_type or "application/octet-stream"
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": disposition},
        )

    path = svc.resolve_stored_file(art)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact has no inline content and no valid storage file",
        )
    return FileResponse(
        path=str(path),
        media_type=art.mime_type or "application/octet-stream",
        filename=filename,
    )
