"""Run execution → audit trail → persisted artifact; no silent memory writes."""

from __future__ import annotations

from sqlalchemy import func

from app.models import Artifact, MemoryEntry, Proposal, Run, RunStep
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_run_execute_success_leaves_audit_artifact_and_no_run_proposals(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import settings

    db.commit()

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    cfg = FakeRuntimeConfig(
        output_text="deterministic-workflow-output",
        output_json={"workflow_marker": True},
    )
    fake = ConfigurableFakeRuntimeAdapter(cfg)

    def _instantiate(_adapter_type: str):
        return fake

    monkeypatch.setattr("app.runs.execution.instantiate_runtime_adapter", _instantiate)

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mem_before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row0 = db.query(Run).filter(Run.id == run.id).one()
    run_row0.prompt = "wf-prompt"
    db.commit()

    ex = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row0.id}/execute",
        params=_params(a, ua.id),
    )
    assert ex.status_code == 200
    body = ex.json()
    assert body.get("status") == "succeeded"
    assert body.get("output_json") is not None

    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    assert run_row.output_json is not None
    assert run_row.output_json.get("output_text") == "deterministic-workflow-output"

    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) >= 1
    for art in arts:
        assert art.space_id == a
        assert art.run_id == run.id

    steps = db.query(RunStep).filter(RunStep.run_id == run.id, RunStep.space_id == a).all()
    step_types = {s.step_type for s in steps}
    assert "queued" in step_types
    assert "completed" in step_types

    assert (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
        == mem_before
    )
    n_run_props = (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == run.id)
        .scalar()
    )
    assert n_run_props == 0


def test_run_execute_cannot_be_triggered_from_foreign_space(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import settings

    db.commit()

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text="x")),
    )

    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    r = cross_space_pair["client_b"].post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404

    db.expire_all()
    assert db.query(Run).filter(Run.id == run.id).one().status == "queued"
