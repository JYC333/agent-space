"""Runtime-level ports — the only seam runtimes may emit run evidence through.

``runtimes`` is a lower-level execution package. It must not import ``app.runs``
(RunEvent persistence, process registry) or any ORM internals. Instead, the
execution layer that owns runs (``app.runs.execution``) injects implementations
of these ports — see ``app.runs.runtime_bridge`` — via
``RuntimeExecutionContext``. Dependency direction: ``runs -> runtimes``, never
``runtimes -> runs``.

These ports are intentionally narrow: they describe exactly what runtime
adapters and the local executor need today (best-effort evidence emission and
subprocess handle registration), not a general event bus or transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RuntimeEvent:
    """A runtime-level evidence event, decoupled from RunEvent ORM internals.

    ``event_type``/``status`` use the run-event vocabulary owned by
    ``app.runs.events`` (the sink validates them; invalid types are dropped
    best-effort, never raised back into the adapter). Run identity
    (``run_id``/``space_id``) is bound into the sink by the composition root,
    so events carry only event-local fields.
    """

    event_type: str
    status: str
    summary: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    runtime_adapter_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] | None = field(default=None)
    log_context: str = ""


@runtime_checkable
class RuntimeEventSink(Protocol):
    """Best-effort sink for runtime-emitted run evidence.

    Implementations must never raise back into adapter execution — a failed
    evidence write must not fail a run (same contract as
    ``app.runs.events.safe_append_run_event``, the production delegate).
    """

    def emit(self, event: RuntimeEvent) -> None:
        ...


@runtime_checkable
class RuntimeProcessRegistry(Protocol):
    """Subprocess handle registration for run cancellation.

    ``LocalExecutor`` registers the subprocess PID under its run id while the
    process is alive and deregisters it on exit (including timeout and failure
    paths). Termination is owned by the runs layer and is not part of this
    port — runtimes never cancel runs themselves. Registration is best-effort:
    a tracking failure must not fail or skip adapter execution.
    """

    def register(self, run_id: str, pid: int) -> None:
        ...

    def deregister(self, run_id: str) -> None:
        ...


__all__ = ["RuntimeEvent", "RuntimeEventSink", "RuntimeProcessRegistry"]
