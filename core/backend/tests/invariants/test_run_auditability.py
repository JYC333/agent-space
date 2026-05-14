"""Invariant: a run leaves durable audit artifacts (snapshot, output, persisted rows) — no silent completion."""

from __future__ import annotations

from app.models import ActivityRecord, Artifact, ContextSnapshot
from app.runs.execution import RunExecutionService
from tests.support import factories


def test_factory_run_has_context_snapshot(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=False)
    db.flush()
    assert run.context_snapshot_id is not None
    snap = db.query(ContextSnapshot).filter(ContextSnapshot.id == run.context_snapshot_id).one()
    assert snap.space_id == a


def test_successful_execution_writes_activity_trail_and_artifact(
    monkeypatch, db, tmp_path, cross_space_pair
):
    from app.config import settings

    from tests.support.assertions import assert_run_has_audit_trail

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "hello-echo"
    db.flush()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.output_json is not None
    assert run.output_json.get("stdout")

    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) >= 1
    for art in arts:
        assert art.space_id == a
        assert art.run_id == run.id

    assert_run_has_audit_trail(db, space_id=a, run_id=run.id, min_activities=2)
    types = {
        r.activity_type
        for r in db.query(ActivityRecord).filter(
            ActivityRecord.space_id == a,
            ActivityRecord.source_run_id == run.id,
        )
    }
    assert "run.execution.started" in types
    assert "run.execution.succeeded" in types


def test_failed_adapter_execution_writes_started_and_failed_activities(
    monkeypatch, db, tmp_path, cross_space_pair
):
    from app.config import settings

    from tests.support.assertions import assert_run_has_audit_trail

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "x"
    db.flush()

    RunExecutionService(db).execute_run(run.id, space_id=a, simulate_failure=True)
    db.refresh(run)
    assert run.status == "failed"
    assert run.error_message or (run.error_json or {})

    assert_run_has_audit_trail(db, space_id=a, run_id=run.id, min_activities=2)
    types = {
        r.activity_type
        for r in db.query(ActivityRecord).filter(
            ActivityRecord.space_id == a,
            ActivityRecord.source_run_id == run.id,
        )
    }
    assert "run.execution.started" in types
    assert "run.execution.failed" in types
