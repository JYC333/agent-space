"""Runtime failure and disabled-adapter journeys leave auditable, non-success state."""

from __future__ import annotations

from sqlalchemy import func

from app.models import ActivityRecord, AgentVersion, Artifact, Proposal, Run
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


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

    ex = api_client.post(f"/api/v1/runs/{rid}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    body = ex.json()
    assert body.get("status") == "failed"
    err = body.get("error_json") or {}
    assert err.get("error_code") == "workflow_forced_fail"
    assert "stable workflow failure" in (err.get("error_text") or "")

    db.expire_all()
    types = {
        r.activity_type
        for r in db.query(ActivityRecord).filter(
            ActivityRecord.space_id == a,
            ActivityRecord.source_run_id == rid,
        )
    }
    assert "run.execution.started" in types
    assert "run.execution.failed" in types

    assert (
        db.query(func.count(Artifact.id)).filter(Artifact.run_id == rid).scalar() == 0
    )
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == rid)
        .scalar()
        == 0
    )


def test_disabled_runtime_adapter_execute_returns_failed_run_without_success_rows(
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
    disabled = factories.create_test_runtime_adapter(
        db,
        space_id=a,
        name="disabled-wf",
        adapter_type="echo",
        enabled=False,
        commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    ver = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    ver.runtime_adapter_id = disabled.id
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    rid = run.id

    r = api_client.post(f"/api/v1/runs/{rid}/execute", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    assert out.get("status") == "failed"
    assert (out.get("error_json") or {}).get("error_code") == "adapter_disabled"

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

    api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))

    summ = api_client.get("/api/v1/home/summary", params=_params(a, ua.id)).json()
    assert summ["run_stats_today"]["failed"] >= 1
