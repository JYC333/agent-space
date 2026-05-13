"""Run execution, outputs, Task linkage, and jobs (canonical).

Uses ``RunExecutionService`` with the echo adapter for execution paths and
``tests.support.run_execution_fixtures`` for deterministic Activity / Artifact /
Proposal rows where read surfaces are tested directly.

Removed ``runtime`` query / job overrides are rejected: ``RunExecutionService``
may return ``runtime_removed`` without mutating the Run; HTTP execute may return
410; ``agent_run`` jobs raise ``ValueError`` when a removed override is present.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.canonical

from app.agents.agent_service import AgentService
from app.models import (
    ActivityRecord,
    Agent,
    Artifact,
    Job,
    MemoryEntry,
    Proposal,
    Run,
    Task,
    TaskArtifact,
    TaskProposal,
    TaskRun,
)
from app.memory.proposals import MemoryProposalService
from app.runs.execution import RunExecutionService
from app.runs.removed_runtime_token import obsolete_runtime_override_token
from app.runs.run_service import RunService
from app.runs.task_output_linkage import link_run_outputs_to_tasks
from app.schemas import AgentCreate, RunCreate, TaskCreate, TaskRunCreateBody
from app.tasks.service import TaskService
from tests.conftest import SPACE, USER, ensure_space
from tests.support.run_execution_fixtures import (
    attach_pending_proposal_for_run,
    materialize_run_outputs_for_tests,
)


def _seed_agent(db) -> Agent:
    return AgentService(db).create(
        AgentCreate(name="Run execution test agent"),
        requesting_user_id=USER,
    )


def _create_queued_run(db, agent: Agent, *, mode: str = "live") -> Run:
    return RunService(db).create_run(
        agent_id=agent.id,
        data=RunCreate(mode=mode),
        space_id=SPACE,
        user_id=USER,
    )


def _auth_q() -> str:
    return f"space_id={SPACE}&user_id={USER}"


class TestEchoAdapterExecution:
    def test_queued_run_executes_to_succeeded(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        assert run.status == "queued"

        result = RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        assert result.success is True

        db.refresh(run)
        assert run.status == "succeeded"
        assert run.started_at is not None
        assert run.ended_at is not None
        assert run.error_message is None
        assert run.output_json.get("runtime_adapter_type") == "echo"

    def test_activity_artifact_proposal_created_via_fixture(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        activities = (
            db.query(ActivityRecord)
            .filter(ActivityRecord.source_run_id == run.id)
            .all()
        )
        assert len(activities) >= 2
        for a in activities:
            assert a.space_id == SPACE
            assert a.source_run_id == run.id

        artifacts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        assert len(artifacts) == 1
        art = artifacts[0]
        assert art.space_id == SPACE
        assert art.run_id == run.id
        assert art.preview is False
        assert art.exportable is True

        proposals = (
            db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
        )
        assert len(proposals) == 1
        prop = proposals[0]
        assert prop.space_id == SPACE
        assert prop.created_by_run_id == run.id
        assert prop.proposal_type == "memory_update"
        assert prop.status == "pending"
        assert prop.preview is False

    def test_run_subresources_return_outputs(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        r = client.get(f"/api/v1/runs/{run.id}/activities?{_auth_q()}")
        assert r.status_code == 200
        assert r.json()["total"] >= 2

        r2 = client.get(f"/api/v1/runs/{run.id}/artifacts?{_auth_q()}")
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        assert r2.json()["items"][0]["preview"] is False

        r3 = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}")
        assert r3.status_code == 200
        rows = r3.json()["items"]
        assert any(p["created_by_run_id"] == run.id for p in rows)
        assert all(p.get("preview") is False for p in rows)

    def test_global_proposals_list_includes_run_emitted_proposal(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        r = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert any(p.get("created_by_run_id") == run.id for p in body["items"])

    def test_global_proposals_detail_matches_list_visibility(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        lst = client.get(f"/api/v1/proposals?{_auth_q()}&status=pending")
        assert lst.status_code == 200
        match = [p for p in lst.json()["items"] if p.get("created_by_run_id") == run.id]
        assert match
        pid = match[0]["id"]
        detail = client.get(f"/api/v1/proposals/{pid}?{_auth_q()}")
        assert detail.status_code == 200
        assert detail.json()["id"] == pid

    def test_cross_space_proposal_hidden_from_list_and_detail(self, client, db):
        ensure_space(db, "team_space")
        p = MemoryProposalService(db).create_proposal(
            space_id="team_space",
            user_id=USER,
            target_scope="user",
            target_namespace="user.default.preferences",
            memory_type="preference",
            proposed_title="Other space only",
            proposed_content="x",
            rationale="cross-space visibility test",
        )
        lst = client.get(f"/api/v1/proposals?space_id={SPACE}&user_id={USER}&status=pending")
        assert lst.status_code == 200
        assert all(x["id"] != p.id for x in lst.json()["items"])
        detail = client.get(f"/api/v1/proposals/{p.id}?space_id={SPACE}&user_id={USER}")
        assert detail.status_code == 404

    def test_activity_inbox_lists_run_emitted_records(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        r = client.get(f"/api/v1/activity?{_auth_q()}&status=raw")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        assert any(x.get("source_run_id") == run.id for x in rows)

    def test_failed_run_preserves_error(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        materialize_run_outputs_for_tests(
            db, run.id, space_id=SPACE, simulate_failure=True
        )
        db.refresh(run)
        assert run.status == "failed"
        assert run.error_message
        assert "simulated failure" in run.error_message.lower()
        assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 1
        assert (
            db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count()
            == 1
        )

    def test_terminal_run_rejects_re_execution(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        with pytest.raises(HTTPException) as exc:
            RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        assert exc.value.status_code == 409

    def test_cancelled_run_rejects_execution(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        run.status = "cancelled"
        db.commit()
        with pytest.raises(HTTPException) as exc:
            RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        assert exc.value.status_code == 409

    def test_cross_space_execution_rejected(self, db):
        ensure_space(db, "space-other-7", "Other")
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        with pytest.raises(HTTPException) as exc:
            RunExecutionService(db).execute_run(run.id, space_id="space-other-7")
        assert exc.value.status_code == 404

    def test_execution_does_not_create_new_agent_version_or_run(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        from app.models import AgentVersion

        versions_before = db.query(AgentVersion).count()
        runs_before = db.query(Run).count()
        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        assert db.query(AgentVersion).count() == versions_before
        assert db.query(Run).count() == runs_before


class TestTaskCreatedRunExecution:
    def test_task_run_echo_links_artifact_via_task_run(self, client, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Run execution task", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )

        _link, run = TaskService(db).create_queued_run_for_task(
            task.id, SPACE, USER, TaskRunCreateBody()
        )
        run_id = run.id
        run = db.query(Run).filter(Run.id == run_id).one()
        assert run.status == "queued"
        assert run.task_id == task.id

        link = db.query(TaskRun).filter(TaskRun.run_id == run.id).one()
        assert link.task_id == task.id

        RunExecutionService(db).execute_run(run_id, space_id=SPACE)

        db.refresh(run)
        assert run.status == "succeeded"

        task_arts = (
            db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).all()
        )
        assert len(task_arts) == 1
        assert task_arts[0].space_id == SPACE

        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)
        task_props = (
            db.query(TaskProposal).filter(TaskProposal.task_id == task.id).all()
        )
        assert len(task_props) == 1
        assert task_props[0].space_id == SPACE

        assert db.query(TaskRun).filter(TaskRun.task_id == task.id).count() == 1

    def test_task_subresources_return_outputs(self, client, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Run execution task surfaces", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        _link, run = TaskService(db).create_queued_run_for_task(
            task.id, SPACE, USER, TaskRunCreateBody()
        )
        run_id = run.id
        run = db.query(Run).filter(Run.id == run_id).one()
        RunExecutionService(db).execute_run(run_id, space_id=SPACE)
        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)
        db.commit()

        a = client.get(f"/api/v1/tasks/{task.id}/artifacts?{_auth_q()}")
        assert a.status_code == 200
        assert a.json()["total"] == 1
        assert a.json()["items"][0]["artifact"]["artifact_type"] == "runtime_output"

        pr = client.get(f"/api/v1/tasks/{task.id}/proposals?{_auth_q()}")
        assert pr.status_code == 200
        assert pr.json()["total"] == 1
        assert pr.json()["items"][0]["proposal"]["proposal_type"] == "memory_update"

    def test_outputs_follow_task_runs_not_run_task_id_alone(self, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Retry-linked", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        run = _create_queued_run(db, agent)
        assert run.task_id is None
        TaskService(db).link_task_to_run(
            space_id=SPACE,
            task_id=task.id,
            run_id=run.id,
            role="retry",
        )
        db.refresh(run)
        assert run.task_id is None

        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)

        assert (
            db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).count()
            == 1
        )
        assert (
            db.query(TaskProposal).filter(TaskProposal.task_id == task.id).count()
            == 1
        )

    def test_existing_task_link_not_duplicated(self, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Pre-linked", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        body = TaskRunCreateBody()
        _link, run = TaskService(db).create_queued_run_for_task(
            task.id, SPACE, USER, body
        )
        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)
        assert db.query(TaskRun).filter(TaskRun.task_id == task.id).count() == 1
        assert (
            db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).count()
            == 1
        )
        assert (
            db.query(TaskProposal).filter(TaskProposal.task_id == task.id).count()
            == 1
        )

    def test_multi_task_run_links_outputs_to_all_tasks(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        task_a = TaskService(db).create(
            TaskCreate(title="A", assigned_agent_id=agent.id), SPACE, USER
        )
        task_b = TaskService(db).create(
            TaskCreate(title="B", assigned_agent_id=agent.id), SPACE, USER
        )
        TaskService(db).link_task_to_run(
            space_id=SPACE, task_id=task_a.id, run_id=run.id, role="primary"
        )
        TaskService(db).link_task_to_run(
            space_id=SPACE, task_id=task_b.id, run_id=run.id, role="subtask"
        )

        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)
        for tid in (task_a.id, task_b.id):
            assert (
                db.query(TaskArtifact).filter(TaskArtifact.task_id == tid).count()
                == 1
            )
            assert (
                db.query(TaskProposal).filter(TaskProposal.task_id == tid).count()
                == 1
            )


class TestDryRunPreview:
    def test_dry_run_produces_preview_artifact_and_proposal(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="dry_run")
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        db.refresh(run)
        assert run.status == "succeeded"
        assert run.mode == "dry_run"
        assert run.output_json["preview"] is True

        art = db.query(Artifact).filter(Artifact.run_id == run.id).one()
        assert art.preview is True

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
        assert prop.preview is True
        assert prop.proposal_type == "memory_update"
        assert (
            db.query(MemoryEntry).filter(MemoryEntry.source_proposal_id == prop.id).count()
            == 0
        )

    def test_dry_run_does_not_write_active_memory_entry(self, db):
        memory_before = db.query(MemoryEntry).count()
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="dry_run")
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)
        assert db.query(MemoryEntry).count() == memory_before

    def test_preview_visible_through_run_subresources(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="dry_run")
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)

        ra = client.get(f"/api/v1/runs/{run.id}/artifacts?{_auth_q()}")
        assert ra.status_code == 200
        items = ra.json()["items"]
        assert items and all(i["preview"] is True for i in items)

        rp = client.get(f"/api/v1/runs/{run.id}/proposals?{_auth_q()}")
        assert rp.status_code == 200
        proposal_rows = rp.json()["items"]
        assert proposal_rows
        assert all(r.get("preview") is True for r in proposal_rows)

    def test_preview_visible_through_task_subresources(self, client, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Preview task", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        _link, run = TaskService(db).create_queued_run_for_task(
            task.id, SPACE, USER, TaskRunCreateBody(mode="dry_run")
        )
        run_id = run.id
        run = db.query(Run).filter(Run.id == run_id).one()
        materialize_run_outputs_for_tests(db, run_id, space_id=SPACE)

        a = client.get(f"/api/v1/tasks/{task.id}/artifacts?{_auth_q()}")
        assert a.status_code == 200
        rows = a.json()["items"]
        assert rows
        artifact_id = rows[0]["artifact_id"]
        art = db.query(Artifact).filter(Artifact.id == artifact_id).one()
        assert art.preview is True

        p = client.get(f"/api/v1/tasks/{task.id}/proposals?{_auth_q()}")
        assert p.status_code == 200
        prop_rows = p.json()["items"]
        assert prop_rows
        proposal_id = prop_rows[0]["proposal_id"]
        prop = db.query(Proposal).filter(Proposal.id == proposal_id).one()
        assert prop.preview is True

    def test_preview_artifact_can_be_exported(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="dry_run")
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)
        art = db.query(Artifact).filter(Artifact.run_id == run.id).one()
        r = client.get(f"/api/v1/artifacts/{art.id}/export?{_auth_q()}")
        assert r.status_code == 200
        assert b"Fixture preview report" in r.content

    def test_dry_run_echo_leaves_sandbox_path_unset(self, db, tmp_path, monkeypatch):
        sandbox_root = tmp_path / "no-sandbox"
        monkeypatch.setattr("app.config.settings.sandbox_root", str(sandbox_root))
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="dry_run")
        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        db.refresh(run)
        assert run.status == "succeeded"
        assert run.sandbox_path is None
        assert not sandbox_root.exists()


class TestJobHandlerExecution:
    @staticmethod
    def _bind_session_local(monkeypatch, db_engine):
        TestingSession = sessionmaker(bind=db_engine)
        monkeypatch.setattr("app.db.SessionLocal", TestingSession)
        return TestingSession

    def test_agent_run_job_with_run_id_executes_existing_run(self, db, db_engine, monkeypatch):
        self._bind_session_local(monkeypatch, db_engine)
        from app.jobs.handlers import handle_agent_run

        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        job = SimpleNamespace(
            payload={"run_id": run.id},
            space_id=SPACE,
            user_id=USER,
        )
        result = handle_agent_run(job)
        assert result == {"run_id": run.id, "status": "succeeded"}

        db.refresh(run)
        assert run.status == "succeeded"

        assert db.query(Job).filter(Job.payload_json["run_id"].as_string() == run.id).count() == 0

    def test_agent_run_job_with_task_id_creates_links_executes(self, db, db_engine, monkeypatch):
        self._bind_session_local(monkeypatch, db_engine)
        from app.jobs.handlers import handle_agent_run

        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Job task", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        runs_before = db.query(Run).count()
        task_runs_before = db.query(TaskRun).count()

        job = SimpleNamespace(
            payload={"task_id": task.id},
            space_id=SPACE,
            user_id=USER,
        )
        result = handle_agent_run(job)
        assert result["status"] == "succeeded"
        assert "run_id" in result

        assert db.query(Run).count() == runs_before + 1
        assert db.query(TaskRun).count() == task_runs_before + 1

        run = db.query(Run).filter(Run.id == result["run_id"]).one()
        assert run.status == "succeeded"
        assert (
            db.query(TaskRun)
            .filter(TaskRun.task_id == task.id, TaskRun.run_id == run.id)
            .count()
            == 1
        )

    def test_agent_run_job_with_agent_id_creates_and_executes(self, db, db_engine, monkeypatch):
        self._bind_session_local(monkeypatch, db_engine)
        from app.jobs.handlers import handle_agent_run

        agent = _seed_agent(db)
        runs_before = db.query(Run).count()
        tasks_before = db.query(Task).count()
        task_runs_before = db.query(TaskRun).count()

        job = SimpleNamespace(
            payload={"agent_id": agent.id, "prompt": "hi"},
            space_id=SPACE,
            user_id=USER,
        )
        result = handle_agent_run(job)
        assert result["status"] == "succeeded"

        assert db.query(Run).count() == runs_before + 1
        assert db.query(Task).count() == tasks_before
        assert db.query(TaskRun).count() == task_runs_before

    def test_agent_run_job_failure_propagates_simulate_failure(self, db, db_engine, monkeypatch):
        self._bind_session_local(monkeypatch, db_engine)
        from app.jobs.handlers import handle_agent_run

        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        job = SimpleNamespace(
            payload={"run_id": run.id, "simulate_failure": True},
            space_id=SPACE,
            user_id=USER,
        )
        result = handle_agent_run(job)
        assert result["run_id"] == run.id
        assert result["status"] == "failed"
        assert "error" in result

    def test_agent_run_job_without_any_id_raises(self):
        from app.jobs.handlers import handle_agent_run

        job = SimpleNamespace(payload={}, space_id=SPACE, user_id=USER)
        with pytest.raises(ValueError):
            handle_agent_run(job)


class TestSafetyInvariants:
    def test_run_execution_service_rejects_obsolete_override_without_run_mutation(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        r = RunExecutionService(db).execute_run(
            run.id, space_id=SPACE, runtime=obsolete_runtime_override_token()
        )
        assert r.success is False
        assert r.error_code == "runtime_removed"
        db.refresh(run)
        assert run.status == "queued"
        assert run.error_json is None

    def test_run_execution_service_rejects_unknown_runtime(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        with pytest.raises(HTTPException) as exc:
            RunExecutionService(db).execute_run(
                run.id, space_id=SPACE, runtime="claude_code"
            )
        assert exc.value.status_code == 400

    def test_fixture_module_has_no_forbidden_adapter_imports(self):
        import ast
        import tests.support.run_execution_fixtures as rf

        with open(rf.__file__, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        forbidden_modules = {
            "subprocess",
            "docker",
            "anthropic",
            "openai",
            "app.agents.runner",
            "app.agents.claude_adapter",
            "app.agents.codex_adapter",
            "app.agents.api_adapter",
            "app.agents.cli_adapter",
            "app.workspace.sandbox_manager",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for binding in node.names:
                    assert binding.name not in forbidden_modules, (
                        f"Fixture module must not import {binding.name!r}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert mod not in forbidden_modules, (
                    f"Fixture module must not import from {mod!r}"
                )

    def test_fixture_does_not_apply_proposal(self, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent, mode="live")
        memory_before = db.query(MemoryEntry).count()
        materialize_run_outputs_for_tests(db, run.id, space_id=SPACE)
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
        assert prop.status == "pending"
        assert prop.decided_at is None
        assert prop.resulting_memory_id is None
        assert db.query(MemoryEntry).count() == memory_before

    def test_echo_linkage_does_not_use_run_task_id_as_only_linkage(self, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="Forged shortcut", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        run = _create_queued_run(db, agent)
        run.task_id = task.id
        db.commit()
        assert (
            db.query(TaskRun)
            .filter(TaskRun.task_id == task.id, TaskRun.run_id == run.id)
            .count()
            == 0
        )

        RunExecutionService(db).execute_run(run.id, space_id=SPACE)
        p = attach_pending_proposal_for_run(db, run)
        link_run_outputs_to_tasks(db, run=run, artifact=None, proposal=p)

        assert (
            db.query(TaskArtifact).filter(TaskArtifact.task_id == task.id).count()
            == 0
        )
        assert (
            db.query(TaskProposal).filter(TaskProposal.task_id == task.id).count()
            == 0
        )
        assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 1

    def test_singular_task_run_route_removed(self, client, db):
        agent = _seed_agent(db)
        task = TaskService(db).create(
            TaskCreate(title="No singular route", assigned_agent_id=agent.id),
            SPACE,
            USER,
        )
        r = client.post(f"/api/v1/tasks/{task.id}/run", json={})
        assert r.status_code in (404, 405)

    def test_run_execution_does_not_create_product_task(self, db, db_engine, monkeypatch):
        TestingSession = sessionmaker(bind=db_engine)
        monkeypatch.setattr("app.db.SessionLocal", TestingSession)
        from app.jobs.handlers import handle_agent_run

        agent = _seed_agent(db)
        tasks_before = db.query(Task).count()
        job = SimpleNamespace(
            payload={"agent_id": agent.id},
            space_id=SPACE,
            user_id=USER,
        )
        handle_agent_run(job)
        assert db.query(Task).count() == tasks_before

    def test_runner_exposes_no_removed_execute_hooks(self):
        import app.agents.runner as runner

        assert not hasattr(runner, "execute_pending_run")
        removed_svc = "".join(("Agent", "Run", "Service"))
        assert not hasattr(runner, removed_svc)

    def test_http_execute_obsolete_override_returns_410(self, client, db):
        agent = _seed_agent(db)
        run = _create_queued_run(db, agent)
        tok = obsolete_runtime_override_token()
        r = client.post(f"/api/v1/runs/{run.id}/execute?{_auth_q()}&runtime={tok}")
        assert r.status_code == 410
        db.refresh(run)
        assert run.status == "queued"
