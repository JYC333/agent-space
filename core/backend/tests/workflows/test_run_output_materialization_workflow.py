"""Workflow: production RunOutputMaterializer + code_patch accept (no hand-inserted run proposals)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func

from app.config import settings
from app.models import Artifact, MemoryEntry, Proposal, Run
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def _patch_execute(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "wsroot"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wsroot").mkdir(parents=True, exist_ok=True)


def test_workflow_output_text_only_no_proposals(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    cfg = FakeRuntimeConfig(
        output_text="plain only",
        output_json={"adapter_type": "fake_test_runtime"},
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.query(Run).filter(Run.id == run.id).one()
    db.commit()

    ex = api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert ex.status_code == 200
    assert ex.json().get("status") == "succeeded"

    db.expire_all()
    n = (
        db.query(func.count(Proposal.id))
        .filter(Proposal.space_id == a, Proposal.created_by_run_id == run.id)
        .scalar()
    )
    assert n == 0


def test_workflow_structured_artifact_no_proposals(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "artifacts": [
                {"artifact_type": "report", "title": "R1", "content": "artifact body"},
            ],
        },
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    arts = db.query(Artifact).filter(Artifact.run_id == run.id, Artifact.artifact_type == "report").all()
    assert len(arts) == 1
    assert arts[0].space_id == a
    assert arts[0].content == "artifact body"
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.created_by_run_id == run.id)
        .scalar()
        == 0
    )


def test_workflow_memory_update_from_run_materializer_then_accept(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "memory_update",
                    "summary": "svc mem",
                    "payload": {
                        "proposed_title": "Tmem",
                        "proposed_content": "mem-from-run",
                        "memory_type": "semantic",
                        "target_scope": "agent",
                        "target_namespace": "ns.runwf",
                        "rationale": "r",
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.commit()
    db.expire_all()
    after_run = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after_run == before
    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
    assert prop.proposal_type == "memory_create"

    acc = api_client.post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert acc.status_code == 200
    assert acc.json().get("result", {}).get("memory", {}).get("content") == "mem-from-run"


def test_workflow_code_patch_from_run_then_accept_mutates_file(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws = factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id, name="cp-wf", commit=True
    )
    disk = Path(tmp_path / "wsroot") / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "note.txt").write_text("V0", encoding="utf-8")

    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "code_patch",
                    "summary": "update note",
                    "workspace_id": ws.id,
                    "patch": {
                        "operations": [
                            {"op": "replace_file", "path": "note.txt", "content": "V1"},
                        ]
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    assert (disk / "note.txt").read_text(encoding="utf-8") == "V0"
    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
    assert prop.proposal_type == "code_patch"

    acc = api_client.post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert acc.status_code == 200
    body = acc.json()
    assert body.get("result_type") == "code_patch_apply"
    assert body.get("result", {}).get("updated_paths") == ["note.txt"]
    assert (disk / "note.txt").read_text(encoding="utf-8") == "V1"

    dup = api_client.post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert dup.status_code == 404


def test_workflow_materialization_rejects_traversal_patch_without_proposal(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
    _patch_execute(monkeypatch, tmp_path)
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws = factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id, name="tr-ws", commit=True
    )
    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "code_patch",
                    "summary": "bad",
                    "workspace_id": ws.id,
                    "patch": {
                        "operations": [
                            {"op": "replace_file", "path": "../evil.txt", "content": "x"},
                        ]
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    api_client.post(f"/api/v1/runs/{run.id}/execute", params=_params(a, ua.id))
    db.expire_all()
    run_row = db.query(Run).filter(Run.id == run.id).one()
    errs = (run_row.output_json or {}).get("materialization_errors") or []
    assert errs
    assert (
        db.query(func.count(Proposal.id))
        .filter(Proposal.created_by_run_id == run.id)
        .scalar()
        == 0
    )
