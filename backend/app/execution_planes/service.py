from __future__ import annotations
"""ExecutionPlane service — read and resolution helpers.

ExecutionPlanes are system records seeded at install time. This service
provides read and resolution helpers; it does not own plane lifecycle.
"""

import logging
from sqlalchemy.orm import Session

from ..models import ExecutionPlane

log = logging.getLogger(__name__)

# Maps adapter_type short names to canonical execution plane names.
# Planes must be seeded by ExecutionPlaneSeeder before these lookups are useful.
#
# Policy note: ``model_api`` is the in-process, vendor-neutral API runtime
# adapter. It uses the providers/LiteLLM layer and selects any configured
# ModelProvider + model, including Anthropic, without exposing provider API keys
# to CLI subprocess environments. Do not add vendor-specific runtime types like
# ``anthropic_api``; the adapter stays vendor-neutral and selects the provider
# at runtime.
# ``ts_agent_host`` uses the same managed provider plane, but credential release
# happens inside control-plane over the internal channel rather than in Python.
_ADAPTER_TO_PLANE: dict[str, str] = {
    "capability": "agent_space_native_local",
    "model_api": "managed_model_api",
    "ts_agent_host": "managed_model_api",
    "claude_code": "local_claude_code_cli",
    "codex_cli": "local_codex_cli",
    "opencode": "local_opencode",
}

# Maps execution plane type to the externality_level value stored on Run.
_PLANE_TYPE_TO_EXTERNALITY: dict[str, str] = {
    "native": "native",
    "local": "local_external",
    "remote_vendor": "remote_external",
    "hybrid": "hybrid",
    "manual": "manual",
}


class ExecutionPlaneService:
    def __init__(self, db: Session):
        self.db = db

    def list_execution_planes(self, space_id: str) -> list[ExecutionPlane]:
        return (
            self.db.query(ExecutionPlane)
            .filter(ExecutionPlane.space_id == space_id)
            .order_by(ExecutionPlane.name)
            .all()
        )

    def get_execution_plane(
        self, execution_plane_id: str, space_id: str
    ) -> ExecutionPlane | None:
        return (
            self.db.query(ExecutionPlane)
            .filter(
                ExecutionPlane.id == execution_plane_id,
                ExecutionPlane.space_id == space_id,
            )
            .first()
        )

    def get_default_execution_plane(
        self, space_id: str, adapter_type: str
    ) -> ExecutionPlane | None:
        """Return the seeded, enabled execution plane for adapter_type.

        Returns None when adapter_type has no registered mapping, the plane has
        not yet been seeded for this space, or the plane is disabled.
        """
        plane_name = _ADAPTER_TO_PLANE.get(adapter_type)
        if not plane_name:
            return None
        return (
            self.db.query(ExecutionPlane)
            .filter(
                ExecutionPlane.space_id == space_id,
                ExecutionPlane.name == plane_name,
                ExecutionPlane.enabled == True,  # noqa: E712
            )
            .first()
        )

    def externality_level_for_plane(self, plane: ExecutionPlane) -> str:
        """Derive the Run.externality_level value from a plane's type."""
        return _PLANE_TYPE_TO_EXTERNALITY.get(plane.type, "local_external")
