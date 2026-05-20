from __future__ import annotations

from pathlib import Path

import pytest
from ulid import ULID

from app.capabilities.enabled_store import load_enabled_external_capabilities
from app.capabilities.registry import CapabilityRegistry
from app.config import settings
from app.models import ActivityRecord, Artifact, Run, RunStep
from app.runs.execution import RunExecutionService
from app.runs.run_service import RunService
from app.runtimes.base import RuntimeExecutionContext
from app.runtimes.registry import is_adapter_type_implemented
from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
from app.schemas import RunCreate
from tests.support import factories


def _runtime_ctx(capability_id: str | None, prompt: str = "") -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        run_id="run-1",
        space_id="space-1",
        prompt=prompt,
        mode="live",
        sandbox_cwd=None,
        model_name=None,
        system_prompt=None,
        adapter_config={},
        capability_id=capability_id,
    )


def _write_capability(
    root: Path,
    cap_id: str,
    *,
    module_dir: str | None = None,
    entrypoint: str | None = None,
    enabled: bool = True,
    permissions: str | None = None,
    main_py: str = "def execute(context):\n    return {'status': 'succeeded', 'output': {}}\n",
) -> Path:
    package_dir = module_dir or cap_id
    cap_dir = root / package_dir
    cap_dir.mkdir(parents=True)
    (cap_dir / "main.py").write_text(main_py, encoding="utf-8")
    entrypoint_yaml = entrypoint if entrypoint is not None else (
        "entrypoint:\n"
        "  type: python_module\n"
        f"  module: capabilities.{package_dir}.main\n"
        "  function: execute\n"
    )
    permissions_yaml = permissions if permissions is not None else (
        "permissions:\n"
        "  network:\n"
        "    allow: []\n"
        "  filesystem:\n"
        "    read: []\n"
        "    write: []\n"
        "  subprocess:\n"
        "    allow: false\n"
    )
    (cap_dir / "capability.yaml").write_text(
        "\n".join([
            f"id: {cap_id}",
            f"name: {cap_id}",
            "version: 0.1.0",
            "description: test capability",
            f"enabled: {str(enabled).lower()}",
            entrypoint_yaml.rstrip(),
            permissions_yaml.rstrip(),
        ]) + "\n",
        encoding="utf-8",
    )
    return cap_dir


def _create_external_capability_workspace(
    db,
    *,
    tmp_path: Path,
    space_id: str,
    user_id: str,
    workspace_type: str = "capability_library",
    metadata_json: dict | None = None,
    cap_id: str = "external.echo",
    module_dir: str = "external_echo",
    manifest_enabled: bool = True,
):
    workspace_root = tmp_path / f"workspace-{module_dir}"
    capability_root = workspace_root / "capabilities"
    _write_capability(
        capability_root,
        cap_id,
        module_dir=module_dir,
        enabled=manifest_enabled,
        main_py=(
            "def execute(context):\n"
            "    data = dict(context.get('input') or {})\n"
            "    return {\n"
            "        'status': 'succeeded',\n"
            "        'output': {'echoed_input': data},\n"
            "        'artifacts': [{\n"
            "            'artifact_type': 'external.echo.result.v1',\n"
            "            'title': 'External Echo Result',\n"
            "            'content': 'External echo capability executed.',\n"
            "            'metadata_json': {'echoed_input': data},\n"
            "        }],\n"
            "    }\n"
        ),
    )
    workspace = factories.create_test_workspace(
        db,
        space_id=space_id,
        root_path=str(workspace_root),
        name=f"workspace-{module_dir}",
        created_by_user_id=user_id,
        workspace_type=workspace_type,
        metadata_json=metadata_json if metadata_json is not None else {
            "capability_roots": ["capabilities"],
        },
        commit=False,
    )
    return workspace, capability_root


