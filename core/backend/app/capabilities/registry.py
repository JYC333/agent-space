from __future__ import annotations
"""
CapabilityRegistry — loads, validates, and stores capabilities in the database.
"""

from sqlalchemy.orm import Session

from ..models import Capability
from ..config import settings
from .loader import scan_capabilities


class CapabilityRegistry:
    def __init__(self, db: Session):
        self.db = db

    def reload(self) -> dict:
        """Scan capabilities/ directory and sync to database."""
        results = scan_capabilities(settings.capabilities_dir)
        loaded = 0
        failed = 0
        details = []

        for manifest, errors in results:
            if errors:
                failed += 1
                details.append({"id": None, "status": "failed", "errors": errors})
                continue

            cap_id = manifest["id"]
            existing = self.db.query(Capability).filter(Capability.id == cap_id).first()

            if existing:
                existing.name = manifest["name"]
                existing.version = manifest["version"]
                existing.description = manifest.get("description", "")
                existing.entrypoint = manifest.get("entrypoint")
                existing.manifest_json = manifest
            else:
                cap = Capability(
                    id=cap_id,
                    name=manifest["name"],
                    version=manifest["version"],
                    description=manifest.get("description", ""),
                    entrypoint=manifest.get("entrypoint"),
                    manifest_json=manifest,
                    enabled=True,
                )
                self.db.add(cap)

            loaded += 1
            details.append({"id": cap_id, "status": "loaded", "errors": []})

        self.db.commit()
        return {"loaded": loaded, "failed": failed, "details": details}

    def list_capabilities(self, enabled_only: bool = True) -> list[Capability]:
        q = self.db.query(Capability)
        if enabled_only:
            q = q.filter(Capability.enabled.is_(True))
        return q.order_by(Capability.id).all()

    def get(self, capability_id: str) -> Capability | None:
        return self.db.query(Capability).filter(Capability.id == capability_id).first()

    def set_enabled(self, capability_id: str, enabled: bool) -> Capability | None:
        cap = self.get(capability_id)
        if not cap:
            return None
        cap.enabled = enabled
        self.db.commit()
        self.db.refresh(cap)
        return cap
