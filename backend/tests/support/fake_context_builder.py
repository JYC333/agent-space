"""Minimal fake satisfying ``app.memory.ContextBuilderPort`` (no database).

The real :class:`app.memory.context_builder.ContextBuilder` requires a DB session
and the full memory-retrieval pipeline. This fake lets a caller that depends only
on the :class:`~app.memory.ports.ContextBuilderPort` seam be exercised without
any of that — it records the ``build`` keyword arguments it was called with and
returns a scripted (or empty) ``ContextPackage``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas import ContextPackage


@dataclass
class FakeContextBuilder:
    """Records ``build`` calls and returns a scripted ``ContextPackage``."""

    package: ContextPackage | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def build(
        self,
        space_id: str,
        user_id: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        task_type: str | None = None,
        capability_id: str | None = None,
        session_id: str | None = None,
        query: str | None = None,
        agent_memory_policy: dict | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        context_reason: str | None = None,
        attachments: list[dict] | None = None,
        workspace_path: str | None = None,
    ) -> ContextPackage:
        if not space_id:
            raise ValueError("space_id is required — context builder is a space boundary")
        if not user_id:
            raise ValueError("user_id is required — context builder requires an explicit user")
        self.calls.append(
            {
                "space_id": space_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "session_id": session_id,
                "query": query,
                "agent_id": agent_id,
                "run_id": run_id,
            }
        )
        if self.package is not None:
            return self.package
        return ContextPackage(attachments=list(attachments or []))
