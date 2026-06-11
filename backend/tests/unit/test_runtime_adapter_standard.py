from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm.attributes import flag_modified


def test_builtin_specs_are_unique_and_implemented_specs_validate():
    from app.runtimes.specs import list_runtime_adapter_specs

    specs = list_runtime_adapter_specs()
    adapter_types = [s.adapter_type for s in specs]
    assert len(adapter_types) == len(set(adapter_types))
    implemented = {s.adapter_type for s in specs if s.implementation_status == "implemented"}
    assert {"echo", "capability", "model_api", "claude_code", "codex_cli"}.issubset(implemented)
    planned = {s.adapter_type for s in specs if s.implementation_status == "planned"}
    assert {"opencode", "gemini_cli", "custom"}.issubset(planned)
    assert all(not s.enabled_by_default for s in specs if s.implementation_status != "implemented")


def test_runtime_requirements_derive_from_spec():
    from app.runtimes.requirements import get_runtime_requirements

    assert get_runtime_requirements("echo").credential_mode == "none"
    assert get_runtime_requirements("capability").model_provider_mode == "none"
    model_api = get_runtime_requirements("model_api")
    assert model_api.credential_mode == "model_provider_api_key"
    assert model_api.model_provider_mode == "required"
    assert model_api.supports_model_override is False
    claude = get_runtime_requirements("claude_code")
    assert claude.credential_mode == "cli_profile"
    assert claude.model_provider_mode == "none"
    codex = get_runtime_requirements("codex_cli")
    assert codex.credential_mode == "cli_profile"
    assert codex.supports_model_override is False


def test_registry_uses_generic_cli_runtime():
    from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
    from app.runtimes.registry import instantiate_runtime_adapter

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
    rendered = render_command(spec=get_runtime_adapter_spec("claude_code"), prompt=prompt, model="sonnet")
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


def test_detection_does_not_mark_missing_cli_commands_installed(db, test_space, monkeypatch, tmp_path):
    from app.runtime_adapters.service import RuntimeAdapterService

    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))

    claude = RuntimeAdapterService(db).detect_one("claude_code", space_id=test_space.id)
    assert claude.installed is False
    assert claude.executable_path is None
    assert claude.warnings == ["'claude' not found in PATH"]

    codex = RuntimeAdapterService(db).detect_one("codex_cli", space_id=test_space.id)
    assert codex.installed is False
    assert codex.executable_path is None
    assert codex.warnings == ["'codex' not found in PATH"]


def test_executable_override_detection_policy(db, test_space, tmp_path):
    from app.models import RuntimeAdapter
    from app.runtime_adapters.service import RuntimeAdapterService
    from app.schemas import RuntimeAdapterCreate

    exe = tmp_path / "runtime-cli"
    exe.write_text("#!/bin/sh\necho runtime-cli 1.0\n", encoding="utf-8")
    exe.chmod(0o755)

    svc = RuntimeAdapterService(db)
    row = svc.create(
        RuntimeAdapterCreate(
            adapter_type="claude_code",
            name="Claude override",
            executable_path=str(exe),
        ),
        test_space.id,
    )
    status = svc.status(row)
    assert status.installed is True
    assert status.executable_path == str(exe.resolve())
    assert status.version == "runtime-cli 1.0"

    stale = RuntimeAdapter(
        id="runtime-adapter-stale-override",
        space_id=test_space.id,
        name="Stale override",
        adapter_type="claude_code",
        enabled=True,
        config_json={"executable_path": str(tmp_path / "missing-cli")},
        health_status="unknown",
        quota_status="unknown",
    )
    db.add(stale)
    db.flush()
    invalid = svc.status(stale)
    assert invalid.installed is False
    assert invalid.executable_path == str(tmp_path / "missing-cli")
    assert any("executable_not_found: executable_path override does not exist" in w for w in invalid.warnings)


def test_detection_version_probe_uses_shell_false(db, test_space, tmp_path, monkeypatch):
    from app.runtime_adapters.service import RuntimeAdapterService
    from app.schemas import RuntimeAdapterCreate

    exe = tmp_path / "runtime-cli"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    calls = []

    class Result:
        stdout = "version"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return Result()

    monkeypatch.setattr("app.runtime_adapters.service.subprocess.run", fake_run)
    row = RuntimeAdapterService(db).create(
        RuntimeAdapterCreate(adapter_type="claude_code", name="Claude", executable_path=str(exe)),
        test_space.id,
    )
    status = RuntimeAdapterService(db).status(row)

    assert status.installed is True
    assert calls
    assert calls[0]["shell"] is False


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


def test_preflight_defaults_to_echo(db, test_space, test_user):
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
    assert result.adapter_type == "echo"
    assert result.executable is True


def test_preflight_and_execution_agree_for_version_runtime_adapter_id(db, test_space, test_user):
    from app.runs.adapter_resolution import resolve_runtime_adapter
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    adapter = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="capability")
    version.runtime_adapter_id = adapter.id
    run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=agent)
    db.flush()

    preflight = PreflightService(db).check(PreflightRequest(agent_id=agent.id, adapter_type="echo"), test_space.id)
    resolved = resolve_runtime_adapter(db, run=run, version=version, policy=version.runtime_policy_json)
    assert preflight.adapter_type == resolved.adapter_type == "capability"


