"""Invariant: run success materializes proposals but never active memory or workspace files directly."""

from __future__ import annotations

from sqlalchemy import func

from app.config import settings
from app.models import MemoryEntry, Proposal
from app.runs.execution import RunExecutionService
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


def test_run_execute_materializes_memory_proposal_without_active_memory(
    monkeypatch, db, cross_space_pair, tmp_path
):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "memory_update",
                    "summary": "from run",
                    "payload": {
                        "proposed_title": "t",
                        "proposed_content": "c",
                        "memory_type": "semantic",
                        "target_scope": "agent",
                        "target_namespace": "ns.inv",
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

    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "p"
    db.flush()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    db.refresh(run)
    assert run.status == "succeeded"
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before
    props = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
    assert len(props) == 1
    assert props[0].proposal_type == "memory_update"
    assert props[0].status == "pending"


def test_run_execute_code_patch_proposal_does_not_write_workspace_until_accept(
    monkeypatch, db, cross_space_pair, tmp_path
):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    ws = factories.create_test_workspace(
        db, space_id=a, created_by_user_id=ua.id, name="patch-ws", commit=False
    )
    db.flush()
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "f.txt").write_text("ORIGINAL", encoding="utf-8")

    cfg = FakeRuntimeConfig(
        output_text="",
        output_json={
            "adapter_type": "fake_test_runtime",
            "proposed_changes": [
                {
                    "proposal_type": "code_patch",
                    "summary": "patch file",
                    "workspace_id": ws.id,
                    "patch": {
                        "operations": [
                            {"op": "replace_file", "path": "f.txt", "content": "PATCHED"},
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
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.prompt = "p"
    db.flush()

    RunExecutionService(db).execute_run(run.id, space_id=a)
    assert (disk / "f.txt").read_text(encoding="utf-8") == "ORIGINAL"
    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).one()
    assert prop.proposal_type == "code_patch"
