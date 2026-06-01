"""
Workspace Console — file browser, git inspector, and runtime session manager.

Endpoints
---------
  GET  /workspace-console/workspaces                      workspaces with paths
  GET  /workspace-console/workspaces/{id}/tree            file tree (PathPolicy enforced)
  GET  /workspace-console/workspaces/{id}/file            file content (query: path=)
  GET  /workspace-console/workspaces/{id}/git/status      git status summary
  GET  /workspace-console/workspaces/{id}/git/diff        raw diff (query: path=)
  GET  /workspace-console/runtimes                        available runtime adapters
  GET  /workspace-console/sessions                        list console sessions
  POST /workspace-console/sessions                        create + run session
  GET  /workspace-console/sessions/{id}                   session detail + events
  POST /workspace-console/sessions/{id}/stop              stop a running session

Runtime execution
-----------------
  claude_code — async background task; runs `claude --print` in workspace dir
  codex_cli   — async background task; runs `codex` in workspace dir

  CLI runtimes (claude_code, codex_cli) return status="running" immediately and
  complete via BackgroundTask. Callers poll GET /sessions/{id} until the status
  changes to "completed" or "failed".

Policy: anthropic_api / anthropic_messages in-process Anthropic runtime types are not supported.
  Anthropic/Claude execution must go through the claude_code CLI integration.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.api_key import get_identity
from ..config import settings
from ..db import get_db
from ..feature_gates import feature_not_implemented
from ..models import Workspace
from ..policy.gateway import PolicyCheckRequest, PolicyGateway
from ..workspace.disk_path import workspace_absolute_root
from ..workspace.path_policy import PathPolicy, PathPolicyError

router = APIRouter(prefix="/workspace-console", tags=["workspace_console"])

_policy = PathPolicy()


# ── Path helpers ──────────────────────────────────────────────────────────────

def _ws_path(ws: Workspace) -> Path:
    """Resolve the on-disk root for a workspace record."""
    return workspace_absolute_root(ws)


def _get_ws(db: Session, workspace_id: str, space_id: str) -> Workspace:
    ws = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_space_id == space_id,
        Workspace.status == "active",
    ).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _enforce_workspace_read(
    db: Session,
    *,
    ws: Workspace,
    actor_user_id: str,
    read_kind: str,
    relative_path: str | None = None,
    force_record: bool | None = None,
    audit_reasons: list[str] | None = None,
) -> None:
    audit_reasons = audit_reasons or _workspace_read_audit_reasons(
        ws,
        read_kind=read_kind,
        relative_path=relative_path,
    )
    PolicyGateway(db).enforce(
        PolicyCheckRequest(
            action="workspace.read",
            actor_type="user",
            actor_id=actor_user_id,
            space_id=ws.space_id,
            resource_type="workspace",
            resource_id=ws.id,
            resource_space_id=ws.space_id,
            context={
                "read_kind": read_kind,
                "relative_path": relative_path,
                "workspace_type": ws.workspace_type,
                "workspace_visibility": ws.visibility,
                "workspace_protected": bool(ws.protected),
                "workspace_system_managed": bool(ws.system_managed),
                "workspace_external_root": bool(ws.allow_external_root),
                "audit_reasons": audit_reasons,
            },
            metadata_json={
                "read_kind": read_kind,
                "relative_path": relative_path,
                "workspace_type": ws.workspace_type,
                "workspace_visibility": ws.visibility,
                "audit_reasons": audit_reasons,
            },
            force_record=bool(force_record) or bool(audit_reasons),
        )
    )


# ── File tree ─────────────────────────────────────────────────────────────────

_MAX_DEPTH = 5
_MAX_FILES = 500
_MAX_DIFF_BYTES = 512 * 1024
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|private[_-]?key)\s*[:=]\s*([^\s'\"]+)"
)
_SECRET_DIFF_PATH_RE = re.compile(
    r"(?i)(^|/)(\.env($|\.)|id_rsa$|id_ed25519$|secrets?\.[^/]+$|[^/]+\.(pem|key)$|\.ssh/|\.aws/|config/secrets/)"
)
_IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", "dist", "build", ".next", ".nuxt", "coverage",
}
_SHOW_HIDDEN = {
    ".gitignore",
    ".env.example",
    ".env.dev.example",
    ".env.test.example",
    ".env.prod.example",
    ".claude",
    ".editorconfig",
}


def _looks_secret_like_path(path: str | None) -> bool:
    return bool(path and _SECRET_DIFF_PATH_RE.search(path))


def _workspace_read_audit_reasons(
    ws: Workspace,
    *,
    read_kind: str,
    relative_path: str | None,
) -> list[str]:
    reasons: list[str] = []
    if ws.workspace_type == "system_core" or ws.system_managed:
        reasons.append("system_core")
    if ws.allow_external_root:
        reasons.append("external_root")
    if ws.protected or ws.visibility == "restricted":
        reasons.append("restricted_workspace")
    if read_kind == "git_diff" and relative_path is None:
        reasons.append("full_diff")
    if _looks_secret_like_path(relative_path):
        reasons.append("secret_like_path")
    return reasons


def _redact_secret_like_diff(diff: str) -> tuple[str, bool]:
    redacted, count = _SECRET_VALUE_RE.subn(r"\1=[REDACTED]", diff)
    return redacted, count > 0


def _diff_touches_secret_like_path(diff: str) -> bool:
    for line in diff.splitlines():
        if not line.startswith(("diff --git ", "+++ ", "--- ")):
            continue
        if _looks_secret_like_path(line):
            return True
    return False


class FileNode(BaseModel):
    name: str
    path: str          # relative to workspace root, "/" for root
    type: str          # "file" | "dir"
    size: Optional[int] = None
    children: Optional[list["FileNode"]] = None


def _build_tree(root: Path, node_path: Path, depth: int, counter: list[int]) -> FileNode:
    rel = str(node_path.relative_to(root)) if node_path != root else "."
    node = FileNode(name=node_path.name or root.name, path=rel, type="dir" if node_path.is_dir() else "file")

    if node_path.is_file():
        try:
            node.size = node_path.stat().st_size
        except OSError:
            pass
        return node

    if depth >= _MAX_DEPTH or counter[0] >= _MAX_FILES:
        return node

    children: list[FileNode] = []
    try:
        entries = sorted(node_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return node

    for entry in entries:
        if entry.is_dir() and entry.name in _IGNORE_DIRS:
            continue
        if entry.name.startswith(".") and entry.name not in _SHOW_HIDDEN:
            continue
        counter[0] += 1
        if counter[0] > _MAX_FILES:
            break
        children.append(_build_tree(root, entry, depth + 1, counter))

    node.children = children
    return node


# ── Git helpers ───────────────────────────────────────────────────────────────

class GitChangedFile(BaseModel):
    path: str
    status: str   # modified | added | deleted | untracked | renamed


class GitStatus(BaseModel):
    is_repo: bool
    branch: Optional[str]
    files: list[GitChangedFile]


def _parse_porcelain(output: str) -> list[GitChangedFile]:
    result: list[GitChangedFile] = []
    for line in output.splitlines():
        if len(line) < 3:
            continue
        xy = line[:2]
        path = line[3:].strip()
        if "?" in xy:
            status = "untracked"
        elif "R" in xy:
            status = "renamed"
        elif "D" in xy:
            status = "deleted"
        elif "A" in xy:
            status = "added"
        else:
            status = "modified"
        result.append(GitChangedFile(path=path, status=status))
    return result


def _run_git(args: list[str], cwd: Path, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""


# ── Schemas ───────────────────────────────────────────────────────────────────

class FileContent(BaseModel):
    path: str
    content: str
    size: int
    line_count: int


class RuntimeInfo(BaseModel):
    id: str
    name: str
    available: bool
    models: list[str]


class ConsoleSessionCreate(BaseModel):
    workspace_id: Optional[str] = None
    agent_id: Optional[str] = None
    runtime_adapter: str = "claude_code"
    model: Optional[str] = None
    prompt: str


# ── Runtime availability ──────────────────────────────────────────────────────

_RUNTIME_SPECS: list[dict] = [
    {"id": "claude_code", "name": "Claude Code",  "models": ["claude-sonnet-4-6", "claude-opus-4-7"]},
    {"id": "codex_cli",   "name": "OpenAI Codex", "models": ["codex-latest"]},
]


def _is_available(runtime: str) -> bool:
    try:
        from ..runtimes.command_renderer import resolve_executable_for_detection
        from ..runtimes.specs import get_runtime_adapter_spec
        spec = get_runtime_adapter_spec(runtime)
        if spec.runtime_kind == "native":
            return True
        resolve_executable_for_detection(spec)
        return True
    except Exception:
        return False


# ── Routes: workspaces ────────────────────────────────────────────────────────

@router.get("/workspaces")
def list_workspaces(
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, _ = ids
    items = (
        db.query(Workspace)
        .filter(Workspace.owner_space_id == space_id, Workspace.status == "active")
        .order_by(Workspace.updated_at.desc())
        .all()
    )
    return {
        "items": [
            {"id": w.id, "name": w.name, "root_path": w.root_path, "kind": w.kind, "description": w.description}
            for w in items
        ]
    }


@router.get("/workspaces/{workspace_id}/tree", response_model=FileNode)
def get_file_tree(
    workspace_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    ws = _get_ws(db, workspace_id, space_id)
    _enforce_workspace_read(db, ws=ws, actor_user_id=user_id, read_kind="tree")
    root = _ws_path(ws)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Workspace directory not found on disk")
    return _build_tree(root, root, 0, [0])


@router.get("/workspaces/{workspace_id}/file", response_model=FileContent)
def get_file_content(
    workspace_id: str,
    path: str = Query(..., description="Relative file path within workspace"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    ws = _get_ws(db, workspace_id, space_id)
    root = _ws_path(ws)
    try:
        safe = _policy.validate(root / path, allowed_root=root, mode="read", workspace_type=ws.workspace_type)
    except PathPolicyError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not safe.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not safe.is_file():
        raise HTTPException(status_code=400, detail="Path is a directory")
    rel_path = safe.relative_to(root).as_posix()
    _enforce_workspace_read(db, ws=ws, actor_user_id=user_id, read_kind="file", relative_path=rel_path)
    size = safe.stat().st_size
    if size > 1_048_576:  # 1 MiB
        raise HTTPException(status_code=413, detail="File too large to display (max 1 MiB)")
    try:
        content = safe.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return FileContent(path=path, content=content, size=size, line_count=content.count("\n") + 1)


@router.get("/workspaces/{workspace_id}/git/status", response_model=GitStatus)
def get_git_status(
    workspace_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    ws = _get_ws(db, workspace_id, space_id)
    _enforce_workspace_read(db, ws=ws, actor_user_id=user_id, read_kind="git_status")
    root = _ws_path(ws)
    if not (root / ".git").exists():
        return GitStatus(is_repo=False, branch=None, files=[])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root).strip() or None
    raw = _run_git(["status", "--porcelain"], root)
    return GitStatus(is_repo=True, branch=branch, files=_parse_porcelain(raw))


@router.get("/workspaces/{workspace_id}/git/diff")
def get_git_diff(
    workspace_id: str,
    path: Optional[str] = Query(None, description="Relative file path; omit for full diff"),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    space_id, user_id = ids
    ws = _get_ws(db, workspace_id, space_id)
    root = _ws_path(ws)
    cmd = ["diff", "HEAD", "--"]
    rel_path: str | None = None
    if path:
        try:
            safe = _policy.validate(root / path, allowed_root=root, mode="read", workspace_type=ws.workspace_type)
            rel_path = safe.relative_to(root).as_posix()
            cmd.append(rel_path)
        except PathPolicyError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
    _enforce_workspace_read(db, ws=ws, actor_user_id=user_id, read_kind="git_diff", relative_path=rel_path)
    diff = _run_git(cmd, root, timeout=15)
    if not diff:
        diff = _run_git(["diff", "--"] + (cmd[3:] if path else []), root, timeout=15)
    if _diff_touches_secret_like_path(diff):
        raise HTTPException(status_code=403, detail="Diff includes blocked path")
    diff, redacted = _redact_secret_like_diff(diff)
    encoded = diff.encode("utf-8")
    truncated = len(encoded) > _MAX_DIFF_BYTES
    if truncated:
        diff = encoded[:_MAX_DIFF_BYTES].decode("utf-8", errors="replace")
    return {"diff": diff, "path": path, "truncated": truncated, "redacted": redacted}


# ── Routes: runtimes ──────────────────────────────────────────────────────────

@router.get("/runtimes")
def list_runtimes(_: tuple[str, str] = Depends(get_identity)):
    """Return all supported runtimes with live availability status."""
    result = []
    for spec in _RUNTIME_SPECS:
        result.append(RuntimeInfo(
            id=spec["id"],
            name=spec["name"],
            available=_is_available(spec["id"]),
            models=spec["models"],
        ))
    return {"runtimes": result}


# ── Routes: console sessions ──────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(
    workspace_id: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del workspace_id, limit, ids, db
    return {"items": []}


@router.post("/sessions", status_code=201)
def create_session(
    data: ConsoleSessionCreate,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Create and run a console session (not persisted until workspace session storage exists).

    Unknown runtimes are rejected with 400 before the not-implemented response.
    """
    del ids, db
    known = {s["id"] for s in _RUNTIME_SPECS}
    if data.runtime_adapter not in known:
        raise HTTPException(status_code=400, detail=f"Unknown runtime: '{data.runtime_adapter}'")
    feature_not_implemented("workspace_console_sessions")


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del session_id, ids, db
    feature_not_implemented("workspace_console_sessions")


class ConsoleSessionRunTurn(BaseModel):
    prompt: str


@router.post("/sessions/{session_id}/run")
def run_session_turn(
    session_id: str,
    data: ConsoleSessionRunTurn,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del session_id, data, ids, db
    feature_not_implemented("workspace_console_sessions")


@router.post("/sessions/{session_id}/stop")
def stop_session(
    session_id: str,
    ids: tuple[str, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    del session_id, ids, db
    feature_not_implemented("workspace_console_sessions")
