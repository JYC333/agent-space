"""HTTP contract: workspace console file access is space-scoped and path-safe."""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_workspace_console_list_cross_space_empty(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="A ws",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)

    r = api_client.get(
        "/api/v1/workspace-console/workspaces",
        params=_params(b, ub.id),
    )
    assert r.status_code == 200
    items = r.json().get("items", [])
    assert all(w["id"] != ws.id for w in items)


def test_file_read_success_and_traversal_denied(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="files",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "readme.txt").write_text("VISIBLE_OK", encoding="utf-8")
    (ws_root / "outside_secret.txt").write_text("LEAK_OUT", encoding="utf-8")

    ok = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "readme.txt"},
    )
    assert ok.status_code == 200
    ok_js = ok.json()
    assert set(ok_js.keys()) >= {"path", "content", "size", "line_count"}
    assert ok_js["content"] == "VISIBLE_OK"

    bad = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "../outside_secret.txt"},
    )
    assert bad.status_code == 403
    assert "LEAK_OUT" not in bad.text


def test_file_read_absolute_outside_root_rejected(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="abs",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)

    outside = Path(tmp_path / "secret_outside.txt")
    outside.write_text("OUTSIDE_SECRET", encoding="utf-8")
    r = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": str(outside)},
    )
    assert r.status_code in (403, 400, 404)
    assert "OUTSIDE_SECRET" not in r.text
