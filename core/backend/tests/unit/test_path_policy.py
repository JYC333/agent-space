"""
Boundary unit tests for PathPolicy (tmp_path only; no repo or host paths).
"""
import os
import sys

import pytest
from pathlib import Path

from app.workspace.path_policy import PathPolicy, PathPolicyError


def _policy(tmp_path: Path) -> PathPolicy:
    workspace_root = tmp_path / "workspaces"
    sandbox_root = tmp_path / "sandboxes"
    workspace_root.mkdir()
    sandbox_root.mkdir()
    return PathPolicy(workspace_root=workspace_root, sandbox_root=sandbox_root)


def test_validate_allows_file_inside_explicit_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f = root / "nested" / "a.txt"
    f.parent.mkdir(parents=True)
    f.write_text("ok")
    policy = _policy(tmp_path)
    resolved = policy.validate(str(f), allowed_root=str(root))
    assert resolved == f.resolve()


def test_validate_denies_parent_traversal_with_normalized_message(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    policy = _policy(tmp_path)
    evil = root / ".." / "outside"
    with pytest.raises(PathPolicyError) as ei:
        policy.validate(str(evil / "x.txt"), allowed_root=str(root))
    assert "traversal" in str(ei.value).lower()
    assert str(root.resolve()) in str(ei.value) or "not under" in str(ei.value)


def test_validate_denies_absolute_path_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    policy = _policy(tmp_path)
    with pytest.raises(PathPolicyError, match="traversal|not under"):
        policy.validate("/etc/passwd", allowed_root=str(root))


@pytest.mark.skipif(
    not getattr(os, "symlink", None) or sys.platform == "win32",
    reason="symlink escape test requires POSIX symlink support",
)
def test_validate_denies_symlink_resolving_outside_root(tmp_path):
    """Path.resolve() follows symlinks; result must stay under allowed_root."""
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "secret.txt"
    target_file.write_text("secret")
    link = root / "escape"
    os.symlink(str(target_file.resolve()), str(link))
    policy = _policy(tmp_path)
    with pytest.raises(PathPolicyError, match="traversal|not under"):
        policy.validate(str(link), allowed_root=str(root))


def test_validate_workspace_requires_registered_directory(tmp_path):
    policy = _policy(tmp_path)
    with pytest.raises(PathPolicyError, match="not registered"):
        policy.validate_workspace("anything.txt", workspace_id="missing-ws")


def test_is_safe_false_on_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    policy = _policy(tmp_path)
    assert policy.is_safe(str(root / ".." / "etc"), allowed_root=str(root)) is False


def test_trusted_code_patch_apply_bypasses_script_write_suffix_block(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    script = root / "tool.py"
    policy = _policy(tmp_path)
    with pytest.raises(PathPolicyError, match="code_patch"):
        policy.validate(str(script), allowed_root=str(root), mode="write")
    resolved = policy.validate(
        str(script),
        allowed_root=str(root),
        mode="write",
        for_trusted_code_patch_apply=True,
    )
    assert resolved == script.resolve()
