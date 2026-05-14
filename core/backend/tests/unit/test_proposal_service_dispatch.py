"""ProposalService dispatches memory_update vs code_patch; unsupported types raise."""

from __future__ import annotations

import pytest

from app.memory.proposals import ProposalService, UnsupportedProposalTypeError
from tests.support import factories


def test_unsupported_proposal_type_raises_at_service_boundary(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="unknown_dispatch_type",
        commit=True,
    )
    with pytest.raises(UnsupportedProposalTypeError) as ei:
        ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert ei.value.proposal_type == "unknown_dispatch_type"


def test_memory_update_accept_uses_memory_applier_path(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is not None and out.updated_paths is None
    assert out.proposal.status == "accepted"


def test_code_patch_accept_uses_code_patch_applier_path(db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import settings

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
    (disk / "c.txt").write_text("0", encoding="utf-8")

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="cp",
        payload_json={
            "patch": {"operations": [{"op": "replace_file", "path": "c.txt", "content": "1"}]},
        },
        commit=True,
    )
    out = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert out is not None
    assert out.memory is None and out.updated_paths == ["c.txt"]
    assert out.proposal.status == "accepted"
