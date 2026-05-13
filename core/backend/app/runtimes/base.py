"""Structured runtime adapter interface.

Adapters return ``RuntimeAdapterResult`` only — execution services map this
onto ``Run`` rows, artifacts, and jobs without exposing adapter-specific types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class RuntimeExecutionContext:
    """Narrow inputs passed into a runtime adapter execute call."""

    run_id: str
    space_id: str
    prompt: str
    mode: str
    sandbox_cwd: str | None
    model_name: str | None
    system_prompt: str | None
    adapter_config: dict[str, Any]
    simulate_failure: bool = False


@dataclass
class RuntimeAdapterResult:
    """Normalized adapter output — internal to the runtime layer."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    output_text: str = ""
    output_json: dict[str, Any] | None = None
    exit_code: int | None = None
    error_text: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    produced_artifact_paths: list[str] = field(default_factory=list)
    adapter_metadata: dict[str, Any] | None = None
    adapter_log_json: dict[str, Any] | None = None


class BaseRuntimeAdapter(ABC):
    """Minimal runtime adapter — one ``execute`` entrypoint."""

    adapter_type: str

    @abstractmethod
    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        """Run the adapter; must not mutate ORM rows directly."""
