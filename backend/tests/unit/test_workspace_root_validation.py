"""Unit tests for app.workspace.root_validation.

Covers:
  1. Managed root under workspace_root succeeds
  2. Absolute external root without allow_external_root fails with workspace_root_untrusted_external
  3. Absolute external root with allow_external_root=True succeeds
  4. Cross-space workspace fails with workspace_cross_space
  5. Non-existent root fails with workspace_root_not_found
  6. File path (not directory) fails with workspace_root_not_directory
  7. Non-git root with sandbox_level=worktree fails with workspace_root_not_git_repo
  8. Non-git root with sandbox_level=none succeeds (git check only for worktree)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.workspace.root_validation import (
    WorkspaceRootValidationError,
    validate_workspace_root_for_execution,
)


def _call(
    *,
    workspace_space_id: str = "sp-a",
    run_space_id: str = "sp-a",
    workspace_root: Path,
    allow_external_root: bool = False,
    sandbox_level: str = "worktree",
) -> None:
    validate_workspace_root_for_execution(
        workspace_space_id=workspace_space_id,
        run_space_id=run_space_id,
        workspace_root=workspace_root,
        allow_external_root=allow_external_root,
        sandbox_level=sandbox_level,
    )


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(path))
    (path / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


# ===========================================================================
# 1. Managed root under workspace_root succeeds
# ===========================================================================


def test_managed_root_under_workspace_root_succeeds(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    repo = ws_root / "my-project"
    repo.mkdir()
    _init_git(repo)

    _call(workspace_root=repo, allow_external_root=False, sandbox_level="worktree")


# ===========================================================================
# 2. External root without trust fails
# ===========================================================================


def test_external_root_without_trust_fails(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    external = tmp_path / "elsewhere"
    external.mkdir()
    _init_git(external)

    with pytest.raises(WorkspaceRootValidationError) as exc_info:
        _call(workspace_root=external, allow_external_root=False, sandbox_level="worktree")

    assert exc_info.value.error_code == "workspace_root_untrusted_external"


# ===========================================================================
# 3. External root with allow_external_root=True succeeds
# ===========================================================================


def test_external_root_with_trust_succeeds(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    external = tmp_path / "trusted-repo"
    external.mkdir()
    _init_git(external)

    _call(workspace_root=external, allow_external_root=True, sandbox_level="worktree")


# ===========================================================================
# 4. Cross-space workspace fails
# ===========================================================================


def test_cross_space_workspace_fails(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    repo = ws_root / "proj"
    repo.mkdir()
    _init_git(repo)

    with pytest.raises(WorkspaceRootValidationError) as exc_info:
        _call(
            workspace_space_id="space-owner",
            run_space_id="space-attacker",
            workspace_root=repo,
            allow_external_root=False,
            sandbox_level="worktree",
        )

    assert exc_info.value.error_code == "workspace_cross_space"


# ===========================================================================
# 5. Non-existent root fails
# ===========================================================================


def test_nonexistent_root_fails(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    missing = ws_root / "does-not-exist"

    with pytest.raises(WorkspaceRootValidationError) as exc_info:
        _call(workspace_root=missing, allow_external_root=False, sandbox_level="worktree")

    assert exc_info.value.error_code == "workspace_root_not_found"


# ===========================================================================
# 6. File (not directory) fails
# ===========================================================================


def test_file_as_root_fails(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    not_dir = ws_root / "afile.txt"
    not_dir.write_text("oops", encoding="utf-8")

    with pytest.raises(WorkspaceRootValidationError) as exc_info:
        _call(workspace_root=not_dir, allow_external_root=False, sandbox_level="worktree")

    assert exc_info.value.error_code == "workspace_root_not_directory"


# ===========================================================================
# 7. Non-git root with sandbox_level=worktree fails
# ===========================================================================


def test_non_git_root_with_worktree_sandbox_fails(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    plain_dir = ws_root / "not-a-repo"
    plain_dir.mkdir()

    with pytest.raises(WorkspaceRootValidationError) as exc_info:
        _call(workspace_root=plain_dir, allow_external_root=False, sandbox_level="worktree")

    assert exc_info.value.error_code == "workspace_root_not_git_repo"


# ===========================================================================
# 8. Non-git root with sandbox_level=none succeeds (git check skipped)
# ===========================================================================


def test_non_git_root_with_none_sandbox_succeeds(tmp_path, monkeypatch):
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    plain_dir = ws_root / "not-a-repo"
    plain_dir.mkdir()

    # sandbox_level=none → no git check → should pass
    _call(workspace_root=plain_dir, allow_external_root=False, sandbox_level="none")
