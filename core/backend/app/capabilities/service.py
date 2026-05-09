from __future__ import annotations
"""
CapabilityService — thin facade over the registry for use in API routes.
"""

from sqlalchemy.orm import Session
from .registry import CapabilityRegistry


class CapabilityService:
    def __init__(self, db: Session):
        self.registry = CapabilityRegistry(db)

    def reload(self) -> dict:
        return self.registry.reload()

    def list(self, enabled_only: bool = True):
        return self.registry.list_capabilities(enabled_only=enabled_only)

    def get(self, capability_id: str):
        return self.registry.get(capability_id)
