"""Unit tests for the CLI runtime bridge (app.runtimes.adapters.cli_runtime).

Covers:
  1. Adapter type registration and class attributes
  2. RunExecutionService import isolation (no direct CLI adapter imports)
  3. _resolve_cli_adapter factory dispatch
  4. CliRuntimeAdapter.execute: CLI available, success path
  5. CliRuntimeAdapter.execute: CLI not available
  6. CliRuntimeAdapter.execute: CLI raises exception
  7. CliRuntimeAdapter.execute: unknown adapter_type
  8. context_package is forwarded from RuntimeExecutionContext to cli_adapter.run()
  9. credential grant is attempted and cleaned up
 10. codex_cli follows the same bridge
"""

from __future__ import annotations

import inspect
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest

from app.runtimes.base import RuntimeAdapterResult, RuntimeExecutionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(
    *,
    adapter_type: str = "claude_code",
    sandbox_cwd: str | None = "/tmp/sandbox",
    model_name: str | None = None,
    context_package: dict | None = None,
    adapter_config: dict | None = None,
) -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        run_id="run-test-001",
        space_id="space-test",
        prompt="Do the task.",
        mode="normal",
        sandbox_cwd=sandbox_cwd,
        model_name=model_name,
        system_prompt=None,
        adapter_config=adapter_config or {},
        resolved_credentials={},
        context_package=context_package or {"user_memory": [], "workspace_memory": []},
    )


def _fake_cli_result(
    *,
    success: bool = True,
    output: str = "done",
    error: str | None = None,
    exit_code: int = 0,
) -> MagicMock:
    from app.runs.types import RuntimeExecutionResult
    r = MagicMock(spec=RuntimeExecutionResult)
    r.success = success
    r.output = output
    r.error = error
    r.exit_code = exit_code
    r.started_at = datetime.now(UTC)
    r.completed_at = datetime.now(UTC)
    return r


def _mock_grant(temp_home: str | None = None) -> MagicMock:
    grant = MagicMock()
    grant.profile_id = "claude_code/default"
    grant.temp_home = temp_home
    return grant


# ===========================================================================
# 1. Registration and class attributes
# ===========================================================================

