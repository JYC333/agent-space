from __future__ import annotations
"""RuntimeToolBindingService — read path for explicitly authorized external tools.

RuntimeToolBinding records which external tools (MCP servers, plugins, skills)
are explicitly authorised for a given scope (space, workspace, agent, adapter type).
This service is read-only: bindings are created administratively, not by agents.

The list path is used by routing and context generation to make allowed external
tools visible before a run is dispatched.
"""

import logging
from sqlalchemy.orm import Session

from ..models import RuntimeToolBinding

log = logging.getLogger(__name__)


class RuntimeToolBindingService:
    def __init__(self, db: Session):
        self.db = db

    def list_runtime_tool_bindings(
        self,
        space_id: str,
        *,
        workspace_id: str | None = None,
        agent_id: str | None = None,
        runtime_adapter_type: str | None = None,
        enabled_only: bool = True,
    ) -> list[RuntimeToolBinding]:
        """Return bindings visible for the given scope combination.

        All parameters are optional filters; only space_id is required.
        When enabled_only=True (default), only enabled=True bindings are returned.
        """
        q = self.db.query(RuntimeToolBinding).filter(
            RuntimeToolBinding.space_id == space_id
        )
        if workspace_id is not None:
            q = q.filter(RuntimeToolBinding.workspace_id == workspace_id)
        if agent_id is not None:
            q = q.filter(RuntimeToolBinding.agent_id == agent_id)
        if runtime_adapter_type is not None:
            q = q.filter(RuntimeToolBinding.runtime_adapter_type == runtime_adapter_type)
        if enabled_only:
            q = q.filter(RuntimeToolBinding.enabled == True)  # noqa: E712
        return q.order_by(RuntimeToolBinding.created_at).all()

    def get_runtime_tool_binding(
        self,
        binding_id: str,
        space_id: str,
    ) -> RuntimeToolBinding | None:
        return (
            self.db.query(RuntimeToolBinding)
            .filter(
                RuntimeToolBinding.id == binding_id,
                RuntimeToolBinding.space_id == space_id,
            )
            .first()
        )