def test_preflight_runtime_adapter_executable_override_skips_default_path_warning(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    _mark_cli_profile_ready(monkeypatch)
    workspace = _workspace_for_worktree_preflight(db, space_id=test_space.id, tmp_path=tmp_path)
    exe = tmp_path / "custom-claude"
    exe.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
    exe.chmod(0o755)
    _path_with_git_only(tmp_path, monkeypatch)

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    adapter = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="claude_code")
    adapter.config_json = {"executable_path": str(exe)}
    version.runtime_adapter_id = adapter.id
    version.runtime_policy_json = {"risk_level": "high"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, workspace_id=workspace.id),
        test_space.id,
    )

    assert result.adapter_type == "claude_code"
    assert not any("not found in PATH" in warning for warning in result.warnings)
    assert result.warnings == []


def test_preflight_runtime_adapter_invalid_executable_override_warns(
    db, test_space, test_user, tmp_path, monkeypatch
):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    _mark_cli_profile_ready(monkeypatch)
    workspace = _workspace_for_worktree_preflight(db, space_id=test_space.id, tmp_path=tmp_path)
    _path_with_git_only(tmp_path, monkeypatch)

    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    adapter = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="claude_code")
    adapter.config_json = {"executable_path": str(tmp_path / "missing-claude")}
    version.runtime_adapter_id = adapter.id
    version.runtime_policy_json = {"risk_level": "high"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, workspace_id=workspace.id),
        test_space.id,
    )

    assert any("executable_not_found: executable_path override does not exist" in w for w in result.warnings)


def test_preflight_without_runtime_adapter_row_warns_for_missing_default_command(
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

    assert any("executable_not_found: 'claude' not found in PATH" in w for w in result.warnings)


def test_preflight_native_adapters_skip_cli_executable_detection(db, test_space, test_user, monkeypatch):
    from app.runs.preflight import PreflightRequest, PreflightService
    from tests.support import factories

    def fail_detection(*args, **kwargs):
        raise AssertionError("native adapters must not check CLI executables")

    monkeypatch.setattr("app.runs.preflight.resolve_executable_for_detection", fail_detection)
    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    version = _agent_version(db, agent)
    version.runtime_policy_json = {"risk_level": "low"}
    flag_modified(version, "runtime_policy_json")
    db.flush()

    echo = PreflightService(db).check(PreflightRequest(agent_id=agent.id), test_space.id)
    capability = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="capability"),
        test_space.id,
    )

    assert echo.adapter_type == "echo"
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
    run.adapter_type = "echo"
    db.flush()

    preflight = PreflightService(db).check(PreflightRequest(agent_id=agent.id, adapter_type="echo"), test_space.id)
    resolved = resolve_runtime_adapter(db, run=run, version=version, policy=version.runtime_policy_json)
    assert preflight.adapter_type == resolved.adapter_type == "echo"


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

    result = PreflightService(db).check(
        PreflightRequest(agent_id=agent.id, adapter_type="claude_code"),
        test_space.id,
    )
    assert any("file_access_adapter_requires_worktree_policy" in err for err in result.errors)

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


def test_runtime_status_credential_readiness_uses_profile_source_path(db, test_space, tmp_path, monkeypatch):
    from app.credentials.broker import CredentialBroker, CredentialProfile
    from app.runtime_adapters.service import RuntimeAdapterService

    broker = CredentialBroker(instance_root=str(tmp_path / "instance"))
    broker._profiles = {
        "claude_code/default": CredentialProfile(
            id="claude_code/default",
            runtime="claude_code",
            name="default",
            source_path=str(tmp_path / "missing-profile"),
            target_path="/home/agent/.claude",
        )
    }
    monkeypatch.setattr("app.credentials.broker.CredentialBroker", lambda: broker)

    missing = RuntimeAdapterService(db).detect_one("claude_code", space_id=test_space.id)
    assert missing.credential_ready is False

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    broker._profiles["claude_code/default"].source_path = str(profile_dir)
    ready = RuntimeAdapterService(db).detect_one("claude_code", space_id=test_space.id)
    assert ready.credential_ready is True