class TestCliRuntimeAdapterRegistration:
    def test_claude_code_is_in_canonical_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("claude_code")

    def test_codex_cli_is_in_canonical_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("codex_cli")

    def test_claude_code_instantiates_via_registry(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter
        adapter = instantiate_runtime_adapter("claude_code")
        assert isinstance(adapter, ClaudeCodeRuntimeAdapter)
        assert adapter.adapter_type == "claude_code"

    def test_codex_cli_instantiates_via_registry(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        from app.runtimes.adapters.cli_runtime import CodexCliRuntimeAdapter
        adapter = instantiate_runtime_adapter("codex_cli")
        assert isinstance(adapter, CodexCliRuntimeAdapter)
        assert adapter.adapter_type == "codex_cli"

    def test_bridge_adapters_have_correct_class_flags(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter
        adapter = ClaudeCodeRuntimeAdapter()
        assert adapter.requires_credentials is False
        assert adapter.requires_file_access is True
        assert adapter.supports_sandboxed_execution is True
        assert adapter.uses_model_config is False
        assert adapter.model_config_behavior == "not_applicable"

    def test_anthropic_direct_adapters_still_absent(self):
        """Guard: adding CLI bridge must not accidentally re-add direct Anthropic API adapters."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("anthropic_api")
        assert not is_adapter_type_implemented("anthropic_messages")


# ===========================================================================
# 2. Import isolation — RunExecutionService must not import CLI adapter classes
# ===========================================================================

class TestImportIsolation:
    def test_execution_service_does_not_import_claude_cli_adapter(self):
        import app.runs.execution as svc
        source = inspect.getsource(svc)
        assert "ClaudeCLIAdapter" not in source, (
            "RunExecutionService must not import ClaudeCLIAdapter — use the CLI runtime bridge"
        )

    def test_execution_service_does_not_import_codex_cli_adapter(self):
        import app.runs.execution as svc
        source = inspect.getsource(svc)
        assert "CodexCLIAdapter" not in source, (
            "RunExecutionService must not import CodexCLIAdapter — use the CLI runtime bridge"
        )

    def test_registry_does_not_import_claude_cli_adapter_directly(self):
        import app.runtimes.registry as reg
        source = inspect.getsource(reg)
        assert "ClaudeCLIAdapter" not in source
        assert "CodexCLIAdapter" not in source

    def test_cli_runtime_module_is_only_import_point(self):
        """app.runtimes.adapters.cli_runtime is the only module in app.runtimes that
        imports ClaudeCLIAdapter or CodexCLIAdapter."""
        import app.runtimes.adapters.cli_runtime as bridge
        source = inspect.getsource(bridge)
        assert "ClaudeCLIAdapter" in source
        assert "CodexCLIAdapter" in source


# ===========================================================================
# 3. _resolve_cli_adapter factory
# ===========================================================================

class TestResolveCLIAdapterFactory:
    def test_claude_code_returns_claude_cli_adapter(self):
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        from app.cli_adapters.claude import ClaudeCLIAdapter
        adapter = _resolve_cli_adapter(
            adapter_type="claude_code",
            sandbox_dir="/tmp/sb",
            credential_grant=None,
            model=None,
        )
        assert isinstance(adapter, ClaudeCLIAdapter)

    def test_claude_cli_adapter_type_raises_key_error(self):
        """claude_cli is not a canonical adapter type; _resolve_cli_adapter must raise KeyError."""
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        import pytest
        with pytest.raises(KeyError):
            _resolve_cli_adapter(
                adapter_type="claude_cli",
                sandbox_dir=None,
                credential_grant=None,
                model=None,
            )

    def test_codex_cli_returns_codex_cli_adapter(self):
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        from app.cli_adapters.codex import CodexCLIAdapter
        adapter = _resolve_cli_adapter(
            adapter_type="codex_cli",
            sandbox_dir=None,
            credential_grant=None,
            model=None,
        )
        assert isinstance(adapter, CodexCLIAdapter)

    def test_unknown_adapter_type_raises_key_error(self):
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        with pytest.raises(KeyError):
            _resolve_cli_adapter(
                adapter_type="totally_unknown",
                sandbox_dir=None,
                credential_grant=None,
                model=None,
            )

    def test_model_passed_to_claude_adapter(self):
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        adapter = _resolve_cli_adapter(
            adapter_type="claude_code",
            sandbox_dir=None,
            credential_grant=None,
            model="claude-opus-4-7",
        )
        assert adapter.model == "claude-opus-4-7"

    def test_sandbox_dir_passed_to_claude_adapter(self):
        from app.runtimes.adapters.cli_runtime import _resolve_cli_adapter
        adapter = _resolve_cli_adapter(
            adapter_type="claude_code",
            sandbox_dir="/sandbox/path",
            credential_grant=None,
            model=None,
        )
        assert adapter.sandbox_dir == "/sandbox/path"


# ===========================================================================
# 4. execute: success path
# ===========================================================================

class TestCliRuntimeAdapterExecuteSuccess:
    def test_execute_returns_success_result(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx(adapter_type="claude_code")

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result(success=True, output="Task complete.")

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        assert result.output_text == "Task complete."
        assert result.stdout == "Task complete."
        assert result.exit_code == 0
        assert result.error_code is None

    def test_execute_sets_adapter_metadata(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result(output="ok")

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.adapter_metadata is not None
        assert result.adapter_metadata["adapter_type"] == "claude_code"
        assert result.adapter_metadata["cli_bridge"] is True

    def test_execute_passes_context_package_to_cli_adapter(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx_pkg = {"user_memory": [{"title": "Pref", "content": "Python"}], "workspace_memory": []}
        ctx = _make_ctx(context_package=ctx_pkg)

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            adapter.execute(ctx)

        call_kwargs = mock_cli.run.call_args
        assert call_kwargs[1]["context"] == ctx_pkg or call_kwargs[0][1] == ctx_pkg

    def test_execute_passes_prompt_to_cli_adapter(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            adapter.execute(ctx)

        mock_cli.run.assert_called_once()
        call_kwargs = mock_cli.run.call_args[1]
        assert call_kwargs["prompt"] == "Do the task."

    def test_execute_passes_timeout_from_adapter_config(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx(adapter_config={"timeout": 600})

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            adapter.execute(ctx)

        call_kwargs = mock_cli.run.call_args[1]
        assert call_kwargs["timeout"] == 600


# ===========================================================================
# 5. execute: CLI not available
# ===========================================================================

class TestCliRuntimeAdapterNotAvailable:
    def test_returns_not_available_error(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = False

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "cli_adapter_not_available"
        assert "claude_code" in result.error_text
        mock_cli.run.assert_not_called()


# ===========================================================================
# 6. execute: CLI raises an exception
# ===========================================================================

class TestCliRuntimeAdapterException:
    def test_returns_exception_error_code(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.side_effect = RuntimeError("subprocess died unexpectedly")

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "cli_adapter_exception"
        assert "subprocess died" in result.error_text


# ===========================================================================
# 7. execute: unknown adapter_type (no factory entry)
# ===========================================================================

class TestCliRuntimeAdapterUnknownType:
    def test_returns_not_registered_error(self):
        from app.runtimes.adapters.cli_runtime import CliRuntimeAdapter

        # Manually create an instance with a bogus adapter_type
        adapter = CliRuntimeAdapter.__new__(CliRuntimeAdapter)
        adapter.adapter_type = "unknown_cli_type"
        ctx = _make_ctx()

        with patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "cli_adapter_not_registered"
        assert "unknown_cli_type" in result.error_text


# ===========================================================================
# 8. execute: failed CLI run (non-zero exit)
# ===========================================================================

class TestCliRuntimeAdapterFailure:
    def test_returns_failed_result_on_nonzero_exit(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result(
            success=False,
            output="",
            error="command failed with code 1",
            exit_code=1,
        )

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "cli_adapter_failed"
        assert result.exit_code == 1
        assert "command failed" in (result.stderr or "")


# ===========================================================================
# 9. Credential grant lifecycle
# ===========================================================================

class TestCredentialGrantLifecycle:
    def test_credential_grant_failure_aborts_before_execution(self):
        """If CredentialBroker.grant_for_run raises, execution fails before CLI invocation."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(
                adapter,
                "_resolve_credential_grant",
                side_effect=Exception("broker unavailable"),
            ),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        assert result.adapter_metadata["fallback_reason"] == "broker_error"
        mock_cli.run.assert_not_called()

    def test_cleanup_temp_home_called_when_grant_has_temp_home(self):
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_grant = MagicMock()
        mock_grant.temp_home = "/tmp/run-001-home"

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        mock_broker_instance = MagicMock()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            # Patch at the module where CredentialBroker is imported in the finally block
            patch("app.credentials.broker.CredentialBroker", return_value=mock_broker_instance),
        ):
            adapter.execute(ctx)

        mock_broker_instance.cleanup_temp_home.assert_called_once_with("run-test-001")

    def test_cleanup_skipped_when_grant_has_no_temp_home(self):
        """No cleanup call when grant.temp_home is None (docker mode grants)."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_grant = MagicMock()
        mock_grant.temp_home = None

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        mock_broker_instance = MagicMock()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch("app.credentials.broker.CredentialBroker", return_value=mock_broker_instance),
        ):
            adapter.execute(ctx)

        mock_broker_instance.cleanup_temp_home.assert_not_called()


# ===========================================================================
# 10. codex_cli follows the same bridge
# ===========================================================================

class TestCodexCliRuntimeAdapter:
    def test_codex_cli_execute_success(self):
        from app.runtimes.adapters.cli_runtime import CodexCliRuntimeAdapter

        adapter = CodexCliRuntimeAdapter()
        ctx = _make_ctx(adapter_type="codex_cli")

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result(output="codex output")

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        assert result.output_text == "codex output"
        assert result.adapter_metadata["adapter_type"] == "codex_cli"

    def test_codex_cli_not_available_returns_correct_error(self):
        from app.runtimes.adapters.cli_runtime import CodexCliRuntimeAdapter

        adapter = CodexCliRuntimeAdapter()
        ctx = _make_ctx(adapter_type="codex_cli")

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = False

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=_mock_grant()),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert "codex_cli" in result.error_text


# ===========================================================================
# 11. context_package in RuntimeExecutionContext
# ===========================================================================

class TestContextPackageField:
    def test_context_package_defaults_to_empty_dict(self):
        ctx = RuntimeExecutionContext(
            run_id="r1",
            space_id="s1",
            prompt="p",
            mode="normal",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
        )
        assert ctx.context_package == {}

    def test_context_package_can_be_set(self):
        pkg = {"user_memory": [{"id": "m1", "content": "pref"}]}
        ctx = RuntimeExecutionContext(
            run_id="r1",
            space_id="s1",
            prompt="p",
            mode="normal",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
            context_package=pkg,
        )
        assert ctx.context_package == pkg


# ===========================================================================
# 12. Credential risk/executor_mode propagation (Task 5)
# ===========================================================================

class TestCredentialRiskPropagation:
    def test_resolve_credential_grant_uses_ctx_risk_level(self):
        """_resolve_credential_grant must pass ctx.risk_level to CredentialBroker."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = RuntimeExecutionContext(
            run_id="run-risk-001",
            space_id="sp-a",
            prompt="do something",
            mode="normal",
            sandbox_cwd="/tmp/sandbox",
            model_name=None,
            system_prompt=None,
            adapter_config={},
            risk_level="high",
            executor_mode="worktree",
        )

        mock_broker_instance = MagicMock()
        mock_broker_instance.grant_for_run.return_value = _mock_grant()

        with patch("app.credentials.broker.CredentialBroker", return_value=mock_broker_instance):
            adapter._resolve_credential_grant(ctx)

        mock_broker_instance.grant_for_run.assert_called_once_with(
            run_id="run-risk-001",
            runtime="claude_code",
            risk_level="high",
            executor_mode="worktree",
        )

    def test_high_risk_worktree_run_passes_high_risk_to_broker(self):
        """High-risk CLI runs must propagate risk_level=high, executor_mode=worktree."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = RuntimeExecutionContext(
            run_id="run-risk-002",
            space_id="sp-b",
            prompt="work",
            mode="normal",
            sandbox_cwd="/wt",
            model_name=None,
            system_prompt=None,
            adapter_config={},
            risk_level="high",
            executor_mode="worktree",
        )

        mock_broker_instance = MagicMock()
        mock_broker_instance.grant_for_run.return_value = _mock_grant()
        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch("app.credentials.broker.CredentialBroker", return_value=mock_broker_instance),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        mock_broker_instance.grant_for_run.assert_called_once()
        call_kwargs = mock_broker_instance.grant_for_run.call_args[1]
        assert call_kwargs["risk_level"] == "high"
        assert call_kwargs["executor_mode"] == "worktree"

    def test_context_risk_level_defaults_to_low(self):
        ctx = RuntimeExecutionContext(
            run_id="r1",
            space_id="s1",
            prompt="p",
            mode="normal",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
        )
        assert ctx.risk_level == "low"
        assert ctx.executor_mode == "worktree"


# ===========================================================================
# 13. Credential grant/source metadata in adapter_metadata (task C)
# ===========================================================================

class TestCredentialSourceMetadata:
    def test_profile_grant_records_credential_source_profile(self):
        """When broker returns a grant with a profile, credential_source='profile'."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_grant = MagicMock()
        mock_grant.temp_home = None  # docker-style grant (no temp home)

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        meta = result.adapter_metadata or {}
        assert meta.get("credential_source") == "profile"
        assert meta.get("credential_broker_used") is True
        assert meta.get("fallback_used") is False

    def test_no_grant_fails_without_container_default_fallback(self):
        """When broker returns None (no profile), CLI execution fails before adapter invocation."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=None),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        meta = result.adapter_metadata or {}
        assert meta.get("credential_source") == "none"
        assert meta.get("credential_broker_used") is True
        assert meta.get("fallback_used") is True
        assert meta.get("fallback_reason") == "no_profile_configured"
        mock_cli.run.assert_not_called()

    def test_temp_home_created_recorded_when_grant_has_temp_home(self):
        """When grant.temp_home is set, temp_home_created=True in adapter_metadata."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_grant = MagicMock()
        mock_grant.temp_home = "/tmp/run-001-home"

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()
        mock_broker = MagicMock()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch("app.credentials.broker.CredentialBroker", return_value=mock_broker),
        ):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        assert meta.get("temp_home_created") is True
        assert meta.get("cleanup_status") == "ok"

    def test_cleanup_failure_recorded_in_metadata(self):
        """When cleanup_temp_home raises, cleanup_status='failed' in adapter_metadata."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_grant = MagicMock()
        mock_grant.temp_home = "/tmp/run-fail-home"

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        mock_broker = MagicMock()
        mock_broker.cleanup_temp_home.side_effect = OSError("cleanup failed")

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch("app.credentials.broker.CredentialBroker", return_value=mock_broker),
        ):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        assert meta.get("cleanup_status") == "failed"

    def test_adapter_metadata_contains_no_secret_fields(self):
        """adapter_metadata must not contain any obvious secret field names."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(adapter, "_resolve_credential_grant", return_value=None),
        ):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        secret_fields = {
            "api_key", "token", "password", "secret", "auth_token",
            "anthropic_api_key", "openai_api_key", "source_path", "home_path",
        }
        found = secret_fields & set(meta.keys())
        assert not found, f"Secret field(s) found in adapter_metadata: {found}"

    def test_broker_error_records_fallback_reason_broker_error(self):
        """If broker raises, fallback_used=True and fallback_reason='broker_error'."""
        from app.runtimes.adapters.cli_runtime import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        ctx = _make_ctx()

        mock_cli = MagicMock()
        mock_cli.is_available.return_value = True
        mock_cli.run.return_value = _fake_cli_result()

        with (
            patch("app.runtimes.adapters.cli_runtime._resolve_cli_adapter", return_value=mock_cli),
            patch.object(
                adapter, "_resolve_credential_grant",
                side_effect=Exception("broker unavailable"),
            ),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        meta = result.adapter_metadata or {}
        assert meta.get("fallback_used") is True
        assert meta.get("fallback_reason") == "broker_error"
        assert meta.get("credential_source") == "none"
        mock_cli.run.assert_not_called()


# ===========================================================================
# 14. Adapter naming guard — codex vs codex_cli (task A)
# ===========================================================================

class TestAdapterNamingGuard:
    def test_codex_alone_not_in_registry(self):
        """'codex' without '_cli' must not be a registered runtime adapter."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("codex")

    def test_codex_cli_in_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("codex_cli")

    def test_codex_cli_instantiates(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        from app.runtimes.adapters.cli_runtime import CodexCliRuntimeAdapter
        adapter = instantiate_runtime_adapter("codex_cli")
        assert isinstance(adapter, CodexCliRuntimeAdapter)

    def test_codex_without_cli_raises(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        with pytest.raises(KeyError):
            instantiate_runtime_adapter("codex")
