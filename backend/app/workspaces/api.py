import uuid
import logging
import re
from datetime import datetime, UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Workspace
from ..schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceOut, Page
from ..auth import get_identity


class ScanResult(BaseModel):
    created: list[WorkspaceOut]
    marked_stale: list[str]  # display names of workspaces whose path disappeared (marked stale, not deleted)

log = logging.getLogger(__name__)


def _folder_name(name: str) -> str:
    """Convert a workspace display name to a safe, lowercase directory name."""
    slug = re.sub(r'[^\w\s-]', '', name.lower().strip())
    slug = re.sub(r'[\s_-]+', '-', slug).strip('-')
    return slug or 'workspace'


def _unique_dir(workspace_root: Path, space_id: str, base: str) -> Path:
    """Return a path under workspace_root/<space_id>/ that does not already exist."""
    space_root = workspace_root / space_id
    candidate = space_root / base
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = space_root / f"{base}-{i}"
        if not candidate.exists():
            return candidate
        i += 1

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _new_id() -> str:
    return str(uuid.uuid4())


@router.get("", response_model=Page[WorkspaceOut])
def list_workspaces(
    status: str = Query("active"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    q = db.query(Workspace).filter(Workspace.space_id == space_id)
    if status:
        q = q.filter(Workspace.status == status)

    from sqlalchemy import func
    total = db.query(func.count(Workspace.id)).filter(
        Workspace.space_id == space_id,
        Workspace.status == status,
    ).scalar() or 0

    items = q.order_by(Workspace.updated_at.desc()).offset(offset).limit(limit).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    data: WorkspaceCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids

    # Reject system_core workspace creation — only registered via env on startup
    if data.workspace_type == "system_core":
        raise HTTPException(
            status_code=400,
            detail="system_core workspaces cannot be created through the UI; "
                   "set ENABLE_SYSTEM_EVOLUTION=true to register one",
        )

    # Reject duplicate names within the same space
    duplicate = db.query(Workspace).filter(
        Workspace.space_id == space_id,
        Workspace.name == data.name.strip(),
        Workspace.status == "active",
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail=f"A workspace named '{data.name.strip()}' already exists")

    ws_id = _new_id()

    # Resolve the on-disk path and create the directory.
    # If the caller supplied a path, treat it as an existing external directory.
    # Otherwise, create workspace_root/<sanitized-name>/ so the console file tree works immediately.
    if data.root_path:
        resolved_path = data.root_path
    else:
        workspace_root = Path(settings.workspace_root)
        ws_dir = _unique_dir(workspace_root, space_id, _folder_name(data.name.strip()))
        try:
            ws_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Could not create workspace dir %s: %s", ws_dir, exc)
        resolved_path = str(ws_dir)

    ws = Workspace(
        id=ws_id,
        space_id=space_id,
        created_by_user_id=user_id,
        name=data.name,
        description=data.description,
        workspace_type=data.workspace_type or "project",
        kind=data.kind,
        root_path=resolved_path,
        metadata_json=data.metadata_json,
        status="active",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@router.post("/scan", response_model=ScanResult, status_code=200)
def scan_workspaces(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Reconcile DB records with the workspace_root directory:
      - Directories on disk with no record → auto-register (created).
      - Records whose path no longer exists on disk → marked stale (NOT hard-deleted).

    Missing workspace paths are marked stale to preserve metadata (id, name, tasks,
    runs, artifacts, proposals, audit references). Workspace data is never deleted
    simply because a mount or directory is temporarily unavailable.
    Returns counts of both in a ScanResult.
    """
    space_id, user_id = ids
    workspace_root = Path(settings.workspace_root).resolve()
    space_workspace_root = workspace_root / space_id

    existing = db.query(Workspace).filter(
        Workspace.space_id == space_id,
        Workspace.status == "active",
    ).all()

    # ── Pass 1: mark stale when directory is gone; never hard-delete ─────────
    stale_names: list[str] = []
    known_paths: set[Path] = set()
    for ws in existing:
        if not ws.root_path:
            continue
        try:
            p = Path(ws.root_path).resolve()
        except OSError:
            continue
        if p.exists():
            known_paths.add(p)
        else:
            stale_names.append(ws.name)
            ws.status = "stale"
            ws.updated_at = datetime.now(UTC)
            log.info(
                "scan: marked workspace '%s' stale (path unavailable: %s); "
                "metadata preserved",
                ws.name, ws.root_path,
            )

    if stale_names:
        db.commit()

    # ── Pass 2: register directories not yet in DB ───────────────────────────
    if not space_workspace_root.exists():
        return ScanResult(created=[], marked_stale=stale_names)

    created: list[Workspace] = []
    for entry in sorted(space_workspace_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.resolve() in known_paths:
            continue
        # Re-query to guard against concurrent scan requests that committed
        # between when we built known_paths and now (e.g. React StrictMode
        # double-invoking the effect fires two requests nearly simultaneously).
        if db.query(Workspace).filter(
            Workspace.space_id == space_id,
            Workspace.root_path == str(entry),
            Workspace.status == "active",
        ).first():
            continue
        ws = Workspace(
            id=_new_id(),
            space_id=space_id,
            created_by_user_id=user_id,
            name=entry.name,
            kind="project",
            root_path=str(entry),
            status="active",
        )
        db.add(ws)
        created.append(ws)
        log.info("scan: auto-registered workspace '%s' at %s", entry.name, entry)

    if created:
        db.commit()
        for ws in created:
            db.refresh(ws)

    return ScanResult(created=created, marked_stale=stale_names)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    workspace_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    ws = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.space_id == space_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: str,
    data: WorkspaceUpdate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    ws = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.space_id == space_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(ws, field, value)
    ws.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=204)
def archive_workspace(
    workspace_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    ws = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.space_id == space_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.status = "archived"
    ws.updated_at = datetime.now(UTC)
    db.commit()
