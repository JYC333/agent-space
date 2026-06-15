"""Tests for the runtimes -> runs cycle inversion.

``app.runtimes`` is a lower-level execution package that emits run evidence and
registers subprocess handles only through the ``app.runtimes.ports`` protocols.
``app.runs.runtime_bridge`` owns the production implementations and
``app.runs.execution`` injects them via ``RuntimeExecutionContext``.

Covers:
- runtime ports import without pulling app.runs
- LocalExecutor registers/deregisters strictly through the injected port
  (completion, timeout, and failure paths)
- GenericCliRuntimeAdapter emits the context-render event through the sink
  exactly once, and tolerates a missing or raising sink
- RunEventRuntimeSink writes the same RunEvent row shape as a direct
  safe_append_run_event call, and preserves the existing drop semantics for
  the (still unregistered) ``runtime_context_rendered`` event type
- RunProcessRegistryAdapter delegates to app.runs.process_registry
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

from app.models import RunEvent
from app.runtimes.base import RuntimeExecutionContext
from app.runtimes.local_executor import ExecutionResult, LocalExecutor
from app.runtimes.ports import RuntimeEvent, RuntimeEventSink, RuntimeProcessRegistry
from app.runtimes.specs import (
    ContextSpec,
    ExecutableSpec,
    InvocationSpec,
    LimitsSpec,
    RuntimeAdapterSpec,
)
from tests.support import factories


BACKEND_ROOT = Path(__file__).resolve().parents[2]

SPACE = "space-rtport-01"
USER = "user-rtport-01"


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class RaisingSink:
    def __init__(self) -> None:
        self.attempts = 0

    def emit(self, event: RuntimeEvent) -> None:
        self.attempts += 1
        raise RuntimeError("sink exploded")


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def register(self, run_id: str, pid: int) -> None:
        self.calls.append(("register", run_id, pid))

    def deregister(self, run_id: str) -> None:
        self.calls.append(("deregister", run_id))


class RaisingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def register(self, run_id: str, pid: int) -> None:
        self.calls.append(("register", run_id, pid))
        raise RuntimeError("register exploded")

    def deregister(self, run_id: str) -> None:
        self.calls.append(("deregister", run_id))
        raise RuntimeError("deregister exploded")


def _spec(**context_overrides) -> RuntimeAdapterSpec:
    return RuntimeAdapterSpec(
        adapter_type="test_local_cli",
        display_name="Test Local CLI",
        runtime_kind="local_cli",
        implementation_status="implemented",
        executable=ExecutableSpec(command="test-cli"),
        invocation=InvocationSpec(
            headless_command_template=["{executable}", "run", "{prompt}"],
            argument_rendering_strategy="argv_template",
        ),
        limits=LimitsSpec(default_timeout_seconds=30, max_timeout_seconds=60),
        context=ContextSpec(**context_overrides) if context_overrides else ContextSpec(),
    )


def _ctx(**overrides) -> RuntimeExecutionContext:
    data = {
        "run_id": "run-port-001",
        "space_id": "space-port",
        "prompt": "do the thing",
        "mode": "normal",
        "sandbox_cwd": "/tmp/sandbox",
        "model_name": None,
        "system_prompt": None,
        "adapter_config": {},
        "resolved_credentials": {},
        "context_package": {},
    }
    data.update(overrides)
    return RuntimeExecutionContext(**data)


class RecordingExecutor:
    def __init__(self, result: ExecutionResult | None = None):
        self.calls: list[dict] = []
        self.result = result or ExecutionResult(0, "done", "")

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


# ---------------------------------------------------------------------------
# Port import hygiene
# ---------------------------------------------------------------------------


def test_runtime_ports_and_package_import_without_runs(tmp_path):
    """Importing the ports module and the full runtimes package must not load
    any app.runs module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    env["AGENT_SPACE_HOME"] = str(tmp_path / "agent-space-home")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(
            """
            import sys

            import app.runtimes.ports
            assert not any(m.startswith("app.runs") for m in sys.modules)

            import app.runtimes
            import app.runtimes.local_executor
            import app.runtimes.registry
            import app.runtimes.adapters.cli_runtime
            loaded = [m for m in sys.modules if m.startswith("app.runs")]
            assert not loaded, loaded
            """
        )],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_runtime_ports_are_structural_protocols():
    from app.runs.runtime_bridge import RunEventRuntimeSink, RunProcessRegistryAdapter

    assert isinstance(RecordingSink(), RuntimeEventSink)
    assert isinstance(RecordingRegistry(), RuntimeProcessRegistry)
    assert isinstance(RunProcessRegistryAdapter(), RuntimeProcessRegistry)
    assert isinstance(
        RunEventRuntimeSink.__new__(RunEventRuntimeSink), RuntimeEventSink
    )


