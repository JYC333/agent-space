"""Sandbox / workdir orchestration for run execution."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .worktree_manager import isolated_run_workdir


@contextmanager
def execution_workspace(
    *,
    space_id: str,
    run_id: str,
    required_sandbox_level: str,
) -> Iterator[str | None]:
    """Yield optional working directory based on policy-derived sandbox level.

    - ``none`` / ``dry_run``: no isolated directory (adapter runs without cwd isolation).
    - ``worktree``: isolated directory under sandbox root (cleaned up on exit).
    - ``one_shot_docker``: not implemented in this build — caller must pre-check.
    """
    if required_sandbox_level in ("none", "dry_run"):
        yield None
        return
    if required_sandbox_level == "worktree":
        with isolated_run_workdir(space_id, run_id) as path:
            yield path
        return
    # one_shot_docker — should be rejected before entering this manager
    yield None
