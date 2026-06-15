"""Runtime failure and disabled-adapter journeys leave auditable, non-success state."""

from __future__ import annotations

from sqlalchemy import func

from app.models import Artifact, Proposal, Run, RunStep
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_fake_runtime_failure_is_audited_without_success_outputs(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import settings

    db.commit()

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    cfg = FakeRuntimeConfig(
        success=False,
        error_code="workflow_forced_fail",
        error_text="stable workflow failure message",
        output_text="",
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    rid = run.id
    run_row = db.query(Run).filter(Run.id == rid).one()
    run_row.prompt = "will-fail"
    db.commit()

    ex = cross_space_pair["client_a"].post(f"/api/v1/runs/{rid}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    body = ex.json()
    assert body.get("status") == "failed"
    err = body.get("error_json") or {}
    assert err.get("error_code") == "workflow_forced_fail"
    assert "stable workflow failure" in (err.get("error_text") or "")

    db.expire_all()
    steps = db.query(RunStep).filter(RunStep.run_id == rid, RunStep.space_id == a).all()
    step_types = {s.step_type for s in steps}
    assert "queued" in step_types
    assert any(s.status == "failed" for s in steps)

    assert (
        db.query(func.count(Artifact.id)).filter(Artifact.run_id == rid).scalar() == 0
    )
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == rid)
        .scalar()
        == 0
    )


def test_planned_adapter_type_execute_returns_failed_run_without_success_rows(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    from app.config import settings

    db.commit()

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run.adapter_type = "opencode"
    db.commit()
    rid = run.id

    r = cross_space_pair["client_a"].post(f"/api/v1/runs/{rid}/execute", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    assert out.get("status") == "failed"
    assert (out.get("error_json") or {}).get("error_code") == "adapter_planned_not_executable"

    db.expire_all()
    assert (
        db.query(func.count(Artifact.id)).filter(Artifact.run_id == rid).scalar() == 0
    )
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == rid)
        .scalar()
        == 0
    )


def test_failed_run_surfaces_in_home_run_stats_today(
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
        lambda _t: ConfigurableFakeRuntimeAdapter(
            FakeRuntimeConfig(success=False, error_code="home_wf_fail", error_text="x")
        ),
    )

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))

    summ = cross_space_pair["client_a"].get("/api/v1/home/summary", params=_params(a, ua.id)).json()
    assert summ["run_stats_today"]["failed"] >= 1
