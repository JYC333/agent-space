from __future__ import annotations

import subprocess

import pytest
from sqlalchemy.orm.attributes import flag_modified


def test_builtin_specs_are_unique_and_implemented_specs_validate():
    from app.runtimes.specs import list_runtime_adapter_specs

    specs = list_runtime_adapter_specs()
    adapter_types = [s.adapter_type for s in specs]
    assert len(adapter_types) == len(set(adapter_types))
    implemented = {
        s.adapter_type for s in specs if s.implementation_status == "implemented"
    }
    assert {
        "capability",
        "model_api",
        "ts_agent_host",
        "claude_code",
        "codex_cli",
    }.issubset(implemented)
    planned = {s.adapter_type for s in specs if s.implementation_status == "planned"}
    assert {"opencode", "gemini_cli", "custom"}.issubset(planned)
    assert all(
        not s.enabled_by_default for s in specs if s.implementation_status != "implemented"
    )


def test_runtime_requirements_derive_from_spec():
    from app.runtimes.requirements import get_runtime_requirements

    assert get_runtime_requirements("capability").model_provider_mode == "none"
    model_api = get_runtime_requirements("model_api")
    assert model_api.credential_mode == "model_provider_api_key"
    assert model_api.model_provider_mode == "required"
    assert model_api.supports_model_override is False
    ts_host = get_runtime_requirements("ts_agent_host")
    assert ts_host.credential_mode == "model_provider_api_key"
    assert ts_host.credential_release_channel == "control_plane_runtime_host"
    assert ts_host.model_provider_mode == "required"
    claude = get_runtime_requirements("claude_code")
    assert claude.credential_mode == "cli_profile"
    assert claude.model_provider_mode == "none"
    codex = get_runtime_requirements("codex_cli")
    assert codex.credential_mode == "cli_profile"
    assert codex.supports_model_override is False


def test_registry_uses_generic_cli_runtime():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.adapters.ts_agent_host import TsAgentHostRuntimeAdapter
    from app.runtimes.registry import instantiate_runtime_adapter

    assert isinstance(
        instantiate_runtime_adapter("ts_agent_host"), TsAgentHostRuntimeAdapter
    )
    assert isinstance(instantiate_runtime_adapter("claude_code"), GenericCliRuntimeAdapter)
    assert isinstance(instantiate_runtime_adapter("codex_cli"), GenericCliRuntimeAdapter)
    with pytest.raises(KeyError):
        instantiate_runtime_adapter("opencode")


def test_command_renderer_rejects_unknown_variable_and_redacts_prompt():
    from app.runtimes.command_renderer import CommandRenderError, render_command
    from app.runtimes.specs import get_runtime_adapter_spec

    spec = get_runtime_adapter_spec("claude_code")
    rendered = render_command(spec=spec, prompt="secret prompt", model="sonnet")
    assert "secret prompt" in rendered.argv
    assert "secret prompt" not in rendered.redacted_argv
    assert "--model" in rendered.argv

    bad_spec = spec.model_copy(deep=True)
    bad_spec.invocation.headless_command_template.append("{unknown}")
    with pytest.raises(CommandRenderError) as exc:
        render_command(spec=bad_spec, prompt="x")
    assert exc.value.error_code == "unknown_template_variable"


def test_command_renderer_model_override_and_permission_bypass_rules():
    from app.runtimes.command_renderer import CommandRenderError, render_command
    from app.runtimes.specs import get_runtime_adapter_spec

    prompt = "do not split; $(rm -rf /)"
    rendered = render_command(
        spec=get_runtime_adapter_spec("claude_code"), prompt=prompt, model="sonnet"
    )
    assert prompt in rendered.argv
    assert rendered.argv.count(prompt) == 1
    assert "--model" in rendered.argv
    assert prompt not in rendered.redacted_argv

    with pytest.raises(CommandRenderError) as exc:
        render_command(spec=get_runtime_adapter_spec("codex_cli"), prompt=prompt, model="gpt-5")
    assert exc.value.error_code == "model_override_not_supported"

    bypass = render_command(
        spec=get_runtime_adapter_spec("claude_code"),
        prompt=prompt,
        permission_bypass=True,
    )
    assert "--dangerously-skip-permissions" in bypass.argv


def test_permission_bypass_policy_gate():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.base import RuntimeExecutionContext
    from app.runtimes.specs import get_runtime_adapter_spec

    adapter = GenericCliRuntimeAdapter(get_runtime_adapter_spec("claude_code"))
    base = dict(
        run_id="run",
        space_id="space",
        prompt="p",
        mode="live",
        sandbox_cwd="/tmp/worktree",
        model_name=None,
        system_prompt=None,
        adapter_config={"permission_bypass": True},
        risk_level="high",
        executor_mode="worktree",
        workspace_id="workspace",
    )
    assert adapter._permission_bypass_error(RuntimeExecutionContext(**base)) is not None
    base["adapter_config"] = {
        "permission_bypass": True,
        "runtime_policy_json": {"allow_permission_bypass": True},
    }
    base["risk_level"] = "medium"
    assert "risk_level" in adapter._permission_bypass_error(RuntimeExecutionContext(**base))
    base["risk_level"] = "high"
    base["workspace_id"] = None
    assert "workspace" in adapter._permission_bypass_error(RuntimeExecutionContext(**base))
    base["workspace_id"] = "workspace"
    assert adapter._permission_bypass_error(RuntimeExecutionContext(**base)) is None


