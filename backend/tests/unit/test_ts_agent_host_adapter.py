"""Tests for the TS agent-host runtime adapter seam."""
from __future__ import annotations

from unittest.mock import patch

from app.runtimes.base import RuntimeExecutionContext


def _ctx(**overrides) -> RuntimeExecutionContext:
    base = dict(
        run_id="run-1",
        space_id="space-1",
        prompt="summarize this",
        mode="live",
        sandbox_cwd=None,
        model_name="gpt-4o-mini",
        system_prompt="You are helpful.",
        adapter_config={"max_tokens": 32},
        model_provider_id="provider-1",
        instruction="instruction text",
        project_id="project-1",
        workspace_id="workspace-1",
        capability_id="capability-1",
        context_package={"context_snapshot_id": "snapshot-1"},
        resolved_credentials={"api_key": "sk-must-not-cross-this-boundary"},
    )
    base.update(overrides)
    return RuntimeExecutionContext(**base)


class TestTsAgentHostSpecAndRegistry:
    def test_spec_shape(self):
        from app.runtimes.requirements import get_runtime_requirements
        from app.runtimes.specs import get_runtime_adapter_spec

        spec = get_runtime_adapter_spec("ts_agent_host")
        assert spec.runtime_kind == "managed_api"
        assert spec.implementation_status == "implemented"
        assert spec.enabled_by_default is False
        assert spec.credentials.credential_mode == "model_provider_api_key"
        assert (
            spec.credentials.credential_release_channel == "control_plane_runtime_host"
        )
        assert spec.model.model_provider_mode == "required"
        assert spec.sandbox.requires_file_access is False
        assert spec.output.output_parser_type == "plain_text"

        requirements = get_runtime_requirements("ts_agent_host")
        assert requirements.credential_mode == "model_provider_api_key"
        assert requirements.credential_release_channel == "control_plane_runtime_host"
        assert requirements.model_provider_mode == "required"

    def test_registry_instantiates(self):
        from app.runtimes.adapters import TsAgentHostRuntimeAdapter
        from app.runtimes.registry import (
            instantiate_runtime_adapter,
            is_adapter_type_implemented,
        )

        assert is_adapter_type_implemented("ts_agent_host") is True
        adapter = instantiate_runtime_adapter("ts_agent_host")
        assert isinstance(adapter, TsAgentHostRuntimeAdapter)
        assert adapter.requires_credentials is False
        assert adapter.uses_cli_credentials is False
        assert adapter.requires_file_access is False

    def test_execution_plane_mapping(self):
        from app.execution_planes.service import _ADAPTER_TO_PLANE

        assert _ADAPTER_TO_PLANE["ts_agent_host"] == "managed_model_api"


class TestTsAgentHostExecute:
    def test_happy_path_maps_internal_host_response(self):
        from app.runtimes.adapters import TsAgentHostRuntimeAdapter

        with patch(
            "app.runtimes.adapters.ts_agent_host.execute_runtime_host_via_control_plane",
            return_value={
                "success": True,
                "stdout": "the summary",
                "stderr": "",
                "output_text": "the summary",
                "output_json": {
                    "adapter_type": "ts_agent_host",
                    "model": "gpt-4o-mini",
                },
                "exit_code": 0,
                "started_at": "2026-06-12T10:00:00.000Z",
                "completed_at": "2026-06-12T10:00:01.000Z",
                "model": "gpt-4o-mini",
                "usage": {"total_tokens": 12},
                "events": [{"type": "model.text_delta", "delta": "the summary"}],
                "adapter_metadata": {"adapter_type": "ts_agent_host"},
            },
        ) as mock_host:
            result = TsAgentHostRuntimeAdapter().execute(_ctx())

        assert result.success is True
        assert result.output_text == "the summary"
        assert result.exit_code == 0
        assert result.output_json["adapter_type"] == "ts_agent_host"
        assert result.adapter_log_json["model_events"] == [
            {"type": "model.text_delta", "delta": "the summary"}
        ]

        payload = mock_host.call_args.args[0]
        assert payload["model_provider_id"] == "provider-1"
        assert payload["context_snapshot_id"] == "snapshot-1"
        assert payload["max_tokens"] == 32
        assert payload["tool_mode"] == "disabled"
        assert payload["tool_bindings"] == []
        assert "api_key" not in str(payload)
        assert "sk-must-not-cross" not in str(payload)

    def test_missing_provider_id_fails_before_internal_call(self):
        from app.runtimes.adapters import TsAgentHostRuntimeAdapter

        with patch(
            "app.runtimes.adapters.ts_agent_host.execute_runtime_host_via_control_plane"
        ) as mock_host:
            result = TsAgentHostRuntimeAdapter().execute(_ctx(model_provider_id=None))

        assert result.success is False
        assert result.error_code == "model_provider_required"
        mock_host.assert_not_called()

    def test_internal_host_error_surfaces_as_failed_adapter_result(self):
        from app.runtimes.adapters import TsAgentHostRuntimeAdapter
        from app.runtimes.runtime_host_client import RuntimeHostClientError

        with patch(
            "app.runtimes.adapters.ts_agent_host.execute_runtime_host_via_control_plane",
            side_effect=RuntimeHostClientError("Unauthorized"),
        ):
            result = TsAgentHostRuntimeAdapter().execute(_ctx())

        assert result.success is False
        assert result.error_code == "runtime_host_unavailable"
        assert result.exit_code == 1

    def test_host_failure_response_maps_without_exception(self):
        from app.runtimes.adapters import TsAgentHostRuntimeAdapter

        with patch(
            "app.runtimes.adapters.ts_agent_host.execute_runtime_host_via_control_plane",
            return_value={
                "success": False,
                "stdout": "",
                "stderr": "tool execution is not enabled",
                "output_text": "",
                "exit_code": 1,
                "error_code": "runtime_tools_not_implemented",
                "error_text": "tool execution is not enabled",
                "adapter_metadata": {"adapter_type": "ts_agent_host"},
            },
        ):
            result = TsAgentHostRuntimeAdapter().execute(_ctx())

        assert result.success is False
        assert result.error_code == "runtime_tools_not_implemented"
        assert result.error_text == "tool execution is not enabled"
