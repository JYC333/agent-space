"""Resolve on-disk roots for registered ``Workspace`` rows (shared by console + patch apply)."""

from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..models import Workspace


def workspace_absolute_root(ws: Workspace) -> Path:
    """Return the absolute directory root for files under this workspace."""
    workspace_root = Path(settings.workspace_root).resolve()
    if ws.root_path:
        p = Path(ws.root_path)
        return p.resolve() if p.is_absolute() else (workspace_root / ws.root_path).resolve()
    return (workspace_root / ws.id).resolve()
