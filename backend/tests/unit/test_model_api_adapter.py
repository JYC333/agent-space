"""Tests for the model_api runtime adapter (in-process, provider-agnostic, no tools)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.providers.invocation import (
    CompletionResult,
    ProviderUnavailableError,
)
from app.providers import CredentialResolutionError
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
        adapter_config={},
        model_provider_id="prov-1",
        resolved_credentials={"api_key": "sk-resolved"},
        db=object(),
    )
    base.update(overrides)
    return RuntimeExecutionContext(**base)


# ---------------------------------------------------------------------------
# Spec + registry
# ---------------------------------------------------------------------------

class TestModelApiSpecAndRegistry:
    def test_spec_shape(self):
        from app.runtimes.specs import get_runtime_adapter_spec
        spec = get_runtime_adapter_spec("model_api")
        assert spec.runtime_kind == "managed_api"
        assert spec.implementation_status == "implemented"
        assert spec.credentials.credential_mode == "model_provider_api_key"
        assert spec.model.model_provider_mode == "required"
        assert spec.sandbox.requires_file_access is False
        assert spec.sandbox.minimum_sandbox_level == "none"
        assert spec.sandbox.supports_worktree is False
        assert spec.sandbox.supports_one_shot_docker is False
        assert spec.sandbox.requires_workspace_for_execution is False
        assert spec.executable.command is None
        assert spec.invocation.headless_command_template == []
        assert spec.output.output_parser_type == "plain_text"

    def test_registry_instantiates(self):
        from app.runtimes.registry import instantiate_runtime_adapter, is_adapter_type_implemented
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        assert is_adapter_type_implemented("model_api") is True
        adapter = instantiate_runtime_adapter("model_api")
        assert isinstance(adapter, ModelApiRuntimeAdapter)
        assert adapter.requires_credentials is True
        assert adapter.requires_file_access is False
        assert adapter.supports_sandboxed_execution is False
        assert adapter.uses_cli_credentials is False

    def test_execution_plane_mapping(self):
        from app.execution_planes.service import _ADAPTER_TO_PLANE
        from app.execution_planes.seeder import _DEFAULT_PLANES
        assert _ADAPTER_TO_PLANE["model_api"] == "managed_model_api"
        names = {p["name"] for p in _DEFAULT_PLANES}
        assert "managed_model_api" in names
        plane = next(p for p in _DEFAULT_PLANES if p["name"] == "managed_model_api")
        assert plane["data_exposure_level"] == "model_provider"
        assert plane["observability_level"] == "full_trace"


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------

class TestModelApiExecute:
    def test_happy_path_returns_output_text(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            return_value=CompletionResult(text="the summary", model="gpt-4o-mini", usage={"total_tokens": 12}),
        ) as mock_ct:
            result = ModelApiRuntimeAdapter().execute(_ctx())
        assert result.success is True
        assert result.output_text == "the summary"
        assert result.exit_code == 0
        assert result.output_json["model"] == "gpt-4o-mini"
        assert result.output_json["usage"] == {"total_tokens": 12}
        # provider_id + pre-resolved key forwarded; no env involvement
        kwargs = mock_ct.call_args.kwargs
        assert kwargs["provider_id"] == "prov-1"
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["api_key"] == "sk-resolved"
        assert kwargs["system"] == "You are helpful."
        assert kwargs["user"] == "summarize this"

    def test_missing_provider_id_fails(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch("app.runtimes.adapters.model_api.complete_text") as mock_ct:
            result = ModelApiRuntimeAdapter().execute(_ctx(model_provider_id=None))
        assert result.success is False
        assert result.error_code == "model_provider_required"
        mock_ct.assert_not_called()

    def test_missing_db_session_fails_before_provider_invocation(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch("app.runtimes.adapters.model_api.complete_text") as mock_ct:
            result = ModelApiRuntimeAdapter().execute(_ctx(db=None))
        assert result.success is False
        assert result.error_code == "model_provider_session_required"
        mock_ct.assert_not_called()

    def test_provider_error_surfaces_as_failure(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            side_effect=ProviderUnavailableError("disabled"),
        ):
            result = ModelApiRuntimeAdapter().execute(_ctx())
        assert result.success is False
        assert result.error_code == "provider_unavailable"

    def test_credential_error_surfaces_sanitized_failure(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            side_effect=CredentialResolutionError("Credential could not be resolved"),
        ):
            result = ModelApiRuntimeAdapter().execute(_ctx())
        assert result.success is False
        assert result.error_code == "credentials_missing"
        assert "sk-" not in (result.error_text or "")

    def test_network_error_surfaces_as_failure(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            side_effect=RuntimeError("boom"),
        ):
            result = ModelApiRuntimeAdapter().execute(_ctx())
        assert result.success is False
        assert result.error_code == "model_api_call_failed"

    def test_empty_resolved_key_fails_before_provider_invocation(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            return_value=CompletionResult(text="x", model="m"),
        ) as mock_ct:
            result = ModelApiRuntimeAdapter().execute(_ctx(resolved_credentials={}))
        assert result.success is False
        assert result.error_code == "credentials_missing"
        mock_ct.assert_not_called()

    def test_adapter_does_not_use_cli_or_process_channels(self):
        from app.runtimes.adapters import ModelApiRuntimeAdapter
        with patch(
            "app.runtimes.adapters.model_api.complete_text",
            return_value=CompletionResult(text="x", model="m"),
        ):
            result = ModelApiRuntimeAdapter().execute(
                _ctx(
                    adapter_config={
                        "credential_profile_id": "cli-profile-must-be-ignored",
                        "executable_path": "/bin/false",
                    },
                    process_registry=object(),
                    sandbox_cwd="/tmp/should-not-be-used",
                )
            )
        assert result.success is True
        assert result.adapter_metadata["adapter_type"] == "model_api"