def test_run_model_selection_default_is_cli_default():
    from app.models import Run
    from app.schemas import RunRequest

    assert Run.model_selection_mode.property.columns[0].default.arg == "cli_default"
    assert RunRequest(prompt="x").model_selection_mode == "cli_default"


def test_cli_specs_do_not_advertise_one_shot_docker():
    from app.runtimes.specs import get_runtime_adapter_spec

    assert get_runtime_adapter_spec("claude_code").sandbox.supports_one_shot_docker is False
    assert get_runtime_adapter_spec("codex_cli").sandbox.supports_one_shot_docker is False


def test_output_parser_registry_is_generic_and_stable():
    from pydantic import ValidationError
    from app.runtimes.output_parsers import get_output_parser
    from app.runtimes.specs import OutputSpec, get_runtime_adapter_spec

    parsed = get_output_parser("generic").parse(stdout="x" * 13000, stderr="bad", exit_code=2)
    assert parsed.error_code == "cli_adapter_nonzero_exit"
    assert parsed.produced_artifact_paths == []
    assert parsed.redacted_stdout.endswith("[TRUNCATED]")
    assert parsed.error_text == "bad"
    assert get_runtime_adapter_spec("claude_code").output.output_parser_type == "generic"
    assert get_runtime_adapter_spec("codex_cli").output.output_parser_type == "generic"
    with pytest.raises(ValidationError):
        OutputSpec(output_parser_type="claude_code")


def test_command_renderer_rejects_unsafe_overrides_and_uses_path_for_spec_command(tmp_path, monkeypatch):
    from app.runtimes.command_renderer import CommandRenderError, render_command
    from app.runtimes.specs import get_runtime_adapter_spec

    spec = get_runtime_adapter_spec("claude_code")
    with pytest.raises(CommandRenderError) as rel:
        render_command(spec=spec, prompt="x", executable_path="claude")
    assert rel.value.error_code == "executable_override_not_absolute"

    with pytest.raises(CommandRenderError) as missing:
        render_command(spec=spec, prompt="x", executable_path=str(tmp_path / "missing"))
    assert missing.value.error_code == "executable_not_found"

    not_executable = tmp_path / "not-executable"
    not_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(CommandRenderError) as no_exec:
        render_command(spec=spec, prompt="x", executable_path=str(not_executable))
    assert no_exec.value.error_code == "executable_not_executable"

    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    exe = path_dir / "claude"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_dir))
    rendered = render_command(spec=spec, prompt="x")
    assert rendered.argv[0] == str(exe)

    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    rendered = render_command(spec=spec, prompt="x")
    assert rendered.argv[0] == "claude"


def _agent_version(db, agent):
    from app.models import AgentVersion
    return db.get(AgentVersion, agent.current_version_id)


def _workspace_for_worktree_preflight(db, *, space_id: str, tmp_path):
    from tests.support import factories

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True)
    return factories.create_test_workspace(
        db,
        space_id=space_id,
        root_path=str(workspace_root),
        allow_external_root=True,
    )


def _path_with_git_only(tmp_path, monkeypatch) -> None:
    import shutil

    git = shutil.which("git")
    assert git is not None
    bin_dir = tmp_path / "path-with-git-only"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(git)
    monkeypatch.setenv("PATH", str(bin_dir))


def _mark_cli_profile_ready(monkeypatch) -> None:
    class ReadyBroker:
        def profile_ready(self, runtime=None, profile_id=None):
            return True

    monkeypatch.setattr("app.credentials.broker.CredentialBroker", lambda: ReadyBroker())


def test_preflight_defaults_to_model_api(db, test_space, test_user):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "low"}
    version.runtime_config_json = {}
    flag_modified(version, "runtime_policy_json")
    flag_modified(version, "runtime_config_json")
    db.flush()

    result = PreflightService(db).check(PreflightRequest(agent_id=agent.id), test_space.id)
    assert result.adapter_type == "model_api"
    assert result.executable is True


def test_preflight_does_not_probe_host_cli_path(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    _mark_cli_profile_ready(monkeypatch)
    workspace = _workspace_for_worktree_preflight(db, space_id=test_space.id, tmp_path=tmp_path)
    _path_with_git_only(tmp_path, monkeypatch)

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "high"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, workspace_id=workspace.id, adapter_type="claude_code"),
        test_space.id,
    )

    assert result.adapter_type == "claude_code"
    assert result.executable is True
    assert not any("executable_not_found" in w for w in result.warnings)


def test_preflight_native_adapters_skip_cli_runtime_tool_checks(db, test_space, test_user):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "low"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    model_api = PreflightService(db).check(PreflightRequest(agent_id=agent.id), test_space.id)
    capability = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="capability"),
        test_space.id,
    )

    assert model_api.adapter_type == "model_api"
    assert capability.adapter_type == "capability"


