from __future__ import annotations
"""ExecutionPlane service — read and resolution helpers.

ExecutionPlanes are system records seeded at install time. This service
provides read and resolution helpers; it does not own plane lifecycle.
"""

import logging
from sqlalchemy.orm import Session

from ..models import ExecutionPlane, RuntimeAdapter

log = logging.getLogger(__name__)

# Maps adapter_type short names to canonical execution plane names.
# Planes must be seeded by ExecutionPlaneSeeder before these lookups are useful.
#
# Policy note: ``anthropic_api`` and ``anthropic_messages`` are intentionally
# absent. Anthropic/Claude usage must go through CLI integrations
# (``claude_code``), not in-process Anthropic runtime types.
_ADAPTER_TO_PLANE: dict[str, str] = {
    "echo":        "agent_space_native_local",
    "capability":  "agent_space_native_local",
    "claude_code": "local_claude_code_cli",
    "codex_cli":   "local_codex_cli",
    "opencode":    "local_opencode",
}

# Maps execution plane type to the externality_level value stored on Run.
_PLANE_TYPE_TO_EXTERNALITY: dict[str, str] = {
    "native":        "native",
    "local":         "local_external",
    "remote_vendor": "remote_external",
    "hybrid":        "hybrid",
    "manual":        "manual",
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

    def get_execution_plane(self, execution_plane_id: str, space_id: str) -> ExecutionPlane | None:
        return (
            self.db.query(ExecutionPlane)
            .filter(
                ExecutionPlane.id == execution_plane_id,
                ExecutionPlane.space_id == space_id,
            )
            .first()
        )

    def get_default_execution_plane(self, space_id: str, adapter_type: str) -> ExecutionPlane | None:
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

    def resolve_execution_plane_for_runtime(
        self,
        runtime_adapter_id: str,
        space_id: str,
    ) -> ExecutionPlane | None:
        """Return the ExecutionPlane linked to a RuntimeAdapter row.

        Both the adapter and the resolved plane are scoped to space_id to prevent
        cross-space metadata leakage. Returns None when the adapter does not exist
        in this space or has no plane set.
        """
        adapter = (
            self.db.query(RuntimeAdapter)
            .filter(
                RuntimeAdapter.id == runtime_adapter_id,
                RuntimeAdapter.space_id == space_id,
            )
            .first()
        )
        if not adapter or not adapter.execution_plane_id:
            return None
        return (
            self.db.query(ExecutionPlane)
            .filter(
                ExecutionPlane.id == adapter.execution_plane_id,
                ExecutionPlane.space_id == space_id,
            )
            .first()
        )

    def externality_level_for_plane(self, plane: ExecutionPlane) -> str:
        """Derive the Run.externality_level value from a plane's type."""
        return _PLANE_TYPE_TO_EXTERNALITY.get(plane.type, "local_external")
