"""Unit tests for the spec-driven generic local CLI runtime."""

from __future__ import annotations

from app.runtimes.base import RuntimeExecutionContext
from app.runtimes.local_executor import ExecutionResult
from app.runtimes.specs import (
    ExecutableSpec,
    InvocationSpec,
    LimitsSpec,
    RuntimeAdapterSpec,
)


def _spec() -> RuntimeAdapterSpec:
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
    )


def _ctx(**overrides) -> RuntimeExecutionContext:
    data = {
        "run_id": "run-test-001",
        "space_id": "space-test",
        "prompt": "Do the task; rm -rf /",
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


def test_registry_instantiates_cli_specs_through_generic_runtime():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.registry import instantiate_runtime_adapter

    assert isinstance(instantiate_runtime_adapter("claude_code"), GenericCliRuntimeAdapter)
    assert isinstance(instantiate_runtime_adapter("codex_cli"), GenericCliRuntimeAdapter)


def test_generic_cli_runtime_passes_prompt_as_single_argv_item():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

    executor = RecordingExecutor()
    result = GenericCliRuntimeAdapter(_spec(), executor=executor).execute(_ctx())

    assert result.success is True
    assert executor.calls[0]["command"] == ["test-cli", "run", "Do the task; rm -rf /"]
    assert executor.calls[0]["stdin"] is None
    assert result.adapter_log_json["command"] == ["test-cli", "run", "[REDACTED_PROMPT]"]


def test_generic_cli_runtime_classifies_nonzero_result():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

    executor = RecordingExecutor(ExecutionResult(2, "partial", "permission denied"))
    result = GenericCliRuntimeAdapter(_spec(), executor=executor).execute(_ctx())

    assert result.success is False
    assert result.error_code == "cli_adapter_nonzero_exit"
    assert result.produced_artifact_paths == []


def test_generic_cli_runtime_classifies_timeout():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

    executor = RecordingExecutor(ExecutionResult(-1, "partial", "slow", timed_out=True))
    result = GenericCliRuntimeAdapter(_spec(), executor=executor).execute(_ctx())

    assert result.success is False
    assert result.error_code == "cli_adapter_timeout"


def test_generic_cli_runtime_forwards_run_id_and_process_registry_port():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter

    class FakeRegistry:
        def register(self, run_id: str, pid: int) -> None:
            pass

        def deregister(self, run_id: str) -> None:
            pass

    registry = FakeRegistry()
    executor = RecordingExecutor()
    GenericCliRuntimeAdapter(_spec(), executor=executor).execute(
        _ctx(run_id="run-123", process_registry=registry)
    )

    assert executor.calls[0]["run_id"] == "run-123"
    assert executor.calls[0]["process_registry"] is registry


def test_generic_cli_runtime_permission_bypass_metadata():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.specs import CredentialsSpec, get_runtime_adapter_spec

    spec = get_runtime_adapter_spec("claude_code").model_copy(
        update={"credentials": CredentialsSpec(credential_mode="none")},
        deep=True,
    )
    denied = GenericCliRuntimeAdapter(spec, executor=RecordingExecutor()).execute(
        _ctx(adapter_config={"permission_bypass": True})
    )
    assert denied.adapter_metadata["permission_bypass_requested"] is True
    assert denied.adapter_metadata["permission_bypass_allowed"] is False
    assert denied.adapter_metadata["permission_bypass_used"] is False

    executor = RecordingExecutor()
    allowed = GenericCliRuntimeAdapter(spec, executor=executor).execute(
        _ctx(
            adapter_config={
                "permission_bypass": True,
                "runtime_policy_json": {"allow_permission_bypass": True},
            },
            risk_level="high",
            executor_mode="worktree",
            workspace_id="workspace",
        )
    )
    assert "--dangerously-skip-permissions" in executor.calls[0]["command"]
    assert allowed.adapter_metadata["permission_bypass_requested"] is True
    assert allowed.adapter_metadata["permission_bypass_allowed"] is True
    assert allowed.adapter_metadata["permission_bypass_used"] is True
    assert "--dangerously-skip-permissions" in allowed.adapter_log_json["command"]

    executor = RecordingExecutor()
    normal = GenericCliRuntimeAdapter(spec, executor=executor).execute(_ctx())
    assert "--dangerously-skip-permissions" not in executor.calls[0]["command"]
    assert normal.adapter_metadata["permission_bypass_requested"] is False
    assert normal.adapter_metadata["permission_bypass_used"] is False


def test_command_render_failure_marks_permission_bypass_unused():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.specs import CredentialsSpec, get_runtime_adapter_spec

    spec = get_runtime_adapter_spec("claude_code").model_copy(
        update={"credentials": CredentialsSpec(credential_mode="none")},
        deep=True,
    )
    result = GenericCliRuntimeAdapter(spec, executor=RecordingExecutor()).execute(
        _ctx(
            adapter_config={
                "permission_bypass": True,
                "runtime_policy_json": {"allow_permission_bypass": True},
                "executable_path": "relative-cli",
            },
            risk_level="high",
            executor_mode="worktree",
            workspace_id="workspace",
        )
    )

    assert result.success is False
    assert result.error_code == "executable_override_not_absolute"
    assert result.adapter_metadata["permission_bypass_requested"] is True
    assert result.adapter_metadata["permission_bypass_allowed"] is True
    assert result.adapter_metadata["permission_bypass_used"] is False


def test_generic_cli_runtime_fails_closed_without_credential_grant():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.specs import get_runtime_adapter_spec

    adapter = GenericCliRuntimeAdapter(get_runtime_adapter_spec("claude_code"), executor=RecordingExecutor())
    adapter._resolve_credential_grant = lambda ctx: None
    result = adapter.execute(_ctx(adapter_config={"credential_profile_id": "claude_code/default"}))

    assert result.success is False
    assert result.error_code == "runtime_credential_profile_required"
    assert result.adapter_metadata["credential_profile_id"] == "claude_code/default"
