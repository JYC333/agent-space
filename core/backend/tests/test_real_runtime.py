"""Minimal real runtime adapter integration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from ulid import ULID

pytestmark = pytest.mark.canonical

from app.agents.agent_service import AgentService
from app.config import settings
from app.models import AgentVersion, Artifact, Credential, ModelProvider, RuntimeAdapter
from app.runs.artifact_persistence import (
    ArtifactPersistenceService,
    _ensure_under_root as _ensure_artifact_under_root,
)
from app.runs.execution import RunExecutionService
from app.runs.removed_runtime_token import obsolete_runtime_override_token
from app.runs.run_service import RunService
from app.runs.worktree_manager import isolated_run_workdir
from app.runtimes.adapters.anthropic_messages import _json_safe
from app.schemas import AgentCreate, RunCreate, TaskCreate, TaskRunCreateBody
from app.tasks.service import TaskService
from tests.conftest import SPACE, USER, ensure_workspace


def _new_id() -> str:
    return str(ULID())


def _seed_agent(db, **kwargs):
    return AgentService(db).create(
        AgentCreate(name=kwargs.pop("name", "P11 Agent"), **kwargs),
        requesting_user_id=USER,
    )


def test_echo_real_adapter_success(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="hello"), SPACE, USER)
    result = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert result.success is True
    assert result.stdout
    assert "hello" in result.stdout
    assert result.exit_code == 0
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.output_json.get("runtime_adapter_type") == "echo"


def test_structured_result_fields(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="x"), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.started_at is not None
    assert r.completed_at is not None
    assert r.stdout is not None
    assert r.stderr is not None


def test_adapter_not_configured(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "",
        },
    )
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_config_json = {}
    db.add(v)
    db.commit()
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "adapter_not_configured"
    db.refresh(run)
    assert run.status == "failed"
    assert run.error_json.get("error_code") == "adapter_not_configured"


def test_adapter_disabled(db):
    cred = Credential(
        id=_new_id(),
        space_id=SPACE,
        name="c",
        credential_type="api_key",
        secret_ref="ref",
    )
    db.add(cred)
    ra = RuntimeAdapter(
        id=_new_id(),
        space_id=SPACE,
        name="off",
        adapter_type="echo",
        enabled=False,
        config_json={},
    )
    db.add(ra)
    db.commit()
    agent = _seed_agent(db, runtime_policy_json={"risk_level": "low", "allowed_adapter_types": ["echo"]})
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_adapter_id = ra.id
    db.add(v)
    db.commit()
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "adapter_disabled"


def test_adapter_not_implemented(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["codex_cli"],
            "default_adapter_type": "codex_cli",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "adapter_not_implemented"


def test_adapter_type_disallowed(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "anthropic_messages",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "adapter_type_disallowed"


def test_model_provider_disallowed(db):
    cred = Credential(
        id=_new_id(),
        space_id=SPACE,
        name="c2",
        credential_type="api_key",
        secret_ref="ref2",
    )
    db.add(cred)
    mp_allowed = ModelProvider(
        id="mp-allowed-p11",
        space_id=SPACE,
        name="allowed",
        provider_type="test",
        credential_id=cred.id,
    )
    mp_other = ModelProvider(
        id="mp-other-p11",
        space_id=SPACE,
        name="other",
        provider_type="test",
        credential_id=cred.id,
    )
    db.add_all([mp_allowed, mp_other])
    db.commit()
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["echo"],
            "allowed_model_providers": ["mp-allowed-p11"],
            "default_adapter_type": "echo",
        },
    )
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.model_provider_id = mp_other.id
    db.add(v)
    db.commit()
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "model_provider_disallowed"


def test_app_source_tree_has_no_tests_package_imports():
    """Product code must not import the ``tests`` package."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    hits: list[str] = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("from tests.") or s.startswith("import tests."):
                hits.append(f"{path.relative_to(root.parent)}:{i}:{s}")
    assert not hits, f"Unexpected test-package imports: {hits}"


def test_runtime_registry_has_echo_and_anthropic_only():
    from app.runtimes.registry import _RUNTIME_ADAPTER_CLASSES

    assert set(_RUNTIME_ADAPTER_CLASSES.keys()) == {"echo", "anthropic_messages"}


def test_sandbox_one_shot_docker_not_implemented(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "critical",
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "echo",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "sandbox_one_shot_docker_not_implemented"


def test_worktree_sandbox_used_for_high_risk(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "high",
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "echo",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(prompt="wt"), SPACE, USER)
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.sandbox_path is None


def test_persisted_artifact_export_after_sandbox_cleanup(db, tmp_path, monkeypatch):
    root = tmp_path / "arts"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(root))
    sb = tmp_path / "sb"
    sb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "sandbox_root", str(sb))

    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "high",
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "echo",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(prompt="persist-me"), SPACE, USER)
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    db.refresh(run)
    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) >= 1
    art = arts[0]
    rel = art.storage_path
    assert rel
    persisted = (root / rel).resolve()
    assert persisted.is_file()
    worktrees = sb / "worktrees" / SPACE / run.id
    assert not worktrees.exists()


