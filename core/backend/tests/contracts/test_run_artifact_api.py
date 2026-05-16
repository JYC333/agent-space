"""HTTP contract: run-scoped artifact list/detail/export for ingested file artifacts."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import AgentVersion, Artifact
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _patch_execute(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspaces").mkdir(parents=True, exist_ok=True)


def _worktree(db, agent) -> None:
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.runtime_policy_json = {**dict(v.runtime_policy_json or {}), "risk_level": "high"}


def test_run_artifacts_list_includes_produced_file_artifact(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"data.bin": "payload-bytes"},
        produced_artifact_paths=["data.bin"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    art = db.query(Artifact).filter(Artifact.run_id == run.id).one()

    r = cross_space_pair["client_a"].get(f"/api/v1/runs/{run.id}/artifacts", params=_params(a, ua.id))
    assert r.status_code == 200
    page = r.json()
    assert page.get("total") == 1
    item = page["items"][0]
    assert item["id"] == art.id
    assert item.get("metadata_json") is not None
    assert item["metadata_json"].get("ingestion_source") == "produced_artifact_paths"
    sp = item.get("storage_path") or ""
    assert sp and not sp.startswith("/")


def test_artifact_detail_and_export_file(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"note.txt": "NOTE"},
        produced_artifact_paths=["note.txt"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    art = db.query(Artifact).filter(Artifact.run_id == run.id).one()

    d = cross_space_pair["client_a"].get(f"/api/v1/artifacts/{art.id}", params=_params(a, ua.id))
    assert d.status_code == 200
    dj = d.json()
    assert "metadata_json" in dj
    assert dj.get("has_inline_content") is False

    ex = cross_space_pair["client_a"].get(f"/api/v1/artifacts/{art.id}/export", params=_params(a, ua.id))
    assert ex.status_code == 200
    assert b"NOTE" in ex.content


def test_get_artifact_cross_space_denied(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"x.txt": "X"},
        produced_artifact_paths=["x.txt"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    art = db.query(Artifact).filter(Artifact.run_id == run.id).one()

    r = cross_space_pair["client_b"].get(f"/api/v1/artifacts/{art.id}", params=_params(b, ub.id))
    assert r.status_code == 404
