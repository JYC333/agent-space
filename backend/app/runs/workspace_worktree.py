"""Git worktree isolation for CLI runs that target a workspace.

When ``required_sandbox_level=worktree`` and the Run has a ``workspace_id``
pointing to a git repository, this module creates a detached git worktree
under ``sandbox_root`` so the CLI tool operates on an isolated copy of the
workspace tree. The worktree is removed on context exit.

Non-git workspace roots are rejected with a clear error — CLI adapters must
not run against an empty sandbox when a real workspace is specified.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workspace preflight
# ---------------------------------------------------------------------------


@dataclass
class WorkspacePreflight:
    """Git status snapshot captured before a worktree is created."""

    base_commit_sha: str | None
    """HEAD commit SHA of the workspace at preflight time, or None when git fails."""

    is_dirty: bool
    """True when the workspace has uncommitted changes (tracked or untracked)."""

    dirty_files: list[str] = field(default_factory=list)
    """Relative file paths that are uncommitted (from git status --porcelain)."""


def run_workspace_preflight(workspace_root: Path) -> WorkspacePreflight:
    """Snapshot HEAD commit SHA and dirty status before worktree creation.

    Raises :class:`WorkspaceNotGitRepoError` when ``workspace_root`` is not a
    git repository.  On any other git failure the field is left as None /
    empty (non-fatal — the worktree creation that follows will surface the
    real error if the repo is corrupt).
    """
    if not _is_git_repo(workspace_root):
        raise WorkspaceNotGitRepoError(
            f"Workspace at '{workspace_root}' is not a git repository."
        )

    # HEAD commit SHA
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True,
        cwd=str(workspace_root), timeout=10,
    )
    base_commit_sha = head_result.stdout.strip() if head_result.returncode == 0 else None

    # Dirty status
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True,
        cwd=str(workspace_root), timeout=10,
    )
    dirty_files: list[str] = []
    if status_result.returncode == 0:
        for line in status_result.stdout.splitlines():
            if len(line) >= 3:
                dirty_files.append(line[3:].strip())

    return WorkspacePreflight(
        base_commit_sha=base_commit_sha,
        is_dirty=len(dirty_files) > 0,
        dirty_files=dirty_files,
    )


class WorkspaceNotGitRepoError(ValueError):
    """Raised when the workspace root_path is not a git repository."""


def _ensure_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("worktree path escapes sandbox_root") from exc


def _is_git_repo(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            cwd=str(path),
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


@contextmanager
def workspace_git_worktree(
    *,
    space_id: str,
    run_id: str,
    workspace_root: Path,
) -> Iterator[str]:
    """Create a detached git worktree for ``workspace_root`` and yield its path.

    The worktree is created under ``{sandbox_root}/worktrees/{space_id}/{run_id}``
    linked to the workspace git repository at HEAD. It is removed on exit.

    Raises :class:`WorkspaceNotGitRepoError` when ``workspace_root`` is not a
    git repository — CLI adapters must not fall back to an empty directory.
    Raises :class:`RuntimeError` when ``git worktree add`` fails.
    """
    wt_path = create_workspace_git_worktree(
        space_id=space_id,
        run_id=run_id,
        workspace_root=workspace_root,
    )

    try:
        yield str(wt_path)
    finally:
        cleanup_workspace_git_worktree(
            space_id=space_id,
            run_id=run_id,
            workspace_root=workspace_root,
            worktree_path=wt_path,
        )


def create_workspace_git_worktree(
    *,
    space_id: str,
    run_id: str,
    workspace_root: Path,
) -> Path:
    """Create a detached git worktree and return its path.

    Unlike :func:`workspace_git_worktree`, this helper does not clean up on
    scope exit. It is used by service-to-service execution where TypeScript owns
    adapter lifetime and calls an explicit cleanup port afterward.
    """
    if not _is_git_repo(workspace_root):
        raise WorkspaceNotGitRepoError(
            f"Workspace at '{workspace_root}' is not a git repository. "
            "CLI adapters (claude_code, codex_cli) require a git worktree for "
            "sandboxed execution. Initialise the workspace root as a git repo first."
        )

    root = Path(settings.sandbox_root).resolve()
    wt_base = (root / "worktrees").resolve()
    _ensure_under_root(wt_base, root)
    wt_path = (wt_base / space_id / run_id).resolve()
    _ensure_under_root(wt_path, wt_base)

    wt_path.parent.mkdir(parents=True, exist_ok=True)
    if wt_path.exists():
        _cleanup_worktree(workspace_root, wt_path, run_id)

    add_result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt_path), "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(workspace_root),
        timeout=30,
    )
    if add_result.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed for workspace '{workspace_root}': "
            f"{add_result.stderr.strip()[:1000]}"
        )

    log.debug(
        "git worktree created space=%s run=%s path=%s",
        space_id, run_id, wt_path,
    )
    return wt_path


def cleanup_workspace_git_worktree(
    *,
    space_id: str,
    run_id: str,
    workspace_root: Path,
    worktree_path: Path | str | None = None,
) -> None:
    """Remove a detached git worktree under the configured sandbox root."""
    root = Path(settings.sandbox_root).resolve()
    wt_base = (root / "worktrees").resolve()
    _ensure_under_root(wt_base, root)
    wt_path = Path(worktree_path).resolve() if worktree_path else (wt_base / space_id / run_id).resolve()
    _ensure_under_root(wt_path, wt_base)
    _cleanup_worktree(workspace_root, wt_path, run_id)


def _cleanup_worktree(workspace_root: Path, wt_path: Path, run_id: str) -> None:
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            capture_output=True,
            cwd=str(workspace_root),
            timeout=15,
        )
    except Exception:
        log.warning("git worktree remove failed for run=%s; falling back to rmtree", run_id)
    # Always attempt rmtree in case git worktree remove left files behind.
    shutil.rmtree(wt_path, ignore_errors=True)
    log.debug("git worktree cleaned up run=%s path=%s", run_id, wt_path)
