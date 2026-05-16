"""Canonical return types for the run execution service.

``RuntimeExecutionResult`` was previously defined in ``app.agents.base``.
It is now defined here so that ``app.runs.execution`` has no dependency on
the legacy ``app.agents`` stack.  ``app.agents.base`` re-exports it for
backward compatibility with existing CLI adapter code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RuntimeExecutionResult:
    """Result returned by RunExecutionService after a run completes.

    This is the execution service output — NOT a Run ORM row.
    Named RuntimeExecutionResult to distinguish from the Run/Activity/Artifact
    product models.
    """

    success: bool
    output: str
    error: str | None = None
    exit_code: int | None = None
    artifacts: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stdout: str | None = None
    stderr: str | None = None
    error_code: str | None = None
    adapter_log_json: dict | None = None