# ---------------------------------------------------------------------------
# LocalExecutor process registration through the port
# ---------------------------------------------------------------------------


class TestLocalExecutorPort:
    def test_registers_then_deregisters_on_completion(self):
        registry = RecordingRegistry()
        result = LocalExecutor().run_command(
            command=["echo", "hello"],
            timeout=10,
            run_id="run-lifecycle",
            process_registry=registry,
        )
        assert result.returncode == 0
        assert [c[0] for c in registry.calls] == ["register", "deregister"]
        assert registry.calls[0][1] == "run-lifecycle"
        assert isinstance(registry.calls[0][2], int) and registry.calls[0][2] > 0
        assert registry.calls[1] == ("deregister", "run-lifecycle")

    def test_deregisters_on_timeout(self):
        registry = RecordingRegistry()
        result = LocalExecutor().run_command(
            command=["sleep", "5"],
            timeout=1,
            run_id="run-timeout",
            process_registry=registry,
        )
        assert result.timed_out is True
        assert result.returncode == -1
        assert registry.calls[0][0] == "register"
        assert registry.calls[-1] == ("deregister", "run-timeout")

    def test_deregisters_on_spawn_failure(self):
        registry = RecordingRegistry()
        result = LocalExecutor().run_command(
            command=["/nonexistent-binary-for-port-test"],
            timeout=5,
            run_id="run-spawn-fail",
            process_registry=registry,
        )
        assert result.returncode == -1
        # Popen failed before register; the failure path still issues the
        # best-effort deregister (idempotent), exactly as before the inversion.
        assert registry.calls == [("deregister", "run-spawn-fail")]

    def test_no_run_id_means_no_registry_interaction(self):
        registry = RecordingRegistry()
        LocalExecutor().run_command(
            command=["echo", "x"], timeout=5, process_registry=registry
        )
        assert registry.calls == []

    def test_no_registry_means_untracked_execution(self):
        result = LocalExecutor().run_command(
            command=["echo", "x"], timeout=5, run_id="run-no-registry"
        )
        assert result.returncode == 0

    def test_registry_failures_do_not_fail_or_skip_execution(self):
        registry = RaisingRegistry()
        result = LocalExecutor().run_command(
            command=["echo", "still-runs"],
            timeout=5,
            run_id="run-registry-raises",
            process_registry=registry,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "still-runs"
        assert [c[0] for c in registry.calls] == ["register", "deregister"]


# ---------------------------------------------------------------------------
# GenericCliRuntimeAdapter emission through RuntimeEventSink
# ---------------------------------------------------------------------------


class TestCliAdapterEventSink:
    def _adapter(self):
        from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

        adapter = GenericCliRuntimeAdapter(
            _spec(
                writes_vendor_context_file=True,
                context_file_type="CLAUDE.md",
                context_target_format="claude",
            ),
            executor=RecordingExecutor(),
        )
        # Bypass real ContextCompiler rendering; emission path stays real.
        adapter._render_context = lambda ctx: SimpleNamespace(
            instruction_file_path="/tmp/sandbox/CLAUDE.md"
        )
        return adapter

    def test_emits_context_render_event_exactly_once(self):
        sink = RecordingSink()
        result = self._adapter().execute(
            _ctx(
                event_sink=sink,
                workspace_id="workspace-1",
                adapter_config={"context_snapshot_id": "snap-1"},
            )
        )
        assert result.success is True
        assert len(sink.events) == 1
        event = sink.events[0]
        assert event.event_type == "runtime_context_rendered"
        assert event.status == "succeeded"
        assert event.workspace_id == "workspace-1"
        assert event.log_context == "runtime_context_rendered"
        assert event.metadata == {
            "context_snapshot_id": "snap-1",
            "adapter_type": "test_local_cli",
            "context_file_type": "CLAUDE.md",
            "context_target_format": "claude",
            "rendered_in_sandbox": True,
            "instruction_file_path": "/tmp/sandbox/CLAUDE.md",
        }

    def test_no_sink_means_no_emission_and_no_failure(self):
        result = self._adapter().execute(_ctx(event_sink=None))
        assert result.success is True

    def test_raising_sink_does_not_fail_the_run(self):
        sink = RaisingSink()
        result = self._adapter().execute(_ctx(event_sink=sink))
        assert sink.attempts == 1
        assert result.success is True

    def test_adapter_without_vendor_context_file_never_emits(self):
        from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

        sink = RecordingSink()
        adapter = GenericCliRuntimeAdapter(_spec(), executor=RecordingExecutor())
        result = adapter.execute(_ctx(event_sink=sink))
        assert result.success is True
        assert sink.events == []


# ---------------------------------------------------------------------------
# Runs-side bridge fidelity (DB)
# ---------------------------------------------------------------------------


def _setup_run(db):
    factories.create_test_space(db, space_id=SPACE)
    factories.create_test_user(db, space_id=SPACE, user_id=USER)
    run = factories.create_test_run(db, space_id=SPACE, user_id=USER)
    db.commit()
    return run


class TestRunEventRuntimeSinkBridge:
    def test_bridge_writes_same_run_event_shape_as_direct_append(self, db):
        from app.runs.events import safe_append_run_event
        from app.runs.runtime_bridge import RunEventRuntimeSink

        run = _setup_run(db)
        metadata = {"adapter_type": "test_local_cli", "rendered_in_sandbox": True}

        direct = safe_append_run_event(
            db,
            run_id=run.id,
            space_id=SPACE,
            event_type="adapter_invoked",
            status="running",
            summary="invoked",
            workspace_id=None,
            metadata_json=dict(metadata),
            log_context="adapter_invoked",
        )
        assert direct is not None

        RunEventRuntimeSink(db, run_id=run.id, space_id=SPACE).emit(
            RuntimeEvent(
                event_type="adapter_invoked",
                status="running",
                summary="invoked",
                metadata=dict(metadata),
            )
        )

        rows = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.space_id == SPACE)
            .order_by(RunEvent.event_index)
            .all()
        )
        assert len(rows) == 2
        first, second = rows
        assert second.event_index == first.event_index + 1
        for column in (
            "space_id", "run_id", "step_id", "actor_id", "event_type", "status",
            "summary", "error_code", "error_message", "workspace_id",
            "artifact_id", "proposal_id", "data_exposure_level",
            "trust_level", "metadata_json",
        ):
            assert getattr(second, column) == getattr(first, column), column

    def test_bridge_maps_error_fields(self, db):
        from app.runs.runtime_bridge import RunEventRuntimeSink

        run = _setup_run(db)
        RunEventRuntimeSink(db, run_id=run.id, space_id=SPACE).emit(
            RuntimeEvent(
                event_type="adapter_completed",
                status="failed",
                error_code="cli_adapter_failed",
                error_message="boom",
                workspace_id=None,
            )
        )
        row = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event_type == "adapter_completed")
            .one()
        )
        assert row.status == "failed"
        assert row.error_code == "cli_adapter_failed"
        assert row.error_message == "boom"

    def test_bridge_maps_workspace_id(self, db):
        from app.runs.runtime_bridge import RunEventRuntimeSink

        run = _setup_run(db)
        workspace = factories.create_test_workspace(
            db,
            space_id=SPACE,
            created_by_user_id=USER,
        )

        RunEventRuntimeSink(db, run_id=run.id, space_id=SPACE).emit(
            RuntimeEvent(
                event_type="adapter_invoked",
                status="running",
                workspace_id=workspace.id,
            )
        )

        row = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.event_type == "adapter_invoked")
            .one()
        )
        assert row.workspace_id == workspace.id

    def test_unregistered_runtime_context_rendered_type_is_still_dropped(self, db):
        """Pre-existing semantics preserved: ``runtime_context_rendered`` is not
        in RUN_EVENT_TYPES, so the best-effort append drops it (no row, no
        raise). The inversion must not silently start persisting it."""
        from app.runs.events import RUN_EVENT_TYPES
        from app.runs.runtime_bridge import RunEventRuntimeSink

        assert "runtime_context_rendered" not in RUN_EVENT_TYPES

        run = _setup_run(db)
        RunEventRuntimeSink(db, run_id=run.id, space_id=SPACE).emit(
            RuntimeEvent(event_type="runtime_context_rendered", status="succeeded")
        )
        count = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id, RunEvent.space_id == SPACE)
            .count()
        )
        assert count == 0

    def test_bridge_never_raises_into_the_adapter(self, db):
        from app.runs.runtime_bridge import RunEventRuntimeSink

        run = _setup_run(db)
        # Invalid status would raise ValueError in RunEventService.append_event;
        # safe_append_run_event swallows it (best-effort contract of the port).
        RunEventRuntimeSink(db, run_id=run.id, space_id=SPACE).emit(
            RuntimeEvent(event_type="adapter_invoked", status="not-a-status")
        )


class TestRunProcessRegistryAdapter:
    def test_delegates_to_runs_process_registry(self):
        from app.runs.process_registry import get_pid
        from app.runs.runtime_bridge import RunProcessRegistryAdapter

        bridge = RunProcessRegistryAdapter()
        run_id = "run-bridge-registry-001"
        try:
            bridge.register(run_id, 4242)
            assert get_pid(run_id) == 4242
        finally:
            bridge.deregister(run_id)
        assert get_pid(run_id) is None