def _fresh_space_user(db, label: str):
    space_id = str(ULID())
    factories.create_test_space(db, space_id=space_id, name=label)
    user = factories.create_test_user(db, space_id=space_id, display_name=f"{label} user")
    return space_id, user


def test_capability_manifest_entrypoint_metadata_loads():
    registry = CapabilityRegistry(None)
    result = registry.reload()

    assert result["failed"] == 0
    cap = registry.get("agent.echo")
    assert cap is not None
    assert cap.entrypoint == {
        "type": "python_module",
        "module": "capabilities.agent_echo.main",
        "function": "execute",
    }
    assert cap.manifest_json["outputs"]["artifact_types"] == ["agent.echo.result.v1"]

    reflector = registry.get("memory.reflect")
    assert reflector is not None
    assert reflector.entrypoint == {
        "type": "python_module",
        "module": "capabilities.memory_reflect.main",
        "function": "execute",
    }
    assert reflector.manifest_json["outputs"]["artifact_types"] == ["memory.reflection.v1"]


def test_capability_adapter_registered():
    assert is_adapter_type_implemented("capability")


@pytest.mark.parametrize(
    ("cap_id", "entrypoint", "permissions", "enabled", "expected_code"),
    [
        ("no_entrypoint", "", None, True, "capability_entrypoint_missing"),
        (
            "shell_entrypoint",
            "entrypoint:\n  type: shell\n  command: echo unsafe\n",
            None,
            True,
            "capability_entrypoint_unsupported",
        ),
        (
            "subprocess_allowed",
            None,
            "permissions:\n  subprocess:\n    allow: true\n",
            True,
            "capability_permissions_unsupported",
        ),
        ("disabled_cap", None, None, False, "capability_disabled"),
    ],
)
def test_capability_adapter_rejects_invalid_manifest_metadata(
    tmp_path,
    monkeypatch,
    cap_id,
    entrypoint,
    permissions,
    enabled,
    expected_code,
):
    cap_root = tmp_path / "capabilities"
    _write_capability(
        cap_root,
        cap_id,
        entrypoint=entrypoint,
        permissions=permissions,
        enabled=enabled,
    )
    monkeypatch.setattr(settings, "capabilities_dir", str(cap_root))

    result = CapabilityRuntimeAdapter().execute(_runtime_ctx(cap_id))

    assert result.success is False
    assert result.error_code == expected_code


def test_capability_adapter_rejects_missing_and_unknown_capability_id(tmp_path, monkeypatch):
    cap_root = tmp_path / "capabilities"
    cap_root.mkdir()
    monkeypatch.setattr(settings, "capabilities_dir", str(cap_root))

    missing = CapabilityRuntimeAdapter().execute(_runtime_ctx(None))
    unknown = CapabilityRuntimeAdapter().execute(_runtime_ctx("unknown"))

    assert missing.success is False
    assert missing.error_code == "capability_id_missing"
    assert unknown.success is False
    assert unknown.error_code == "capability_not_found"


def test_capability_function_exception_returns_failed_result(tmp_path, monkeypatch):
    cap_root = tmp_path / "capabilities"
    _write_capability(
        cap_root,
        "boom",
        main_py="def execute(context):\n    raise RuntimeError('boom from capability')\n",
    )
    monkeypatch.setattr(settings, "capabilities_dir", str(cap_root))

    result = CapabilityRuntimeAdapter().execute(_runtime_ctx("boom"))

    assert result.success is False
    assert result.error_code == "capability_execution_error"
    assert "boom from capability" in result.error_text


def test_memory_reflect_capability_skeleton_executes():
    result = CapabilityRuntimeAdapter().execute(
        _runtime_ctx(
            "memory.reflect",
            '{"messages": [{"role": "user", "content": "remember this"}]}',
        )
    )

    assert result.success is True
    assert result.output_json["capability_id"] == "memory.reflect"
    assert result.output_json["output"]["message_count"] == 1
    assert result.output_json["artifacts"][0]["artifact_type"] == "memory.reflection.v1"