def test_preflight_and_execution_agree_for_request_adapter_type(db, test_space, test_user):
    from app.runs.adapter_resolution import resolve_runtime_adapter
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_config_json = {"adapter_type": "capability"}
    version.runtime_policy_json = {"risk_level": "low"}
    flag_modified(version, "runtime_config_json")
    flag_modified(version, "runtime_policy_json")
    run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=agent)
    run.adapter_type = "model_api"
    db.flush()

    preflight = PreflightService(db).check(PreflightRequest(agent_id=agent.id, adapter_type="model_api"), test_space.id)
    resolved = resolve_runtime_adapter(db, run=run, version=version, policy=version.runtime_policy_json)
    assert preflight.adapter_type == resolved.adapter_type == "model_api"


def test_preflight_uses_spec_for_file_access_and_credentials(db, test_space, test_user, monkeypatch):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    class EmptyBroker:
        def profile_ready(self, runtime=None, profile_id=None):
            return False
        def list_profiles(self, runtime=None):
            return []
        def get_profile(self, profile_id):
            return None

    monkeypatch.setattr("app.credentials.broker.CredentialBroker", lambda: EmptyBroker())
    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "medium"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    # A workspace-bound CLI at medium risk must be raised to high (worktree):
    # operating on a persistent workspace needs worktree isolation + diff review.
    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code", workspace_id="bound"),
        test_space.id,
    )
    assert any("file_access_adapter_requires_worktree_policy" in err for err in result.errors)

    # A no-workspace CLI at medium risk resolves to a run-scope ephemeral working
    # dir (a real sandbox), so it is NOT rejected for lacking worktree policy.
    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code"),
        test_space.id,
    )
    assert not any(
        "file_access_adapter_requires_worktree_policy" in err for err in result.errors
    )

    version.runtime_policy_json = {"risk_level": "high"}
    flag_modified(version, "runtime_policy_json")
    db.flush()
    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code", workspace_id="missing"),
        test_space.id,
    )
    assert result.executable is False

    version.runtime_policy_json = {"risk_level": "low"}
    flag_modified(version, "runtime_policy_json")
    db.flush()
    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="capability"),
        test_space.id,
    )
    assert not any("runtime_credential_profile_required" in err for err in result.errors)

    from app.runs.preflight import _PreflightState
    state = _PreflightState(space_id=test_space.id, adapter_type="claude_code")
    PreflightService(db)._check_credential_profile(PreflightRequest(agent_id=agent.id), state)
    assert any("runtime_credential_profile_required" in err for err in state.errors)


def test_preflight_credential_readiness_requires_existing_source_path(db, test_space, test_user, tmp_path, monkeypatch):
    from app.credentials.broker import CredentialBroker, CredentialProfile
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    missing_profile = CredentialProfile(
        id="claude_code/default",
        runtime="claude_code",
        name="default",
        source_path=str(tmp_path / "missing-profile"),
        target_path="/home/agent/.claude",
    )
    broker = CredentialBroker(instance_root=str(tmp_path / "instance"))
    broker._profiles = {"claude_code/default": missing_profile}
    monkeypatch.setattr("app.credentials.broker.CredentialBroker", lambda: broker)

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True)
    workspace = factories.create_test_workspace(
        db,
        space_id=test_space.id,
        root_path=str(workspace_root),
        allow_external_root=True,
    )
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "high"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code", workspace_id=workspace.id),
        test_space.id,
    )
    assert any("runtime_credential_profile_required" in err for err in result.errors)

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    broker._profiles["claude_code/default"] = CredentialProfile(
        id="claude_code/default",
        runtime="claude_code",
        name="default",
        source_path=str(profile_dir),
        target_path="/home/agent/.claude",
    )
    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code", workspace_id=workspace.id),
        test_space.id,
    )
    assert not any("runtime_credential_profile_required" in err for err in result.errors)


def test_credential_audit_does_not_store_paths_tokens_or_file_content(db, test_space, test_user, monkeypatch):
    from app.models import CliCredentialEvent
    from app.runtimes.base import RuntimeExecutionContext
    from app.runtimes.registry import instantiate_runtime_adapter
    from tests.support import factories

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=agent)
    adapter = instantiate_runtime_adapter("claude_code")
    monkeypatch.setattr(adapter, "_resolve_credential_grant", lambda ctx: None)
    result = adapter.execute(
        RuntimeExecutionContext(
            run_id=run.id,
            space_id=test_space.id,
            prompt="do work",
            mode="headless",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={"credential_profile_id": "claude_code/default"},
            db=db,
        )
    )
    assert result.error_code == "runtime_credential_profile_required"
    db.flush()

    events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
    assert len(events) == 1
    record = {
        column.name: getattr(events[0], column.name)
        for column in CliCredentialEvent.__table__.columns
    }
    text = "\n".join(str(value) for value in record.values() if value is not None)
    assert "/home/" not in text
    assert "/tmp/" not in text
    assert "source_path" not in text
    assert "token" not in text.lower()
    assert "secret-content" not in text
