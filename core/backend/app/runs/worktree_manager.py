"""Isolated working directory for ``required_sandbox_level=worktree``.

Uses ``SANDBOX_ROOT`` / ``settings.sandbox_root`` — never the artifact storage root.
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import settings


def _ensure_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("worktree path escapes sandbox_root") from exc


@contextmanager
def isolated_run_workdir(space_id: str, run_id: str) -> Iterator[str]:
    """Yield a dedicated directory under the sandbox root; delete it on exit."""
    root = Path(settings.sandbox_root).resolve()
    worktrees_root = (root / "worktrees").resolve()
    _ensure_under_root(worktrees_root, root)
    work = (worktrees_root / space_id / run_id).resolve()
    _ensure_under_root(work, worktrees_root)
    work.mkdir(parents=True, exist_ok=True)
    try:
        yield str(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