def test_runtime_status_is_space_scoped_and_prefers_runtime_adapter_id(db, cross_space_pair_db):
    from app.models import Run
    from app.runtime_adapters.service import RuntimeAdapterService
    from tests.support import factories

    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    user_a = cross_space_pair_db["user_a"].id
    user_b = cross_space_pair_db["user_b"].id
    adapter_a = factories.create_test_runtime_adapter(db, space_id=a, adapter_type="echo")
    adapter_a2 = factories.create_test_runtime_adapter(db, space_id=a, adapter_type="echo")
    adapter_b = factories.create_test_runtime_adapter(db, space_id=b, adapter_type="echo")
    agent_a = factories.create_test_agent(db, space_id=a, owner_user_id=user_a)
    agent_b = factories.create_test_agent(db, space_id=b, owner_user_id=user_b)
    run_a = factories.create_test_run(db, space_id=a, user_id=user_a, agent=agent_a)
    run_a.runtime_adapter_id = adapter_a.id
    run_a.adapter_type = "echo"
    run_a.status = "succeeded"
    run_b = factories.create_test_run(db, space_id=b, user_id=user_b, agent=agent_b)
    run_b.runtime_adapter_id = adapter_b.id
    run_b.adapter_type = "echo"
    run_b.status = "failed"
    db.flush()

    status_a = RuntimeAdapterService(db).status(adapter_a)
    assert status_a.last_run_status == "succeeded"
    status_a2 = RuntimeAdapterService(db).status(adapter_a2)
    assert status_a2.last_run_status is None
    assert status_a.configured_count == 2
    unconfigured = RuntimeAdapterService(db).detect_one("echo")
    assert unconfigured.last_run_status is None
    assert unconfigured.last_error_code is None

    detected = RuntimeAdapterService(db).detect_all(a)
    echo_detected = next(item for item in detected if item.adapter_type == "echo")
    assert echo_detected.configured_count == 2
    assert echo_detected.configured is False
    assert echo_detected.runtime_adapter_id is None
    assert echo_detected.last_run_status is None


def test_runtime_adapter_quota_and_health_are_independent(db, test_space):
    from app.runtime_adapters.service import RuntimeAdapterService
    from app.schemas import RuntimeAdapterCreate, RuntimeAdapterUpdate
    from pydantic import ValidationError

    svc = RuntimeAdapterService(db)
    row = svc.create(
        RuntimeAdapterCreate(
            adapter_type="echo",
            name="Echo",
            health_status="ok",
            quota_status="low",
        ),
        test_space.id,
    )
    assert row.health_status == "ok"
    assert row.quota_status == "low"
    updated = svc.update(row.id, test_space.id, RuntimeAdapterUpdate(quota_status="exhausted"))
    assert updated.health_status == "ok"
    assert updated.quota_status == "exhausted"
    updated = svc.update(row.id, test_space.id, RuntimeAdapterUpdate(health_status="warning"))
    assert updated.health_status == "warning"
    assert updated.quota_status == "exhausted"
    updated = svc.update(row.id, test_space.id, RuntimeAdapterUpdate(enabled=False))
    assert updated.enabled is False
    assert updated.health_status == "warning"
    updated = svc.update(row.id, test_space.id, RuntimeAdapterUpdate(health_status="disabled"))
    assert updated.health_status == "disabled"

    with pytest.raises(ValidationError):
        RuntimeAdapterCreate(adapter_type="echo", name="Bad", health_status="bad")
    with pytest.raises(ValidationError):
        RuntimeAdapterUpdate(quota_status="bad")

    planned = svc.create(
        RuntimeAdapterCreate(
            adapter_type="opencode",
            name="OpenCode",
            enabled=False,
            health_status="ok",
            quota_status="low",
        ),
        test_space.id,
    )
    assert planned.enabled is False
    assert planned.health_status == "unimplemented"
    assert planned.quota_status == "unknown"


def test_usage_provider_is_fallback_cached_and_instance_scoped(db, test_space, test_user, tmp_path, monkeypatch):
    from app.config import settings
    from app.runtime_adapters.service import RuntimeAdapterService
    from tests.support import factories

    monkeypatch.setattr(settings, "instance_root", str(tmp_path))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "quota-cache.json").write_text('{"remaining": 3}', encoding="utf-8")

    adapter_a = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="echo")
    adapter_b = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="echo")
    agent = factories.create_test_agent(db, space_id=test_space.id, owner_user_id=test_user.id)
    run_a = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=agent)
    run_a.adapter_type = "echo"
    run_a.runtime_adapter_id = adapter_a.id
    run_a.status = "succeeded"
    run_a.started_at = datetime.now(UTC)
    run_a.runtime_seconds = 2.5
    run_b = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id, agent=agent)
    run_b.adapter_type = "echo"
    run_b.runtime_adapter_id = adapter_b.id
    run_b.status = "succeeded"
    run_b.runtime_seconds = 9.0
    db.flush()

    usage_a = RuntimeAdapterService(db).usage(adapter_a)
    assert usage_a["runtime_adapter_id"] == adapter_a.id
    assert usage_a["run_count"] == 1
    assert usage_a["runtime_seconds"] == 2.5

    refreshed = RuntimeAdapterService(db).usage(adapter_a, refresh=True)
    assert refreshed["supports_usage_probe"] is False
    assert "warning" in refreshed

    claude = factories.create_test_runtime_adapter(db, space_id=test_space.id, adapter_type="claude_code")
    claude_usage = RuntimeAdapterService(db).usage(claude)
    assert claude_usage["cached_quota"] == {"remaining": 3}
    claude_refresh = RuntimeAdapterService(db).usage(claude, refresh=True)
    assert claude_refresh["warning"] == "live Claude quota probe is not available in this build"


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
