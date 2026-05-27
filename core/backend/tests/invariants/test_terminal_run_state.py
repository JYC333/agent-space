"""Invariant: terminal runs are not re-executed in place; stop is a no-op once terminal."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.runs.execution import RunExecutionService
from app.runs.run_service import RunService
from tests.support import factories


@pytest.fixture(autouse=True)
def _stub_durable_policy_audit(monkeypatch):
    """This SQLite module verifies terminal-state transitions, not policy audit commits."""
    monkeypatch.setattr(
        "app.policy.audit.DurablePolicyAuditWriter.write",
        lambda _writer, _envelope: "stub-policy-audit",
    )


def test_completed_run_cannot_be_executed_again(monkeypatch, db, tmp_path, cross_space_pair_db):
    from app.config import settings

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "once"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.refresh(run)
    assert run.status == "succeeded"

    with pytest.raises(HTTPException) as ei:
        RunExecutionService(db).execute_run(run.id, space_id=a)
    assert ei.value.status_code == 409


def test_failed_run_cannot_transition_to_succeeded_by_re_execute(monkeypatch, db, tmp_path, cross_space_pair_db):
    from app.config import settings

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "x"
    db.flush()
    db.commit()

    RunExecutionService(db).execute_run(run.id, space_id=a, simulate_failure=True)
    db.refresh(run)
    assert run.status == "failed"

    with pytest.raises(HTTPException) as ei:
        RunExecutionService(db).execute_run(run.id, space_id=a)
    assert ei.value.status_code == 409


def test_stop_run_is_noop_when_already_succeeded(monkeypatch, db, tmp_path, cross_space_pair_db):
    from app.config import settings

    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "done"
    db.flush()
    db.commit()
    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.refresh(run)
    status_before = run.status

    run2, changed = RunService(db).stop_run(run.id, a)
    assert changed is False
    assert run2.status == status_before
