"""Sandbox / workdir orchestration for run execution."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .worktree_manager import isolated_run_workdir


@contextmanager
def execution_workspace(
    *,
    space_id: str,
    run_id: str,
    required_sandbox_level: str,
    workspace_root: Path | None = None,
) -> Iterator[str | None]:
    """Yield optional working directory based on policy-derived sandbox level.

    - ``none`` / ``dry_run``: no isolated directory (adapter runs without cwd isolation).
    - ``worktree`` with ``workspace_root``: detached git worktree under sandbox root.
      Raises :class:`~.workspace_worktree.WorkspaceNotGitRepoError` when the
      workspace is not a git repository.
    - ``worktree`` without ``workspace_root``: plain isolated directory (fallback
      used when the Run has no workspace_id).
    - ``one_shot_docker``: not implemented in this build — caller must pre-check.
    """
    if required_sandbox_level in ("none", "dry_run"):
        yield None
        return
    if required_sandbox_level == "worktree":
        if workspace_root is not None:
            from .workspace_worktree import workspace_git_worktree
            with workspace_git_worktree(
                space_id=space_id,
                run_id=run_id,
                workspace_root=workspace_root,
            ) as path:
                yield path
        else:
            with isolated_run_workdir(space_id, run_id) as path:
                yield path
        return
    # one_shot_docker — should be rejected before entering this manager
    yield None
