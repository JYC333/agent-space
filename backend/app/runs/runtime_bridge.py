"""Runs-owned implementations of the runtime ports.

This is the only place runtime-level events and process handles are mapped onto
runs-owned systems (``app.runs.events`` / ``app.runs.process_registry``).
``app.runs.execution`` injects these into runtime adapters via
``RuntimeExecutionContext``; ``runtimes`` itself never imports this module.
Dependency direction: ``runs -> runtimes.ports``, never ``runtimes -> runs``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..runtimes.ports import RuntimeEvent
from .events import safe_append_run_event
from . import process_registry


class RunEventRuntimeSink:
    """``RuntimeEventSink`` writing RunEvent rows for one run.

    Bound to a (db, run_id, space_id) triple by the composition root so
    runtime adapters emit event-local fields only. Delegates to
    ``safe_append_run_event`` — best-effort, validated against the run-event
    vocabulary, and never raises back into adapter execution.
    """

    def __init__(self, db: Session, *, run_id: str, space_id: str) -> None:
        self.db = db
        self.run_id = run_id
        self.space_id = space_id

    def emit(self, event: RuntimeEvent) -> None:
        safe_append_run_event(
            self.db,
            run_id=self.run_id,
            space_id=self.space_id,
            event_type=event.event_type,
            status=event.status,
            summary=event.summary,
            error_code=event.error_code,
            error_message=event.error_message,
            runtime_adapter_id=event.runtime_adapter_id,
            workspace_id=event.workspace_id,
            metadata_json=event.metadata,
            log_context=event.log_context or event.event_type,
        )


class RunProcessRegistryAdapter:
    """``RuntimeProcessRegistry`` delegating to the in-process run registry.

    Registration/deregistration only — termination stays runs-owned
    (``RunService.stop_run`` → ``process_registry.terminate``).
    """

    def register(self, run_id: str, pid: int) -> None:
        process_registry.register(run_id, pid)

    def deregister(self, run_id: str) -> None:
        process_registry.deregister(run_id)


__all__ = ["RunEventRuntimeSink", "RunProcessRegistryAdapter"]