def test_taskrun_links_artifact(db):
    ensure_workspace(db, "ws-p11", SPACE, created_by_user_id=USER)
    agent = _seed_agent(db)
    task = TaskService(db).create(
        TaskCreate(title="t", assigned_agent_id=agent.id, workspace_id="ws-p11"),
        SPACE,
        USER,
    )
    _link, run = TaskService(db).create_queued_run_for_task(
        task.id, SPACE, USER, TaskRunCreateBody(prompt="linked")
    )
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    from app.models import TaskArtifact

    ta = (
        db.query(TaskArtifact)
        .filter(TaskArtifact.task_id == task.id, TaskArtifact.space_id == SPACE)
        .all()
    )
    assert len(ta) >= 1


def test_anthropic_credentials_missing(db):
    agent = _seed_agent(
        db,
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["anthropic_messages"],
            "default_adapter_type": "anthropic_messages",
        },
    )
    run = RunService(db).create_run(agent.id, RunCreate(prompt="hi"), SPACE, USER)
    with patch.object(settings, "anthropic_api_key", ""):
        r = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert r.success is False
    assert r.error_code == "credentials_missing"


def test_terminal_run_is_not_overwritten_by_preflight_failures(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="done"), SPACE, USER)
    first = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert first.success is True

    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_policy_json = {
        "risk_level": "critical",
        "allowed_adapter_types": ["echo"],
        "default_adapter_type": "echo",
    }
    db.add(v)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    assert exc.value.status_code == 409
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.error_json is None


def test_terminal_re_execute_does_not_call_adapter_resolution(db):
    """Terminal runs must 409 before adapter resolution or sandbox setup can mutate the row."""
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="t2"), SPACE, USER)
    assert RunExecutionService(db).execute_run(run.id, space_id=SPACE).success is True

    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_adapter_id = None
    v.runtime_config_json = {}
    v.runtime_policy_json = {
        "risk_level": "low",
        "allowed_adapter_types": ["echo"],
        "default_adapter_type": "",
    }
    db.add(v)
    db.commit()

    with patch("app.runs.execution.resolve_runtime_adapter") as resolve_adapters:
        with patch("app.runs.execution.execution_workspace") as exec_ws:
            with pytest.raises(HTTPException) as exc:
                RunExecutionService(db).execute_run(run.id, space_id=SPACE)
            assert exc.value.status_code == 409
            resolve_adapters.assert_not_called()
            exec_ws.assert_not_called()
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.error_json is None


def test_obsolete_runtime_override_returns_runtime_removed(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="probe?"), SPACE, USER)
    r = RunExecutionService(db).execute_run(
        run.id, space_id=SPACE, runtime=obsolete_runtime_override_token()
    )
    assert r.success is False
    assert r.error_code == "runtime_removed"
    db.refresh(run)
    assert run.status == "queued"
    assert run.error_json is None


def test_job_payload_obsolete_runtime_override_raises(db, db_engine, monkeypatch):
    """agent_run jobs reject obsolete ``payload.runtime`` before touching the Run."""
    monkeypatch.setattr("app.db.SessionLocal", sessionmaker(bind=db_engine))

    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(prompt="job-obsolete"), SPACE, USER)
    job = SimpleNamespace(
        payload={"run_id": run.id, "runtime": obsolete_runtime_override_token()},
        space_id=SPACE,
        user_id=USER,
    )
    from app.jobs.handlers import handle_agent_run

    with pytest.raises(ValueError, match="runtime_removed"):
        handle_agent_run(job)
    db.refresh(run)
    assert run.status == "queued"
    assert run.error_json is None


def test_anthropic_adapter_log_values_are_json_safe():
    class UsageObject:
        def model_dump(self):
            return {"input_tokens": 3, "nested": SimpleNamespace(value="x")}

    converted = _json_safe({"usage": UsageObject(), "stop_reason": SimpleNamespace(name="end")})
    assert converted == {
        "usage": {"input_tokens": 3, "nested": "namespace(value='x')"},
        "stop_reason": "namespace(name='end')",
    }
    json.dumps(converted)


def test_artifact_and_worktree_paths_reject_traversal(tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    sandbox_root = tmp_path / "sandbox"
    artifact_root.mkdir()
    sandbox_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(artifact_root))
    monkeypatch.setattr(settings, "sandbox_root", str(sandbox_root))

    with pytest.raises(ValueError):
        _ensure_artifact_under_root((artifact_root / ".." / "escape.txt").resolve(), artifact_root.resolve())

    with pytest.raises(ValueError):
        with isolated_run_workdir("../escape", "run"):
            pass

    assert not (tmp_path / "escape").exists()


def test_artifact_persistence_service_rejects_path_escape(db, tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(root))

    run = MagicMock()
    run.space_id = ".."
    run.id = "bad_run_id"

    with patch("app.runs.artifact_persistence._new_id", return_value="artid"):
        with pytest.raises(ValueError, match="artifact path escapes"):
            ArtifactPersistenceService(db).persist_text_file(
                run=run, text="leak", title="t"
            )
