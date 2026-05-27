"""Workflow: ``produced_artifact_paths`` ingested by production code (no manual Artifact inserts)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func

from app.config import settings
from app.models import AgentVersion, Artifact, Proposal, Run
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


@pytest.fixture(autouse=True)
def _stub_durable_policy_audit(monkeypatch):
    """Keep SQLite path-ingestion coverage focused on artifact writes."""
    monkeypatch.setattr(
        "app.policy.audit.DurablePolicyAuditWriter.write",
        lambda self, decision: None,
    )


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _patch_roots(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspaces").mkdir(parents=True, exist_ok=True)


def _require_worktree(db, agent) -> None:
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    p = dict(v.runtime_policy_json or {})
    p["risk_level"] = "high"
    v.runtime_policy_json = p


def test_valid_produced_file_path_creates_managed_artifact(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_roots(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _require_worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"out/report.md": "# hello"},
        produced_artifact_paths=["out/report.md"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    ex = cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    assert ex.json().get("status") == "succeeded"

    db.expire_all()
    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) == 1
    art = arts[0]
    assert art.space_id == a
    assert art.storage_path is not None
    assert not art.storage_path.startswith("/")
    assert art.content is None
    assert art.metadata_json and art.metadata_json.get("ingestion_source") == "produced_artifact_paths"
    assert art.metadata_json.get("source_relative_path") == "out/report.md"
    disk = Path(settings.artifact_storage_root).resolve() / art.storage_path
    assert disk.is_file()
    assert disk.read_text(encoding="utf-8") == "# hello"
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == run.id)
        .scalar()
        == 0
    )


def test_multiple_valid_produced_paths(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_roots(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _require_worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"a.txt": "A", "b.txt": "B"},
        produced_artifact_paths=["a.txt", "b.txt"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    arts = db.query(Artifact).filter(Artifact.run_id == run.id).order_by(Artifact.title).all()
    assert len(arts) == 2
    for art in arts:
        assert art.space_id == a
        assert art.run_id == run.id


def test_invalid_traversal_records_error_no_artifact(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_roots(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _require_worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        sandbox_seed_files={"ok.txt": "ok"},
        produced_artifact_paths=["ok.txt", "../secret.txt"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    ex = cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    body = ex.json()
    assert body.get("status") == "succeeded"
    oj = body.get("output_json") or {}
    errs = oj.get("materialization_errors") or []
    assert any("produced_artifact_paths[1]" in e for e in errs)
    joined = " ".join(errs)
    assert "SECRET_LEAK" not in joined

    db.expire_all()
    arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    assert len(arts) == 1
    assert arts[0].title == "ok.txt"


def test_missing_file_records_error(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_roots(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _require_worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={"adapter_type": "fake_test_runtime"},
        produced_artifact_paths=["nope.txt"],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    ex = cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    errs = (ex.json().get("output_json") or {}).get("materialization_errors") or []
    assert any("missing" in e.lower() for e in errs)
    assert db.query(Artifact).filter(Artifact.run_id == run.id).count() == 0


def test_produced_paths_and_proposed_changes(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    _patch_roots(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id, name="pa-ws", commit=True
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    _require_worktree(db, agent)
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "memory_update",
                    "summary": "mem",
                    "payload": {
                        "proposed_title": "T",
                        "proposed_content": "c",
                        "memory_type": "semantic",
                        "target_scope": "agent",
                        "target_namespace": "ns.p",
                        "rationale": "r",
                    },
                }
            ],
        },
        sandbox_seed_files={"report.md": "R"},
        produced_artifact_paths=[
            {"path": "report.md", "artifact_type": "report", "title": "Run report", "mime_type": "text/markdown"}
        ],
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()
    ex = cross_space_pair["client_a"].post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200

    db.expire_all()
    art = db.query(Artifact).filter(Artifact.run_id == run.id).one()
    assert art.artifact_type == "report"
    assert art.title == "Run report"
    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
    assert prop.status == "pending"
    assert prop.proposal_type == "memory_create"
