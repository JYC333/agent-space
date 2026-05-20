"""Unit tests for run model config resolution priority."""

from __future__ import annotations

from app.runs.model_config_resolution import resolve_model_config_priority


def test_run_request_overrides_agent_version():
    resolved = resolve_model_config_priority(
        request_provider_id="run-prov",
        request_model="gpt-run",
        version_provider_id="agent-prov",
        version_model_name="gpt-agent",
        default_provider_id="default-prov",
        default_provider_model="gpt-default",
    )
    assert resolved.model_provider_id == "run-prov"
    assert resolved.model_name == "gpt-run"
    assert resolved.source == "request"


def test_agent_version_used_when_no_run_override():
    resolved = resolve_model_config_priority(
        request_provider_id=None,
        request_model=None,
        version_provider_id="agent-prov",
        version_model_name="gpt-agent",
        default_provider_id="default-prov",
        default_provider_model="gpt-default",
    )
    assert resolved.model_provider_id == "agent-prov"
    assert resolved.model_name == "gpt-agent"
    assert resolved.source == "agent_default"


def test_space_default_used_when_agent_has_no_model():
    resolved = resolve_model_config_priority(
        request_provider_id=None,
        request_model=None,
        version_provider_id=None,
        version_model_name=None,
        default_provider_id="default-prov",
        default_provider_model="gpt-default",
    )
    assert resolved.model_provider_id == "default-prov"
    assert resolved.model_name == "gpt-default"
    assert resolved.source == "space_default"
