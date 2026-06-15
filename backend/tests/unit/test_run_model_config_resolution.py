"""Unit tests for run model config resolution priority."""

from __future__ import annotations

import pytest

from app.runs.model_config_resolution import (
    resolve_model_config_for_runtime,
    resolve_model_config_priority,
)
from app.runtimes.requirements import (
    UnknownRuntimeRequirementsError,
    get_runtime_requirements,
    resolve_default_provider_for_runtime,
)
from tests.support import factories


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


def test_default_provider_is_not_resolved_for_non_model_provider_runtimes(db):
    space_id = "model-config-runtime-none"
    factories.create_test_space(db, space_id=space_id)
    factories.create_test_model_provider(
        db,
        space_id=space_id,
        is_default=True,
        commit=False,
    )

    for adapter_type in ("capability", "claude_code", "codex_cli"):
        assert resolve_default_provider_for_runtime(db, space_id, adapter_type) is None


def test_cli_runtime_ignores_runtime_scoped_default_provider(db):
    space_id = "model-config-runtime-default"
    factories.create_test_space(db, space_id=space_id)
    user = factories.create_test_user(db, space_id=space_id)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id)
    version = agent.versions[0]
    global_default = factories.create_test_model_provider(
        db,
        space_id=space_id,
        name="global-default",
        is_default=True,
        default_model="gpt-global",
        commit=False,
    )
    runtime_default = factories.create_test_model_provider(
        db,
        space_id=space_id,
        name="runtime-default",
        default_model="gpt-runtime",
        commit=False,
    )
    runtime_default.config_json = {"runtime_default_for": "claude_code"}
    db.flush()

    default = resolve_default_provider_for_runtime(db, space_id, "claude_code")
    resolved = resolve_model_config_for_runtime(
        db,
        space_id=space_id,
        adapter_type="claude_code",
        request_provider_id=None,
        request_model=None,
        version=version,
    )

    assert default is None
    assert resolved.model_provider_id is None
    assert resolved.model_provider_id != global_default.id
    assert resolved.model_name is None
    assert resolved.source == "none"


def test_every_registered_runtime_adapter_has_explicit_requirements():
    from app.runtimes.specs import list_runtime_adapter_specs

    missing: list[str] = []
    for spec in list_runtime_adapter_specs():
        if spec.implementation_status != "implemented":
            continue
        try:
            get_runtime_requirements(spec.adapter_type)
        except UnknownRuntimeRequirementsError:
            missing.append(spec.adapter_type)

    assert missing == []


def test_unknown_non_empty_runtime_requirement_raises():
    with pytest.raises(UnknownRuntimeRequirementsError) as exc:
        get_runtime_requirements("unknown_runtime_for_requirements_test")

    assert exc.value.adapter_type == "unknown_runtime_for_requirements_test"
    assert "runtime_requirements_missing" in str(exc.value)


def test_none_or_empty_runtime_requirement_is_none_mode():
    assert get_runtime_requirements(None).model_provider_mode == "none"
    assert get_runtime_requirements("").model_provider_mode == "none"
