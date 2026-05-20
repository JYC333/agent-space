"""Structured runtime adapter interface — M4 canonical runtime adapter contract.

Canonical location: ``core/backend/app/runtimes/``

New runtime adapters must be added here, not under ``app.agents``.
See ``app.runtimes.registry`` for adapter registration.
See ``app.runtimes.credentials`` for credential resolution.

Adapters return ``RuntimeAdapterResult`` only — execution services map this
onto ``Run`` rows, artifacts, and jobs without exposing adapter-specific types.

Credential rule (M4):
  Adapters must read API keys from ``ctx.resolved_credentials``, not from
  ``ctx.adapter_config`` raw fields or environment variables.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


@dataclass
class RuntimeExecutionContext:
    """Narrow inputs passed into a runtime adapter execute call.

    Credential rule: adapters must read API keys from ``resolved_credentials``,
    not from ``adapter_config`` raw fields or environment variables.
    ``adapter_config`` is pre-sanitized (secret fields stripped) before being
    passed to the adapter — it is safe for logging.
    """

    run_id: str
    space_id: str
    prompt: str
    mode: str
    sandbox_cwd: str | None
    model_name: str | None
    system_prompt: str | None
    adapter_config: dict[str, Any]
    instruction: str | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    capability_id: str | None = None
    simulate_failure: bool = False
    # Pre-resolved credentials — set by execution service via runtimes.credentials.
    # Adapters read api_key from here; never from adapter_config or env vars.
    resolved_credentials: dict[str, Any] = field(default_factory=dict)


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
    produced_artifact_paths: list[Any] = field(default_factory=list)
    adapter_metadata: dict[str, Any] | None = None
    adapter_log_json: dict[str, Any] | None = None


class BaseRuntimeAdapter(ABC):
    """Canonical runtime adapter base class.

    New adapters must subclass this and register in ``app.runtimes.registry``.
    Do not add new product runtime adapters under ``app.agents``.

    Subclasses declare their credential and file-access requirements via class
    attributes so the registry and execution service can enforce policy before
    the adapter is invoked.

    Credential rule: ``execute`` must read credentials from
    ``ctx.resolved_credentials``, not from ``ctx.adapter_config`` raw fields
    or environment variables.
    """

    adapter_type: str

    # Declare whether this adapter needs API credentials (resolved by execution
    # service via runtimes.credentials before calling execute).
    requires_credentials: bool = False

    # Declare whether this adapter reads or writes files in the sandbox workdir.
    requires_file_access: bool = False

    # Declare whether this adapter supports sandboxed execution (worktree isolation).
    supports_sandboxed_execution: bool = False

    # Model config consumption metadata (used by Run API resolved_model summary).
    uses_model_config: bool = False
    model_config_behavior: Literal[
        "uses_model", "not_applicable", "unsupported"
    ] = "not_applicable"
    model_config_note: str = ""

    @abstractmethod
    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        """Run the adapter; must not mutate ORM rows directly.

        Read credentials from ``ctx.resolved_credentials["api_key"]``.
        Read non-secret config (model, max_tokens, etc.) from ``ctx.adapter_config``.
        """
