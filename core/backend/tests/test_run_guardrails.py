"""Guardrails, runtime policy hooks, and integration polish."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from ulid import ULID

pytestmark = pytest.mark.canonical

from app.agents.agent_service import AgentService
from app.models import Agent, AgentVersion, Artifact, BoardColumn, MemoryEntry, Run
from app.runs.execution import RunExecutionService
from app.runs.removed_runtime_token import obsolete_runtime_override_token
from app.runs.run_service import RunService
from app.runs.runtime_policy import compute_runtime_policy_decision, required_sandbox_level_for_risk
from app.schemas import AgentCreate, RunCreate, TaskCreate, TaskRunCreateBody, TaskUpdate
from app.tasks.service import TaskService
from tests.conftest import SPACE, USER, ensure_space, ensure_user

AUTH = f"space_id={SPACE}&user_id={USER}"


def _new_id() -> str:
    return str(ULID())


def _seed_agent(db, *, name: str = "P10 Agent", **kwargs) -> Agent:
    return AgentService(db).create(
        AgentCreate(name=name, **kwargs),
        requesting_user_id=USER,
    )


# ---------------------------------------------------------------------------
# Unit: runtime policy / sandbox mapping
# ---------------------------------------------------------------------------


def test_required_sandbox_level_mapping():
    assert required_sandbox_level_for_risk("low") == "none"
    assert required_sandbox_level_for_risk("medium") == "dry_run"
    assert required_sandbox_level_for_risk("high") == "worktree"
    assert required_sandbox_level_for_risk("critical") == "one_shot_docker"


def test_compute_runtime_policy_decision_defaults(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    v = db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).one()
    d = compute_runtime_policy_decision(run=run, version=v)
    assert d.required_sandbox_level == "dry_run"  # DEFAULT_RUNTIME_POLICY risk medium
    assert d.policy_snapshot["risk_level"] == "medium"


# ---------------------------------------------------------------------------
# Delegation guardrails (RunService)
# ---------------------------------------------------------------------------


def test_root_run_delegation_depth_zero(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    assert run.parent_run_id is None
    assert run.delegation_depth == 0


def test_child_run_delegation_depth_parent_plus_one(db):
    a1 = _seed_agent(db, name="P10 A1")
    a2 = _seed_agent(db, name="P10 A2")
    parent = RunService(db).create_run(a1.id, RunCreate(), SPACE, USER)
    child = RunService(db).create_run(
        a2.id,
        RunCreate(
            trigger_origin="parent_run",
            parent_run_id=parent.id,
            instructed_by_agent_id=a1.id,
        ),
        SPACE,
        USER,
    )
    assert child.parent_run_id == parent.id
    assert child.delegation_depth == 1
    assert child.instructed_by_agent_id == a1.id


def test_max_delegation_depth_rejected(db):
    a1 = _seed_agent(
        db,
        name="Shallow",
        runtime_policy_json={
            "can_delegate": True,
            "max_delegation_depth": 1,
            "allowed_adapter_types": ["echo"],
            "risk_level": "low",
        },
    )
    a2 = _seed_agent(db, name="B")
    a3 = _seed_agent(db, name="C")
    parent = RunService(db).create_run(a1.id, RunCreate(adapter_type="echo"), SPACE, USER)
    child = RunService(db).create_run(
        a2.id,
        RunCreate(
            trigger_origin="parent_run",
            parent_run_id=parent.id,
            instructed_by_agent_id=a1.id,
            adapter_type="echo",
        ),
        SPACE,
        USER,
    )
    assert child.delegation_depth == 1
    with pytest.raises(HTTPException) as ei:
        RunService(db).create_run(
            a3.id,
            RunCreate(
                trigger_origin="parent_run",
                parent_run_id=child.id,
                instructed_by_agent_id=a1.id,
                adapter_type="echo",
            ),
            SPACE,
            USER,
        )
    assert ei.value.status_code == 403


def test_cross_space_parent_run_rejected(db):
    ensure_space(db, "space-x10", "SX")
    ensure_user(db, "ux10", "space-x10")
    a_other = AgentService(db).create(
        AgentCreate(name="Other", space_id="space-x10"),
        requesting_user_id="ux10",
    )
    parent = RunService(db).create_run(
        a_other.id,
        RunCreate(),
        "space-x10",
        "ux10",
    )
    a_local = _seed_agent(db, name="Local")
    with pytest.raises(HTTPException) as ei:
        RunService(db).create_run(
            a_local.id,
            RunCreate(parent_run_id=parent.id, trigger_origin="parent_run"),
            SPACE,
            USER,
        )
    assert ei.value.status_code == 400
    assert "Cross-space" in ei.value.detail


# ---------------------------------------------------------------------------
# Task guardrails
# ---------------------------------------------------------------------------


def test_task_max_runs_enforced_by_taskrun_count(db):
    agent = _seed_agent(db)
    tsvc = TaskService(db)
    task = tsvc.create(
        TaskCreate(title="Limited", assigned_agent_id=agent.id, max_runs=1),
        SPACE,
        USER,
    )
    tsvc.create_queued_run_for_task(task.id, SPACE, USER, TaskRunCreateBody())
    with pytest.raises(HTTPException) as ei:
        tsvc.create_queued_run_for_task(task.id, SPACE, USER, TaskRunCreateBody())
    assert ei.value.status_code == 400
    assert "max_runs" in ei.value.detail


def test_task_assigned_agent_mismatch_rejected(db):
    a1 = _seed_agent(db, name="TA1")
    a2 = _seed_agent(db, name="TA2")
    tsvc = TaskService(db)
    task = tsvc.create(
        TaskCreate(title="Owned", assigned_agent_id=a1.id),
        SPACE,
        USER,
    )
    with pytest.raises(HTTPException) as ei:
        tsvc.create_queued_run_for_task(
            task.id,
            SPACE,
            USER,
            TaskRunCreateBody(agent_id=a2.id),
        )
    assert ei.value.status_code == 400

    tsvc.update(
        task.id,
        SPACE,
        TaskUpdate(policy_json={"allow_assigned_agent_override": True}),
    )
    _link, run = tsvc.create_queued_run_for_task(
        task.id,
        SPACE,
        USER,
        TaskRunCreateBody(agent_id=a2.id),
    )
    assert run.agent_id == a2.id


# ---------------------------------------------------------------------------
# Execution policy (RunExecutionService + real adapters)
# ---------------------------------------------------------------------------


def test_obsolete_runtime_override_returns_runtime_removed(db):
    agent = _seed_agent(
        db,
        name="NoStubOverride",
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["echo"],
        },
    )
    run = RunService(db).create_run(
        agent.id,
        RunCreate(adapter_type="echo"),
        SPACE,
        USER,
    )
    r = RunExecutionService(db).execute_run(
        run.id, space_id=SPACE, runtime=obsolete_runtime_override_token()
    )
    assert r.success is False
    assert r.error_code == "runtime_removed"


def test_execute_sets_required_sandbox_level_and_policy_snapshot(db):
    agent = _seed_agent(
        db,
        name="Risky",
        runtime_policy_json={
            "risk_level": "high",
            "allowed_adapter_types": ["echo"],
        },
    )
    run = RunService(db).create_run(
        agent.id,
        RunCreate(adapter_type="echo"),
        SPACE,
        USER,
    )
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    db.expire_all()
    r = db.query(Run).filter(Run.id == run.id).one()
    assert r.required_sandbox_level == "worktree"
    dec = r.output_json.get("runtime_policy_decision")
    assert dec is not None
    assert dec["risk_level"] == "high"
    assert dec["required_sandbox_level"] == "worktree"


def test_runtime_policy_snapshot_includes_allowed_lists_when_set(db):
    agent = _seed_agent(
        db,
        name="PolicyLists",
        runtime_policy_json={
            "risk_level": "low",
            "allowed_adapter_types": ["echo"],
            "allowed_model_providers": ["mp-x"],
        },
    )
    run = RunService(db).create_run(
        agent.id,
        RunCreate(adapter_type="echo"),
        SPACE,
        USER,
    )
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    db.expire_all()
    r = db.query(Run).filter(Run.id == run.id).one()
    dec = r.output_json.get("runtime_policy_decision")
    assert dec["allowed_adapter_types"] == ["echo"]
    assert dec["allowed_model_providers"] == ["mp-x"]


def test_no_active_memory_entry_during_live_echo_execution(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    before = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    after = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    assert before == after


def test_no_active_memory_entry_during_dry_run_echo_execution(db):
    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(mode="dry_run"), SPACE, USER)
    before = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    RunExecutionService(db).execute_run(run.id, space_id=SPACE)
    after = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    assert before == after


# ---------------------------------------------------------------------------
# HTTP / E2E flows
# ---------------------------------------------------------------------------


def test_echo_runtime_e2e_board_task_run_artifact_export_home(client, db):
    agent = _seed_agent(db)
    br = client.post(f"/api/v1/boards?{AUTH}", json={"name": "P10 Board", "create_default_columns": True})
    assert br.status_code == 201
    board_id = br.json()["id"]
    inbox = (
        db.query(BoardColumn)
        .filter(BoardColumn.board_id == board_id, BoardColumn.status_key == "inbox")
        .one()
    )
    tr = client.post(
        f"/api/v1/tasks?{AUTH}",
        json={
            "title": "P10 task",
            "board_id": board_id,
            "column_id": inbox.id,
            "assigned_agent_id": agent.id,
        },
    )
    assert tr.status_code == 201
    task_id = tr.json()["id"]

    rr = client.post(f"/api/v1/tasks/{task_id}/runs?{AUTH}", json={})
    assert rr.status_code == 201
    run_id = rr.json()["id"]

    ex = client.post(f"/api/v1/runs/{run_id}/execute?{AUTH}")
    assert ex.status_code == 200
    body = ex.json()
    assert body["status"] == "succeeded"
    assert body.get("required_sandbox_level") is not None

    arts = client.get(f"/api/v1/runs/{run_id}/artifacts?{AUTH}")
    assert arts.status_code == 200
    assert arts.json()["total"] >= 1
    art_id = arts.json()["items"][0]["id"]
    exp = client.get(f"/api/v1/artifacts/{art_id}/export?{AUTH}")
    assert exp.status_code == 200

    task_arts = client.get(f"/api/v1/tasks/{task_id}/artifacts?{AUTH}")
    assert task_arts.status_code == 200
    assert task_arts.json()["total"] >= 1

    home = client.get(f"/api/v1/home/summary?{AUTH}")
    assert home.status_code == 200
    h = home.json()
    assert any(x["id"] == run_id for x in h["recent_runs"])


def test_dry_run_e2e_echo_preview_outputs_no_memory_write(client, db):
    agent = _seed_agent(db)
    br = client.post(f"/api/v1/boards?{AUTH}", json={"name": "Dry B", "create_default_columns": True})
    assert br.status_code == 201
    board_id = br.json()["id"]
    inbox = (
        db.query(BoardColumn)
        .filter(BoardColumn.board_id == board_id, BoardColumn.status_key == "inbox")
        .one()
    )
    tr = client.post(
        f"/api/v1/tasks?{AUTH}",
        json={
            "title": "Dry task",
            "board_id": board_id,
            "column_id": inbox.id,
            "assigned_agent_id": agent.id,
        },
    )
    assert tr.status_code == 201
    task_id = tr.json()["id"]
    rr = client.post(
        f"/api/v1/tasks/{task_id}/runs?{AUTH}",
        json={"mode": "dry_run"},
    )
    assert rr.status_code == 201
    run_id = rr.json()["id"]
    before = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    ex = client.post(f"/api/v1/runs/{run_id}/execute?{AUTH}")
    assert ex.status_code == 200
    after = db.query(MemoryEntry).filter(MemoryEntry.space_id == SPACE, MemoryEntry.status == "active").count()
    assert before == after

    arts = client.get(f"/api/v1/tasks/{task_id}/artifacts?{AUTH}")
    assert arts.status_code == 200
    assert len(arts.json()["items"]) >= 1
    art = db.query(Artifact).filter(Artifact.run_id == run_id).one()
    assert art.preview is True


def test_post_agent_runs_delegation_via_api(client, db):
    a1 = _seed_agent(db, name="API parent")
    a2 = _seed_agent(db, name="API child")
    pr = client.post(
        f"/api/v1/agents/{a1.id}/runs?{AUTH}",
        json={"adapter_type": "echo"},
    )
    assert pr.status_code == 201
    parent_id = pr.json()["id"]
    ch = client.post(
        f"/api/v1/agents/{a2.id}/runs?{AUTH}",
        json={
            "trigger_origin": "parent_run",
            "parent_run_id": parent_id,
            "instructed_by_agent_id": a1.id,
            "adapter_type": "echo",
        },
    )
    assert ch.status_code == 201
    assert ch.json()["delegation_depth"] == 1
    assert ch.json()["parent_run_id"] == parent_id


def test_list_run_proposals_route_exists(client, db):
    """Light smoke: run proposals listing with rows seeded via test fixtures."""
    from tests.support.run_execution_fixtures import materialize_run_outputs_for_tests

    agent = _seed_agent(db)
    run = RunService(db).create_run(agent.id, RunCreate(), SPACE, USER)
    materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)
    r = client.get(f"/api/v1/runs/{run.id}/proposals?{AUTH}")
    assert r.status_code == 200
