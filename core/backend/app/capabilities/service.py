from __future__ import annotations
"""
CapabilityService — thin facade over the registry for use in API routes.
"""

from sqlalchemy.orm import Session
from .registry import CapabilityRegistry


class CapabilityService:
    def __init__(self, db: Session):
        self.registry = CapabilityRegistry(db)

    def reload(self, *, space_id: str | None = None) -> dict:
        return self.registry.reload(space_id=space_id)

    def list(self, enabled_only: bool = True, *, space_id: str | None = None):
        self.registry.reload(space_id=space_id)
        return self.registry.list_capabilities(enabled_only=enabled_only)

    def get(self, capability_id: str, *, space_id: str | None = None):
        self.registry.reload(space_id=space_id)
        return self.registry.get(capability_id)
