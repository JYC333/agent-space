"""Invariant: workspace file paths resolved for access stay under the workspace root (PathPolicy at service glue)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import Workspace
from app.workspace.path_policy import PathPolicy, PathPolicyError


def _resolved_workspace_disk_root(ws: Workspace, workspace_root: Path) -> Path:
    """Same resolution as workspace console file routes (no HTTP)."""
    root = workspace_root.resolve()
    if ws.root_path:
        p = Path(ws.root_path)
        return p.resolve() if p.is_absolute() else (root / ws.root_path).resolve()
    return (root / ws.id).resolve()


def test_workspace_console_path_glue_denies_traversal(monkeypatch, db, tmp_path, test_user):
    """Mirrors ``workspace_console`` file read path: ``root / user_path`` then PathPolicy.validate."""
    from app.config import settings

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = Workspace(
        id="ws-inv-1",
        space_id=test_user.space_id,
        name="inv",
        root_path=None,
        created_by_user_id=test_user.id,
    )
    db.add(ws)
    db.flush()

    disk_root = _resolved_workspace_disk_root(ws, ws_root)
    disk_root.mkdir(parents=True, exist_ok=True)
    (disk_root / "readme.txt").write_text("safe", encoding="utf-8")

    policy = PathPolicy(workspace_root=ws_root, sandbox_root=tmp_path / "sandboxes")
    safe = policy.validate(disk_root / "readme.txt", allowed_root=disk_root, mode="read")
    assert safe.read_text() == "safe"

    with pytest.raises(PathPolicyError):
        policy.validate(disk_root / ".." / ".." / "etc" / "passwd", allowed_root=disk_root, mode="read")

    outside = Path("/tmp") / "nope.txt"
    with pytest.raises(PathPolicyError):
        policy.validate(outside, allowed_root=disk_root, mode="read")


def test_absolute_path_outside_workspace_root_rejected(monkeypatch, tmp_path):
    from app.config import settings

    ws_root = tmp_path / "w"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    policy = PathPolicy(workspace_root=ws_root)
    allowed = (ws_root / "proj").resolve()
    allowed.mkdir()
    (allowed / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PathPolicyError):
        policy.validate(Path("/etc/passwd"), allowed_root=allowed, mode="read")
