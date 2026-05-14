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
  anthropic_api — synchronous Anthropic SDK call (blocks until response)
  claude_code   — async background task; runs `claude --print` in workspace dir
  codex         — async background task; runs `codex` in workspace dir

  CLI runtimes (claude_code, codex) return status="running" immediately and
  complete via BackgroundTask. Callers poll GET /sessions/{id} until the status
  changes to "completed" or "failed".
"""
from __future__ import annotations

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
from ..workspace.disk_path import workspace_absolute_root
from ..workspace.path_policy import PathPolicy, PathPolicyError
from ..agents.base import RuntimeExecutionResult

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


# ── File tree ─────────────────────────────────────────────────────────────────

_MAX_DEPTH = 5
_MAX_FILES = 500
_IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", "dist", "build", ".next", ".nuxt", "coverage",
}
_SHOW_HIDDEN = {".gitignore", ".env.example", ".claude", ".editorconfig"}


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


# ── Runtime adapter registry ──────────────────────────────────────────────────

# Map console runtime IDs → adapter classes (imported lazily to avoid circular deps)
_RUNTIME_SPECS: list[dict] = [
    {"id": "anthropic_api", "name": "Anthropic API",  "models": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"]},
    {"id": "claude_code",   "name": "Claude Code",    "models": ["claude-sonnet-4-6", "claude-opus-4-7"]},
    {"id": "codex",         "name": "OpenAI Codex",   "models": ["codex-latest"]},
]


def _make_adapter(runtime: str, model: str | None = None):
    """Instantiate the appropriate adapter for a console runtime ID."""
    if runtime == "anthropic_api":
        from ..agents.api_adapter import AnthropicAPIAdapter
        return AnthropicAPIAdapter(model=model)
    if runtime == "claude_code":
        from ..agents.claude_adapter import ClaudeCLIAdapter
        return ClaudeCLIAdapter(model=model)
    if runtime == "codex":
        from ..agents.codex_adapter import CodexCLIAdapter
        return CodexCLIAdapter()
    return None


def _is_available(runtime: str) -> bool:
    try:
        adapter = _make_adapter(runtime)
        return adapter is not None and adapter.is_available()
    except Exception:
        return False


def _result_to_events(result: "RuntimeExecutionResult") -> list[dict]:
    """Convert a RuntimeExecutionResult to the RuntimeEvent list for a console session."""
    events: list[dict] = []
    if result.output:
        events.append({"type": "text_delta", "content": result.output})
    if result.success:
        events.append({"type": "run_completed"})
    else:
        events.append({"type": "run_failed", "error": result.error or "Run failed"})
    return events


def _events_to_messages(events: list[dict]) -> list[dict]:
    """
    Reconstruct an Anthropic-style messages array from stored session events.

    user_turn events mark user prompts; text_delta events accumulate assistant
    content. Only completed turns (those followed by at least one text_delta)
    are included — the caller is responsible for appending the new user message.
    """
    messages: list[dict] = []
    current_prompt: str | None = None
    current_response: list[str] = []

    for ev in events:
        t = ev.get("type")
        if t == "user_turn":
            if current_prompt is not None and current_response:
                messages.append({"role": "user", "content": current_prompt})
                messages.append({"role": "assistant", "content": "".join(current_response)})
            current_prompt = ev.get("prompt", "")
            current_response = []
        elif t == "text_delta" and current_prompt is not None:
            current_response.append(ev.get("content", ""))

    # Flush the last turn if it has an assistant response
    if current_prompt is not None and current_response:
        messages.append({"role": "user", "content": current_prompt})
        messages.append({"role": "assistant", "content": "".join(current_response)})

    return messages


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
    space_id, _ = ids
    ws = _get_ws(db, workspace_id, space_id)
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
    space_id, _ = ids
    ws = _get_ws(db, workspace_id, space_id)
    root = _ws_path(ws)
    try:
        safe = _policy.validate(root / path, allowed_root=root, mode="read")
    except PathPolicyError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not safe.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not safe.is_file():
        raise HTTPException(status_code=400, detail="Path is a directory")
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
    space_id, _ = ids
    ws = _get_ws(db, workspace_id, space_id)
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
    space_id, _ = ids
    ws = _get_ws(db, workspace_id, space_id)
    root = _ws_path(ws)
    cmd = ["diff", "HEAD", "--"]
    if path:
        try:
            safe = _policy.validate(root / path, allowed_root=root, mode="read")
            cmd.append(str(safe))
        except PathPolicyError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
    diff = _run_git(cmd, root, timeout=15)
    if not diff:
        diff = _run_git(["diff", "--"] + (cmd[3:] if path else []), root, timeout=15)
    return {"diff": diff, "path": path}


# ── Routes: runtimes ──────────────────────────────────────────────────────────

@router.get("/runtimes")
def list_runtimes():
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
