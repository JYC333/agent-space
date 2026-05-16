"""HTTP contract: code_patch accept response and cross-space deny (apply path)."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_accept_code_patch_returns_kind_and_paths(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
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
    (disk / "a.txt").write_text("0", encoding="utf-8")

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="t",
        payload_json={
            "patch": {
                "operations": [{"op": "replace_file", "path": "a.txt", "content": "1"}],
            },
            "source_run_id": None,
        },
        commit=True,
    )

    r = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    js = r.json()
    assert js.get("result_type") == "code_patch_apply"
    assert js.get("result", {}).get("updated_paths") == ["a.txt"]
    assert js.get("proposal", {}).get("id") == prop.id


def test_accept_code_patch_cross_space_returns_404(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    db.commit()
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

    ws = factories.create_test_workspace(db, space_id=a, created_by_user_id=ua.id, commit=True)
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="x",
        payload_json={
            "patch": {"operations": [{"op": "replace_file", "path": "f.txt", "content": ""}]},
        },
        commit=True,
    )
    r = cross_space_pair["client_b"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    body = r.json()
    assert body.get("error") == "not_found"
    assert "message" in body
