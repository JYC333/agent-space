"""Invariant: a run leaves durable audit artifacts (snapshot, output, persisted rows) — no silent completion."""

from __future__ import annotations

from app.models import ActivityRecord, Artifact, ContextSnapshot, Run
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


def test_snapshot_population_failure_blocks_adapter_and_marks_run_failed(
    monkeypatch, db, tmp_path, cross_space_pair
):
    """
    Invariant: if ContextSnapshotPopulator raises, the runtime adapter must
    never execute and the run must end in a failed terminal state.
    """
    from app.config import settings

    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    adapter_called = []

    def _never_called(_adapter_type):
        class _Boom:
            def execute(self, ctx):
                adapter_called.append(True)
                raise AssertionError("adapter must not be called when snapshot population fails")
        return _Boom()

    monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", _never_called)
    monkeypatch.setattr(
        "app.runs.execution.ContextSnapshotPopulator",
        _make_failing_populator("snapshot population failed: db error"),
    )

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "test"
    db.flush()

    result = RunExecutionService(db).execute_run(run.id, space_id=a)

    assert not adapter_called, "adapter must not be called after snapshot population failure"
    assert result.success is False
    assert result.error_code == "context_snapshot_population_failed"

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.status == "failed"
    assert "context_snapshot_population_failed" in (run_row.error_json or {}).get("error_code", "")


def test_executed_run_always_has_auditable_snapshot(
    monkeypatch, db, tmp_path, cross_space_pair
):
    """Invariant: every run that reaches succeeded/failed via normal execution has a non-empty snapshot."""
    from app.config import settings

    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "audit check"
    db.flush()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.expire_all()

    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.context_snapshot_id is not None

    snap = db.query(ContextSnapshot).filter(
        ContextSnapshot.id == run_row.context_snapshot_id
    ).one()
    assert snap.prefix_hash is not None, "executed run must have non-empty prefix_hash"
    assert snap.tail_hash is not None, "executed run must have non-empty tail_hash"
    assert snap.retrieval_trace_json is not None
    assert snap.token_budget_json is not None
    assert snap.source_refs_json is not None


# ---------------------------------------------------------------------------
# Helper: factory for a populator that always raises
# ---------------------------------------------------------------------------


def _make_failing_populator(error_message: str):
    """Return a ContextSnapshotPopulator replacement class whose populate() always raises."""

    class _FailingPopulator:
        def __init__(self, db):
            pass

        def populate(self, run, version):
            raise RuntimeError(error_message)

    return _FailingPopulator
