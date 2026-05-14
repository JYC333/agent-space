"""Workspace console: safe reads and path policy — no code_patch proposal path in product yet."""

from __future__ import annotations

from app.config import settings
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_workspace_console_list_read_and_traversal_denied_without_leakage(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    db.commit()
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
        name="wf-workspace",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "notes.txt").write_text("INNER_OK", encoding="utf-8")
    (ws_root / "outside.txt").write_text("OUTSIDE_SECRET", encoding="utf-8")

    listed = api_client.get(
        "/api/v1/workspace-console/workspaces",
        params=_params(b, ub.id),
    )
    assert listed.status_code == 200
    ids = {w["id"] for w in listed.json().get("items", [])}
    assert ws.id not in ids

    ok = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "notes.txt"},
    )
    assert ok.status_code == 200
    assert ok.json()["content"] == "INNER_OK"

    bad = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "../outside.txt"},
    )
    assert bad.status_code == 403
    assert "OUTSIDE_SECRET" not in bad.text

    outside = tmp_path / "abs_secret.txt"
    outside.write_text("ABS_SECRET", encoding="utf-8")
    abs_try = api_client.get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": str(outside)},
    )
    assert abs_try.status_code in (400, 403, 404)
    assert "ABS_SECRET" not in abs_try.text
