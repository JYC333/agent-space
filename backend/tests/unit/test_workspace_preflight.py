"""Unit tests for workspace preflight (WorkspacePreflight + run_workspace_preflight).

Invariants verified:
  1. Non-git directory raises WorkspaceNotGitRepoError.
  2. Clean repo: is_dirty=False, dirty_files=[], base_commit_sha non-empty.
  3. Dirty repo (uncommitted tracked change): is_dirty=True, dirty_files lists the file.
  4. Dirty repo (untracked file): is_dirty=True, dirty_files lists the file.
  5. base_commit_sha matches the HEAD commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.runs.workspace_worktree import (
    WorkspacePreflight,
    WorkspaceNotGitRepoError,
    run_workspace_preflight,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "hi") -> str:
    """Initialise a git repo and return the HEAD commit SHA."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(path))
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(path)
    )
    return result.stdout.strip()


# ===========================================================================
# 1. Non-git directory raises WorkspaceNotGitRepoError
# ===========================================================================


def test_preflight_non_git_dir_raises(tmp_path):
    non_git = tmp_path / "not-a-repo"
    non_git.mkdir()
    with pytest.raises(WorkspaceNotGitRepoError):
        run_workspace_preflight(non_git)


# ===========================================================================
# 2. Clean repo
# ===========================================================================


def test_preflight_clean_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    expected_sha = _init_git_repo(repo)

    pf = run_workspace_preflight(repo)

    assert isinstance(pf, WorkspacePreflight)
    assert pf.is_dirty is False
    assert pf.dirty_files == []
    assert pf.base_commit_sha == expected_sha


# ===========================================================================
# 3. Dirty repo — uncommitted tracked change
# ===========================================================================


def test_preflight_dirty_modified_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "hello.txt", "original")
    (repo / "hello.txt").write_text("modified", encoding="utf-8")

    pf = run_workspace_preflight(repo)

    assert pf.is_dirty is True
    assert any("hello.txt" in f for f in pf.dirty_files)


# ===========================================================================
# 4. Dirty repo — untracked file
# ===========================================================================


def test_preflight_dirty_untracked_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "new_file.py").write_text("brand new", encoding="utf-8")

    pf = run_workspace_preflight(repo)

    assert pf.is_dirty is True
    assert any("new_file.py" in f for f in pf.dirty_files)


# ===========================================================================
# 5. base_commit_sha matches HEAD
# ===========================================================================


def test_preflight_base_commit_sha_matches_head(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = _init_git_repo(repo)

    pf = run_workspace_preflight(repo)

    assert pf.base_commit_sha == sha
    assert len(pf.base_commit_sha) == 40  # SHA-1 hex


# ===========================================================================
# 6. Staged (not committed) change is also dirty
# ===========================================================================


def test_preflight_staged_change_is_dirty(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "hello.txt", "original")
    (repo / "staged.py").write_text("staged content", encoding="utf-8")
    subprocess.run(["git", "add", "staged.py"], check=True, capture_output=True, cwd=str(repo))

    pf = run_workspace_preflight(repo)

    assert pf.is_dirty is True
