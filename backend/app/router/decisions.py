from __future__ import annotations

"""Canonical routing decision types.

The router package owns intent parsing, task capability classification, and
runtime adapter selection decisions. Caller-specific services may still enforce
their own policy gates, but they should consume these types instead of
reconstructing routing state locally.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

_HEAVY_TASK_TYPES: frozenset[str] = frozenset({
    "code_modify",
    "structure_change",
    "test_fix",
    "migration",
    "repo_analysis",
    "dependency_debug",
    "patch",
    "debug",
    "build",
})


class AdapterResolutionError(Exception):
    """Adapter routing failure with a stable machine-readable error code."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass
class TaskClassification:
    task_type: str = "generic"
    risk_level: str = "medium"
    requires_filesystem: bool = False
    requires_terminal: bool = False
    requires_git: bool = False
    requires_long_reasoning: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_cli(self) -> bool:
        if self.requires_filesystem or self.requires_terminal or self.requires_git:
            return True
        if self.requires_long_reasoning:
            return True
        if self.task_type in _HEAVY_TASK_TYPES:
            return True
        return False


@dataclass(frozen=True)
class TaskRouteDecision:
    requested_adapter: str
    adapter_type: str
    classification: TaskClassification
    needs_cli: bool


@dataclass
class RoutingDecision:
    agent_id: Optional[str] = None
    capability_id: Optional[str] = None
    workspace_id: Optional[str] = None
    space_id: Optional[str] = None
    action: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedRuntimeAdapter:
    adapter_type: str | None
    merged_config: dict[str, Any]


@dataclass(frozen=True)
class AdapterDecision:
    adapter_type: str | None
    merged_config: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None

    @property
    def error(self) -> str | None:
        if not self.error_code:
            return None
        if self.message:
            return f"{self.error_code}: {self.message}"
        return self.error_code
