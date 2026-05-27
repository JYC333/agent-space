"""HTTP contract: workspace console file access is space-scoped and path-safe."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.exceptions import PolicyGateBlocked
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _fresh_policy_record(action: str, **filters):
    from app.db import SessionLocal
    from app.models import PolicyDecisionRecord

    fresh = SessionLocal()
    try:
        query = fresh.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == action
        )
        for field, value in filters.items():
            query = query.filter(getattr(PolicyDecisionRecord, field) == value)
        return query.order_by(PolicyDecisionRecord.created_at.desc()).first()
    finally:
        fresh.close()


def _blocked_workspace_read(*, user_id: str, space_id: str, workspace_id: str) -> PolicyGateBlocked:
    return PolicyGateBlocked(
        decision=PolicyDecision(
            decision=Decision.DENY,
            message="workspace read denied",
            risk_level=RiskLevel.LOW,
            reason_code="test_workspace_read_denied",
            audit_code="test_workspace_read_denied",
            policy_source="test",
        ),
        action="workspace.read",
        actor_type="user",
        actor_id=user_id,
        actor_ref=None,
        space_id=space_id,
        resource_type="workspace",
        resource_id=workspace_id,
        run_id=None,
        proposal_id=None,
        metadata_json={"read_kind": "file", "relative_path": "readme.txt"},
        http_status_code=403,
    )


def test_workspace_create_uses_backend_canonical_fields(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    r = cross_space_pair["client_a"].post(
        "/api/v1/workspaces",
        params=_params(a, ua.id),
        json={
            "name": "Research",
            "workspace_type": "project",
            "kind": "research",
            "root_path": str(ws_root / "external-research"),
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body.keys()) >= {
        "id",
        "owner_space_id",
        "created_by_user_id",
        "workspace_type",
        "kind",
        "root_path",
    }
    assert "space_id" not in body
    assert "created_by" not in body
    assert "type" not in body
    assert "path" not in body
    assert body["owner_space_id"] == a
    assert body["created_by_user_id"] == ua.id
    assert body["workspace_type"] == "project"
    assert body["kind"] == "research"
    assert body["root_path"] == str(ws_root / "external-research")


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

    r = cross_space_pair["client_b"].get(
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

    ok = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "readme.txt"},
    )
    assert ok.status_code == 200
    ok_js = ok.json()
    assert set(ok_js.keys()) >= {"path", "content", "size", "line_count"}
    assert ok_js["content"] == "VISIBLE_OK"

    bad = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": "../outside_secret.txt"},
    )
    assert bad.status_code == 403
    assert "LEAK_OUT" not in bad.text


def test_workspace_read_policy_deny_blocks_file_content(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="policy-denied",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    (disk / "readme.txt").write_text("DO_NOT_LEAK", encoding="utf-8")

    with patch("app.workspace_console.api.PolicyGateway") as gateway:
        gateway.return_value.enforce.side_effect = _blocked_workspace_read(
            user_id=ua.id,
            space_id=a,
            workspace_id=ws.id,
        )
        r = cross_space_pair["client_a"].get(
            f"/api/v1/workspace-console/workspaces/{ws.id}/file",
            params={**_params(a, ua.id), "path": "readme.txt"},
        )

    assert r.status_code == 403
    assert r.json().get("error") == "policy_denied"
    assert "DO_NOT_LEAK" not in r.text


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
    r = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/file",
        params={**_params(a, ua.id), "path": str(outside)},
    )
    assert r.status_code in (403, 400, 404)
    assert "OUTSIDE_SECRET" not in r.text


def test_git_diff_output_is_bounded(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    import app.workspace_console.api as workspace_api

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="diff",
        commit=True,
    )
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    huge_diff = "x" * (workspace_api._MAX_DIFF_BYTES + 1024)
    monkeypatch.setattr(workspace_api, "_run_git", lambda *args, **kwargs: huge_diff)

    r = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/git/diff",
        params=_params(a, ua.id),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["truncated"] is True
    assert len(body["diff"].encode("utf-8")) <= workspace_api._MAX_DIFF_BYTES


def test_full_diff_workspace_read_is_force_audited(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    import app.workspace_console.api as workspace_api

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="system-core-read",
        commit=True,
    )
    ws.workspace_type = "system_core"
    ws.system_managed = True
    db.commit()
    disk = ws_root / ws.id
    disk.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        workspace_api,
        "_run_git",
        lambda *args, **kwargs: "diff --git a/readme.txt b/readme.txt\n+safe\n",
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/git/diff",
        params=_params(a, ua.id),
    )

    assert r.status_code == 200, r.text
    record = _fresh_policy_record("workspace.read", resource_id=ws.id)
    assert record is not None
    assert record.decision == "allow"
    assert set(record.metadata_json["audit_reasons"]) >= {"system_core", "full_diff"}


def test_full_diff_secret_values_are_redacted(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    import app.workspace_console.api as workspace_api

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="diff-redact",
        commit=True,
    )
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        workspace_api,
        "_run_git",
        lambda *args, **kwargs: "diff --git a/app.txt b/app.txt\n+API_KEY=supersecret\n",
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/git/diff",
        params=_params(a, ua.id),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["redacted"] is True
    assert "supersecret" not in body["diff"]
    assert "[REDACTED]" in body["diff"]


def test_full_diff_secret_like_paths_are_denied(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    import app.workspace_console.api as workspace_api

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    ws_root = tmp_path / "wsroot"
    ws_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        name="diff-secret-path",
        commit=True,
    )
    (ws_root / ws.id).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        workspace_api,
        "_run_git",
        lambda *args, **kwargs: "diff --git a/.env.local b/.env.local\n+TOKEN=secret\n",
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/workspace-console/workspaces/{ws.id}/git/diff",
        params=_params(a, ua.id),
    )

    assert r.status_code == 403
    assert "secret" not in r.text.lower()
