from __future__ import annotations
"""
CapabilityRegistry — loads and validates capabilities from manifest files.

Registry records are held in memory per reload. Builtin capabilities use manifest
``enabled``; external workspace capabilities default disabled with enable state
persisted in ``$AGENT_SPACE_HOME/config/settings.yaml``. There is no DB-backed
capability table.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Workspace
from ..workspace.disk_path import workspace_absolute_root
from ..workspace.path_policy import PathPolicy, PathPolicyError
from .enabled_store import load_enabled_external_capabilities, set_external_capability_enabled
from .loader import scan_capabilities

log = logging.getLogger(__name__)

# In-memory overrides for builtin capabilities only (manifest is source of truth on reload).
_BUILTIN_ENABLED_OVERRIDES: dict[str, bool] = {}


@dataclass
class FileDefinedCapability:
    """In-memory capability record shaped for CapabilityOut (from_attributes)."""

    id: str
    name: str
    version: str
    description: str
    entrypoint: Optional[Any]
    manifest_dir: str
    manifest_json: dict
    source: str = "builtin"
    workspace_id: str | None = None
    root_path: str | None = None
    manifest_path: str | None = None
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CapabilityRegistry:
    def __init__(self, db: Session | None):
        self.db = db
        self._by_id: dict[str, FileDefinedCapability] = {}
        self._persisted_external_enabled: set[str] = set()

    def reload(self, *, space_id: str | None = None) -> dict:
        # DB-backed capabilities are not implemented until a real Capability model/table exists
        # in the canonical migration. Load file-defined manifests only.
        loaded = 0
        failed = 0
        details: list[dict] = []

        self._by_id = {}
        self._persisted_external_enabled = load_enabled_external_capabilities()
        results = scan_capabilities(settings.capabilities_dir)
        for manifest, errors in results:
            if errors:
                failed += 1
                details.append({"id": None, "status": "failed", "errors": errors})
                continue

            self._load_manifest(
                manifest,
                source="builtin",
                root_path=str(Path(settings.capabilities_dir).resolve()),
                workspace_id=None,
                default_enabled=bool(manifest.get("enabled", True)),
            )
            loaded += 1
            details.append({"id": manifest["id"], "status": "loaded", "source": "builtin", "errors": []})

        if self.db is not None and space_id is not None:
            for root, workspace, root_errors in self._external_roots(space_id):
                if root_errors:
                    failed += 1
                    details.append({
                        "id": None,
                        "status": "failed",
                        "source": "external_workspace",
                        "workspace_id": workspace.id,
                        "root_path": str(root) if root else None,
                        "errors": root_errors,
                    })
                    continue
                assert root is not None
                for manifest, errors in scan_capabilities(str(root)):
                    if errors:
                        failed += 1
                        details.append({
                            "id": None,
                            "status": "failed",
                            "source": "external_workspace",
                            "workspace_id": workspace.id,
                            "root_path": str(root),
                            "errors": errors,
                        })
                        continue
                    cap_id = manifest["id"]
                    if cap_id in self._by_id:
                        failed += 1
                        details.append({
                            "id": cap_id,
                            "status": "failed",
                            "source": "external_workspace",
                            "workspace_id": workspace.id,
                            "root_path": str(root),
                            "errors": [f"Duplicate capability id '{cap_id}'"],
                        })
                        continue
                    self._load_manifest(
                        manifest,
                        source="external_workspace",
                        root_path=str(root),
                        workspace_id=workspace.id,
                        default_enabled=False,
                    )
                    loaded += 1
                    details.append({
                        "id": cap_id,
                        "status": "loaded",
                        "source": "external_workspace",
                        "workspace_id": workspace.id,
                        "root_path": str(root),
                        "errors": [],
                    })

        return {"loaded": loaded, "failed": failed, "details": details}

    def _load_manifest(
        self,
        manifest: dict,
        *,
        source: str,
        root_path: str,
        workspace_id: str | None,
        default_enabled: bool,
    ) -> None:
        cap_id = manifest["id"]
        now = datetime.now(UTC)
        manifest_copy = {
            k: v for k, v in manifest.items()
            if k not in {"_dir", "_manifest_path"}
        }
        if source == "external_workspace":
            enabled = cap_id in self._persisted_external_enabled
        else:
            enabled = _BUILTIN_ENABLED_OVERRIDES.get(cap_id, default_enabled)
        self._by_id[cap_id] = FileDefinedCapability(
            id=cap_id,
            name=manifest["name"],
            version=manifest["version"],
            description=manifest.get("description", ""),
            entrypoint=manifest.get("entrypoint"),
            manifest_dir=manifest["_dir"],
            source=source,
            workspace_id=workspace_id,
            root_path=root_path,
            manifest_path=manifest.get("_manifest_path"),
            manifest_json=manifest_copy,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )

    def _external_roots(
        self,
        space_id: str,
    ) -> list[tuple[Path | None, Workspace, list[str]]]:
        assert self.db is not None
        workspaces = (
            self.db.query(Workspace)
            .filter(
                Workspace.space_id == space_id,
                Workspace.status == "active",
                Workspace.workspace_type == "capability_library",
            )
            .all()
        )
        rows: list[tuple[Path | None, Workspace, list[str]]] = []
        policy = PathPolicy()
        for ws in workspaces:
            meta = ws.metadata_json or {}
            roots = meta.get("capability_roots")
            if roots is None:
                continue
            if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
                rows.append((None, ws, ["metadata_json.capability_roots must be a list of strings"]))
                continue
            workspace_root = workspace_absolute_root(ws)
            for rel in roots:
                try:
                    rel_path = Path(rel)
                    if rel_path.is_absolute():
                        raise ValueError("capability root must be a relative path")
                    if ".." in rel_path.parts:
                        raise ValueError("capability root must not contain '..'")
                    candidate = (workspace_root / rel_path).resolve()
                    safe = policy.validate(
                        candidate,
                        allowed_root=workspace_root,
                        mode="read",
                        workspace_type=ws.workspace_type,
                    )
                except (ValueError, PathPolicyError) as exc:
                    rows.append((None, ws, [str(exc)]))
                    continue
                rows.append((safe, ws, []))
        return rows

    def list_capabilities(self, enabled_only: bool = True) -> list[FileDefinedCapability]:
        items = list(self._by_id.values())
        if enabled_only:
            items = [c for c in items if c.enabled]
        return sorted(items, key=lambda c: c.id)

    def get(self, capability_id: str) -> FileDefinedCapability | None:
        return self._by_id.get(capability_id)

    def set_enabled(self, capability_id: str, enabled: bool) -> FileDefinedCapability | None:
        cap = self._by_id.get(capability_id)
        if not cap:
            return None
        cap.enabled = enabled
        cap.updated_at = datetime.now(UTC)
        if cap.source == "external_workspace":
            set_external_capability_enabled(capability_id, enabled)
            if enabled:
                self._persisted_external_enabled.add(capability_id)
            else:
                self._persisted_external_enabled.discard(capability_id)
        else:
            _BUILTIN_ENABLED_OVERRIDES[capability_id] = enabled
        return cap


def load_installed_capability(
    capability_id: str,
    *,
    db: Session | None = None,
    space_id: str | None = None,
) -> FileDefinedCapability | None:
    """Load one file-defined capability from the configured capabilities directory."""
    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)
    return registry.get(capability_id)
