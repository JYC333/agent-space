"""Invariant: general proposal review — pending-only durable apply; type and space boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func

from app.config import settings
from app.proposals import ProposalService
from app.policy.exceptions import PolicyGateBlocked
from app.models import MemoryEntry, Proposal
from tests.support import factories


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_memory_update_pending_does_not_create_active_memory(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
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


def test_code_patch_pending_does_not_mutate_workspace_files(db, cross_space_pair_db, tmp_path, monkeypatch):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
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


def test_unsupported_proposal_type_accept_raises_no_durable_mutation(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
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
    with pytest.raises(PolicyGateBlocked) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.decision.proposal_type == "unknown_type_x"
    assert ei.value.decision.audit_code == "unsupported_proposal_type"
    db.refresh(prop)
    assert prop.status == "pending"
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before


def test_cross_space_proposal_apply_denied(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    b = cross_space_pair_db["space_b_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    assert ProposalService(db).accept(prop.id, space_id=b, user_id=ua.id) is None
    db.refresh(prop)
    assert prop.status == "pending"


def test_accept_links_memory_entry_to_proposal(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None
    mem = out.memory
    assert mem.source_proposal_id == prop.id
    db.refresh(out.proposal)
    assert out.proposal.resulting_memory_id == mem.id


def test_accept_code_patch_links_applied_paths_on_proposal(db, test_user, test_space, tmp_path, monkeypatch):
    a = test_space.id
    ua = test_user
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)
    original = b"0"
    Path(ws_root / ws.id / "z.txt").write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="z",
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "z.txt",
                        "content": "1",
                        "preimage_exists": True,
                        "preimage_sha256": _sha256(original),
                    }
                ]
            },
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None and out.updated_paths == ["z.txt"]
    db.refresh(prop)
    row = db.query(Proposal).filter(Proposal.id == prop.id).one()
    assert row.status == "accepted"
    assert (row.payload_json or {}).get("applied_paths") == ["z.txt"]
    files = (row.payload_json or {}).get("applied_files") or []
    assert files[0]["path"] == "z.txt"
    assert files[0]["preimage_sha256"]
    assert files[0]["postimage_sha256"]


def test_code_patch_rejects_path_traversal_before_write(db, test_user, test_space, tmp_path, monkeypatch):
    from app.proposals import ProposalService

    a = test_space.id
    ua = test_user
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "../escape.txt",
                        "content": "x",
                        "preimage_exists": False,
                        "preimage_sha256": None,
                    }
                ]
            },
        },
        commit=True,
    )

    with pytest.raises(Exception) as excinfo:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert "path traversal" in str(excinfo.value)
    assert not (ws_root / "escape.txt").exists()
    db.refresh(prop)
    assert prop.status == "pending"


def test_code_patch_file_write_failure_does_not_mark_success(db, test_user, test_space, tmp_path, monkeypatch):
    from app.proposals import ProposalService
    import app.memory.code_patch_apply as patch_mod

    a = test_space.id
    ua = test_user
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    target = disk / "a.txt"
    original = b"before"
    target.write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "a.txt",
                        "content": "after",
                        "preimage_exists": True,
                        "preimage_sha256": _sha256(original),
                    }
                ]
            },
        },
        commit=True,
    )

    def fail_replace(*args, **kwargs):
        raise OSError("disk full at /private/path")

    monkeypatch.setattr(patch_mod.os, "replace", fail_replace)

    with pytest.raises(Exception) as excinfo:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert "private/path" not in str(excinfo.value)
    assert target.read_text(encoding="utf-8") == "before"
    db.refresh(prop)
    assert prop.status == "pending"


def test_code_patch_db_failure_after_file_write_rolls_back_file(db, test_user, test_space, tmp_path, monkeypatch):
    from app.proposals import ProposalService

    a = test_space.id
    ua = test_user
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    target = disk / "db-fail.txt"
    original = b"before"
    target.write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "db-fail.txt",
                        "content": "after",
                        "preimage_exists": True,
                        "preimage_sha256": _sha256(original),
                    }
                ]
            },
        },
        commit=True,
    )

    real_commit = db.commit
    calls = {"n": 0}

    def fail_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("commit failed")
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_once)

    with pytest.raises(RuntimeError, match="commit failed"):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert target.read_text(encoding="utf-8") == "before"


def test_code_patch_rollback_failure_reports_partial_apply(db, test_user, test_space, tmp_path, monkeypatch):
    from app.memory.code_patch_apply import CodePatchFileTransaction, CodePatchPartialApplyError
    from app.proposals import ProposalService

    a = test_space.id
    ua = test_user
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    target = disk / "partial.txt"
    original = b"before"
    target.write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "partial.txt",
                        "content": "after",
                        "preimage_exists": True,
                        "preimage_sha256": _sha256(original),
                    }
                ]
            },
        },
        commit=True,
    )

    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    monkeypatch.setattr(
        CodePatchFileTransaction,
        "rollback",
        lambda self: (_ for _ in ()).throw(CodePatchPartialApplyError("rollback failed")),
    )

    with pytest.raises(CodePatchPartialApplyError, match="file rollback failed"):
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert target.read_text(encoding="utf-8") == "after"