def test_external_capability_workspace_discovery_sets_source_metadata(db, tmp_path):
    space_id, user = _fresh_space_user(db, "external-discovery")
    workspace, capability_root = _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    db.commit()

    registry = CapabilityRegistry(db)
    result = registry.reload(space_id=space_id)
    cap = registry.get("external.echo")

    assert result["failed"] == 0
    assert cap is not None
    assert cap.source == "external_workspace"
    assert cap.workspace_id == workspace.id
    assert cap.root_path == str(capability_root.resolve())
    assert cap.manifest_path and cap.manifest_path.endswith("capability.yaml")
    assert cap.enabled is False


def test_ordinary_workspace_is_not_scanned_for_capabilities(db, tmp_path):
    space_id, user = _fresh_space_user(db, "ordinary-workspace")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
        workspace_type="project",
    )
    db.commit()

    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)

    assert registry.get("external.echo") is None


def test_metadata_json_workspace_type_is_not_used_for_discovery(db, tmp_path):
    """capability_library must come from Workspace.workspace_type, not metadata_json."""
    space_id, user = _fresh_space_user(db, "metadata-workspace-type")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
        workspace_type="project",
        metadata_json={
            "workspace_type": "capability_library",
            "capability_roots": ["capabilities"],
        },
    )
    db.commit()

    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)

    assert registry.get("external.echo") is None


def test_external_capability_enable_persists_across_registry_reload(db, tmp_path, monkeypatch):
    instance_root = tmp_path / "instance-enable"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    space_id, user = _fresh_space_user(db, "persist-enable")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    db.commit()

    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)
    assert registry.get("external.echo").enabled is False
    assert registry.set_enabled("external.echo", True) is not None

    reloaded = CapabilityRegistry(db)
    reloaded.reload(space_id=space_id)
    cap = reloaded.get("external.echo")

    assert cap is not None
    assert cap.enabled is True
    assert "external.echo" in load_enabled_external_capabilities(str(instance_root))


def test_external_capability_disable_persists_across_registry_reload(db, tmp_path, monkeypatch):
    instance_root = tmp_path / "instance-disable"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    space_id, user = _fresh_space_user(db, "persist-disable")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    db.commit()

    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)
    registry.set_enabled("external.echo", True)
    registry.set_enabled("external.echo", False)

    reloaded = CapabilityRegistry(db)
    reloaded.reload(space_id=space_id)
    cap = reloaded.get("external.echo")

    assert cap is not None
    assert cap.enabled is False
    assert "external.echo" not in load_enabled_external_capabilities(str(instance_root))


def test_persisted_enabled_external_capability_missing_from_discovery_is_ignored(
    db,
    tmp_path,
    monkeypatch,
):
    instance_root = tmp_path / "instance-ghost"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    settings_path = instance_root / "config" / "settings.yaml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "capabilities:\n  enabled_external_capabilities:\n    - ghost.external\n",
        encoding="utf-8",
    )

    space_id, user = _fresh_space_user(db, "ghost-external")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    db.commit()

    registry = CapabilityRegistry(db)
    result = registry.reload(space_id=space_id)

    assert result["failed"] == 0
    assert registry.get("ghost.external") is None
    assert registry.get("external.echo") is not None
    assert registry.get("external.echo").enabled is False


def test_newly_discovered_external_capability_is_not_auto_enabled(db, tmp_path, monkeypatch):
    instance_root = tmp_path / "instance-new-external"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    space_id, user = _fresh_space_user(db, "new-external")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
        cap_id="external.echo",
        module_dir="external_echo",
    )
    db.commit()

    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)
    registry.set_enabled("external.echo", True)

    workspace_root = tmp_path / "workspace-external_echo_two"
    capability_root = workspace_root / "capabilities"
    _write_capability(
        capability_root,
        "external.echo.two",
        module_dir="external_echo_two",
    )
    factories.create_test_workspace(
        db,
        space_id=space_id,
        root_path=str(workspace_root),
        name="workspace-external_echo_two",
        created_by_user_id=user.id,
        workspace_type="capability_library",
        metadata_json={"capability_roots": ["capabilities"]},
        commit=True,
    )

    reloaded = CapabilityRegistry(db)
    reloaded.reload(space_id=space_id)

    assert reloaded.get("external.echo").enabled is True
    assert reloaded.get("external.echo.two") is not None
    assert reloaded.get("external.echo.two").enabled is False


