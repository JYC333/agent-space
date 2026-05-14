"""Invariant: general proposal review — pending-only durable apply; type and space boundaries."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func

from app.config import settings
from app.memory.proposals import ProposalService, UnsupportedProposalTypeError
from app.models import MemoryEntry, Proposal
from tests.support import factories


def test_memory_update_pending_does_not_create_active_memory(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before
    assert prop.status == "pending"


def test_code_patch_pending_does_not_mutate_workspace_files(db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "f.txt").write_text("ORIG", encoding="utf-8")

    factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="p",
        payload_json={
            "patch": {
                "operations": [{"op": "replace_file", "path": "f.txt", "content": "NEW"}],
            },
        },
        commit=True,
    )
    assert (disk / "f.txt").read_text(encoding="utf-8") == "ORIG"


def test_unsupported_proposal_type_accept_raises_no_durable_mutation(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="unknown_type_x",
        commit=True,
    )
    try:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    except UnsupportedProposalTypeError as exc:
        assert exc.proposal_type == "unknown_type_x"
    else:
        raise AssertionError("expected UnsupportedProposalTypeError")
    db.refresh(prop)
    assert prop.status == "pending"
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_cross_space_proposal_apply_denied(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    assert ProposalService(db).accept(prop.id, space_id=b, user_id=ua.id) is None
    db.refresh(prop)
    assert prop.status == "pending"


def test_accept_links_memory_entry_to_proposal(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None
    mem = out.memory
    assert mem.source_proposal_id == prop.id
    db.refresh(out.proposal)
    assert out.proposal.resulting_memory_id == mem.id


def test_accept_code_patch_links_applied_paths_on_proposal(db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)
    Path(ws_root / ws.id / "z.txt").write_text("0", encoding="utf-8")

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="z",
        payload_json={
            "patch": {"operations": [{"op": "replace_file", "path": "z.txt", "content": "1"}]},
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None and out.updated_paths == ["z.txt"]
    db.refresh(prop)
    row = db.query(Proposal).filter(Proposal.id == prop.id).one()
    assert row.status == "accepted"
    assert (row.payload_json or {}).get("applied_paths") == ["z.txt"]
