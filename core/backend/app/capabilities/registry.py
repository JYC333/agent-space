from __future__ import annotations
"""
CapabilityRegistry — loads and validates capabilities from manifest files.

DB-backed capability rows are not implemented until a real Capability model and
table exist in the canonical initial migration. reload() syncs only in-memory
state from the capabilities/ directory; list_capabilities() reads that cache.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from .loader import scan_capabilities

log = logging.getLogger(__name__)


@dataclass
class FileDefinedCapability:
    """In-memory capability record shaped for CapabilityOut (from_attributes)."""

    id: str
    name: str
    version: str
    description: str
    entrypoint: Optional[str]
    manifest_json: dict
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CapabilityRegistry:
    def __init__(self, db: Session):
        self.db = db
        self._by_id: dict[str, FileDefinedCapability] = {}

    def reload(self) -> dict:
        # DB-backed capabilities are not implemented until a real Capability model/table exists
        # in the canonical migration. Load file-defined manifests only.
        results = scan_capabilities(settings.capabilities_dir)
        loaded = 0
        failed = 0
        details: list[dict] = []

        for manifest, errors in results:
            if errors:
                failed += 1
                details.append({"id": None, "status": "failed", "errors": errors})
                continue

            cap_id = manifest["id"]
            now = datetime.now(UTC)
            existing = self._by_id.get(cap_id)
            manifest_copy = {k: v for k, v in manifest.items() if k != "_dir"}
            if existing:
                existing.name = manifest["name"]
                existing.version = manifest["version"]
                existing.description = manifest.get("description", "")
                existing.entrypoint = manifest.get("entrypoint")
                existing.manifest_json = manifest_copy
                existing.updated_at = now
            else:
                self._by_id[cap_id] = FileDefinedCapability(
                    id=cap_id,
                    name=manifest["name"],
                    version=manifest["version"],
                    description=manifest.get("description", ""),
                    entrypoint=manifest.get("entrypoint"),
                    manifest_json=manifest_copy,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )

            loaded += 1
            details.append({"id": cap_id, "status": "loaded", "errors": []})

        return {"loaded": loaded, "failed": failed, "details": details}

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
        return cap