def test_set_enabled_does_not_persist_unknown_capability(db):
    registry = CapabilityRegistry(db)
    registry.reload()

    assert registry.set_enabled("unknown.external", True) is None
    assert "unknown.external" not in load_enabled_external_capabilities()


def test_builtin_capability_enabled_state_unchanged_across_registry_reload(tmp_path, monkeypatch):
    cap_root = tmp_path / "capabilities"
    _write_capability(cap_root, "builtin.toggle", enabled=False)
    monkeypatch.setattr(settings, "capabilities_dir", str(cap_root))

    registry = CapabilityRegistry(None)
    registry.reload()
    assert registry.get("builtin.toggle").enabled is False

    registry.set_enabled("builtin.toggle", True)
    assert registry.get("builtin.toggle").enabled is True

    reloaded = CapabilityRegistry(None)
    reloaded.reload()
    assert reloaded.get("builtin.toggle").enabled is True
    assert "builtin.toggle" not in load_enabled_external_capabilities(str(tmp_path / "unused"))


@pytest.mark.parametrize(
    "capability_roots",
    [
        ["/absolute/capabilities"],
        ["../capabilities"],
    ],
)
def test_invalid_external_capability_roots_are_rejected(
    db,
    tmp_path,
    capability_roots,
):
    space_id, user = _fresh_space_user(db, "invalid-capability-root")
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
        metadata_json={"capability_roots": capability_roots},
    )
    db.commit()

    registry = CapabilityRegistry(db)
    result = registry.reload(space_id=space_id)

    assert registry.get("external.echo") is None
    assert result["failed"] == 1
    assert result["details"][-1]["source"] == "external_workspace"


def test_external_capability_root_symlink_outside_workspace_is_rejected(
    db,
    tmp_path,
):
    space_id, user = _fresh_space_user(db, "symlink-capability-root")
    workspace_root = tmp_path / "workspace-with-link"
    outside_root = tmp_path / "outside"
    outside_cap_root = outside_root / "capabilities"
    _write_capability(
        outside_cap_root,
        "external.echo",
        module_dir="external_echo",
    )
    workspace_root.mkdir(parents=True)
    (workspace_root / "capabilities").symlink_to(outside_cap_root, target_is_directory=True)
    factories.create_test_workspace(
        db,
        space_id=space_id,
        root_path=str(workspace_root),
        name="linked-capability-library",
        created_by_user_id=user.id,
        workspace_type="capability_library",
        metadata_json={"capability_roots": ["capabilities"]},
        commit=True,
    )

    registry = CapabilityRegistry(db)
    result = registry.reload(space_id=space_id)

    assert registry.get("external.echo") is None
    assert result["failed"] == 1
    assert "not under" in result["details"][-1]["errors"][0]


def test_external_capability_defaults_disabled_and_fails_execution(
    db,
    tmp_path,
    monkeypatch,
):
    instance_root = tmp_path / "instance-disabled-exec"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    space_id, user = _fresh_space_user(db, "disabled-external-capability")
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces-root"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.adapter_type = "capability"
    run.capability_id = "external.echo"
    db.commit()

    result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    assert result.success is False
    assert result.error_code == "capability_disabled"


def test_enabled_external_capability_executes_through_run_service(
    db,
    tmp_path,
    monkeypatch,
):
    instance_root = tmp_path / "instance-exec"
    monkeypatch.setattr(settings, "instance_root", str(instance_root))
    space_id, user = _fresh_space_user(db, "enabled-external-capability")
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces-root"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    _create_external_capability_workspace(
        db,
        tmp_path=tmp_path,
        space_id=space_id,
        user_id=user.id,
    )
    registry = CapabilityRegistry(db)
    registry.reload(space_id=space_id)
    assert registry.set_enabled("external.echo", True) is not None

    project = factories.create_test_project(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.adapter_type = "capability"
    run.capability_id = "external.echo"
    run.project_id = project.id
    run.prompt = '{"message": "hello external"}'
    db.commit()

    result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    assert result.success is True
    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.run_id == run.id,
            Artifact.artifact_type == "external.echo.result.v1",
        )
        .one()
    )
    assert artifact.project_id == project.id
    assert artifact.title == "External Echo Result"
    assert artifact.metadata_json == {"echoed_input": {"message": "hello external"}}


def test_capability_run_executes_echo_and_materializes_artifact_activity(
    db,
    test_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    space_id = test_user.space_id
    user = test_user
    project = factories.create_test_project(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.adapter_type = "capability"
    run.capability_id = "agent.echo"
    run.project_id = project.id
    run.prompt = '{"query": "attention mechanisms"}'
    db.commit()

    result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    assert result.success is True
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "succeeded"
    assert run_row.output_json["runtime_adapter_type"] == "capability"
    adapter_output = run_row.output_json["output_json"]
    assert adapter_output["capability_id"] == "agent.echo"
    assert adapter_output["output"]["echoed_input"] == {"query": "attention mechanisms"}

    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.run_id == run.id,
            Artifact.artifact_type == "agent.echo.result.v1",
        )
        .one()
    )
    assert artifact.project_id == project.id
    assert artifact.title == "Echo Result"
    assert artifact.content == "Echo capability executed."
    assert artifact.metadata_json == {"echoed_input": {"query": "attention mechanisms"}}

    activity = (
        db.query(ActivityRecord)
        .filter(
            ActivityRecord.source_run_id == run.id,
            ActivityRecord.activity_type == "capability_event",
        )
        .one()
    )
    assert activity.project_id == project.id
    assert activity.source_kind == "run_event"
    assert activity.payload_json == {"capability_id": "agent.echo"}

    step_types = {
        s.step_type
        for s in db.query(RunStep).filter(RunStep.run_id == run.id).all()
    }
    assert {"runtime_selected", "adapter_started", "completed"}.issubset(step_types)


def test_capability_run_missing_capability_id_fails_clearly(db, test_user):
    space_id = test_user.space_id
    user = test_user
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.adapter_type = "capability"
    db.commit()

    result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

    assert result.success is False
    assert result.error_code == "capability_id_missing"
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "failed"
    assert run_row.error_json["error_code"] == "capability_id_missing"


def test_run_service_rejects_cross_space_project_for_capability_run(db):
    space_a = str(ULID())
    space_b = str(ULID())
    factories.create_test_space(db, space_id=space_a, name="Capability A")
    factories.create_test_space(db, space_id=space_b, name="Capability B")
    user_a = factories.create_test_user(db, space_id=space_a, display_name="Capability User A")
    user_b = factories.create_test_user(db, space_id=space_b, display_name="Capability User B")
    foreign_project = factories.create_test_project(
        db,
        space_id=space_b,
        owner_user_id=user_b.id,
        commit=False,
    )
    agent = factories.create_test_agent(
        db,
        space_id=space_a,
        owner_user_id=user_a.id,
        commit=False,
    )
    db.commit()

    with pytest.raises(Exception) as exc:
        RunService(db).create_run(
            agent_id=agent.id,
            data=RunCreate(
                run_type="workflow",
                adapter_type="capability",
                capability_id="agent.echo",
                project_id=foreign_project.id,
            ),
            space_id=space_a,
            user_id=user_a.id,
        )

    assert "not found in space" in str(exc.value)
