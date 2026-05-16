"""HTTP contract: general proposal API — list, detail, accept, reject."""

from __future__ import annotations

from sqlalchemy import func

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.config import settings
from app.main import app as _app
from starlette.testclient import TestClient
from app.models import MemoryEntry, Proposal
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def _assert_error_envelope(body: dict, *, error: str) -> None:
    assert body.get("error") == error
    assert "message" in body


def test_get_proposal_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    r = cross_space_pair["client_b"].get(
        f"/api/v1/proposals/{prop.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")


def test_accept_proposal_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    r = cross_space_pair["client_b"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")


def test_reject_proposal_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    r = cross_space_pair["client_b"].post(
        f"/api/v1/proposals/{prop.id}/reject",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")


def test_non_creator_cannot_accept_in_same_space(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    u_other = factories.create_test_user(db, space_id=a, display_name="Other A", commit=True)
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    _, raw = UserSessionService(db).create(u_other.id)
    other_client = TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)
    r = other_client.post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, u_other.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")


def test_non_creator_cannot_reject_in_same_space(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    u_other = factories.create_test_user(db, space_id=a, display_name="Other Rej", commit=True)
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    _, raw = UserSessionService(db).create(u_other.id)
    other_client = TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)
    r = other_client.post(
        f"/api/v1/proposals/{prop.id}/reject",
        params=_params(a, u_other.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")


def test_preview_proposal_accept_returns_404_no_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        preview=True,
        commit=True,
    )
    before = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    r = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r.status_code == 404
    _assert_error_envelope(r.json(), error="not_found")
    db.expire_all()
    after = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after == before
    row = db.query(Proposal).filter(Proposal.id == prop.id).first()
    assert row is not None and row.status == "pending"


def test_rejected_proposal_cannot_be_accepted(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    r1 = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/reject",
        params=_params(a, ua.id),
    )
    assert r1.status_code == 200
    out = r1.json()
    assert out.get("status") == "rejected"

    r2 = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r2.status_code == 404
    _assert_error_envelope(r2.json(), error="not_found")


def test_memory_update_accept_returns_general_shape_and_creates_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        preview=False,
        commit=True,
    )
    r = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("result_type") == "memory_entry"
    assert "proposal" in body and body["proposal"].get("id") == prop.id
    mem = body.get("result", {}).get("memory")
    assert mem and mem.get("content") == "proposed text"
    db.refresh(prop)
    assert prop.status == "accepted"
    assert prop.resulting_memory_id == mem.get("id")


def test_double_accept_does_not_duplicate_memory(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        preview=False,
        commit=True,
    )
    r1 = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r1.status_code == 200
    mem_id = r1.json().get("result", {}).get("memory", {}).get("id")
    assert mem_id

    r2 = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r2.status_code == 404
    _assert_error_envelope(r2.json(), error="not_found")

    n = (
        db.query(func.count(MemoryEntry.id))
        .filter(
            MemoryEntry.space_id == a,
            MemoryEntry.source_proposal_id == prop.id,
            MemoryEntry.status == "active",
        )
        .scalar()
    )
    assert n == 1


def test_code_patch_accept_returns_general_shape(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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


def test_policy_change_accept_returns_policy_version_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="policy_change",
        title="Require review",
        payload_json={
            "domain": "memory",
            "policy_key": "memory.require_review",
            "policy_version": 2,
            "rule_json": {"requires_review": True},
            "enforcement_mode": "require_approval",
        },
        commit=True,
    )

    r = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )

    assert r.status_code == 200, r.text
    js = r.json()
    assert js.get("result_type") == "policy_version"
    assert js.get("result", {}).get("policy_id")
    assert js.get("result", {}).get("policy_version") == 2
    assert js.get("proposal", {}).get("id") == prop.id


def test_double_accept_code_patch_does_not_reapply(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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
    (disk / "b.txt").write_text("x", encoding="utf-8")

    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="cp",
        payload_json={
            "patch": {
                "operations": [{"op": "replace_file", "path": "b.txt", "content": "y"}],
            },
        },
        commit=True,
    )
    r1 = cross_space_pair["client_a"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(a, ua.id))
    assert r1.status_code == 200
    assert (disk / "b.txt").read_text(encoding="utf-8") == "y"

    r2 = cross_space_pair["client_a"].post(f"/api/v1/proposals/{prop.id}/accept", params=_params(a, ua.id))
    assert r2.status_code == 404
    _assert_error_envelope(r2.json(), error="not_found")
    assert (disk / "b.txt").read_text(encoding="utf-8") == "y"


def test_unsupported_proposal_type_accept_stable_error_no_mutation(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    before_mem = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="legacy_tool_call",
        commit=True,
    )
    r = cross_space_pair["client_a"].post(
        f"/api/v1/proposals/{prop.id}/accept",
        params=_params(a, ua.id),
    )
    assert r.status_code == 409
    body = r.json()
    assert body.get("error") == "conflict"
    msg = body.get("message")
    assert isinstance(msg, dict)
    assert msg.get("code") == "unsupported_proposal_type"
    assert msg.get("proposal_type") == "legacy_tool_call"
    db.refresh(prop)
    assert prop.status == "pending"
    after_mem = (
        db.query(func.count(MemoryEntry.id))
        .filter(MemoryEntry.space_id == a, MemoryEntry.status == "active")
        .scalar()
    )
    assert after_mem == before_mem


def test_list_proposals_page_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        commit=True,
    )
    r = cross_space_pair["client_a"].get("/api/v1/proposals", params=_params(a, ua.id))
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"items", "total", "limit", "offset"}
    assert isinstance(data["items"], list)


def test_list_proposals_default_returns_pending_only(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    p_pending = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="pending", title="pen", commit=True
    )
    p_accepted = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="accepted", title="acc", commit=True
    )
    p_rejected = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="rejected", title="rej", commit=True
    )
    r = cross_space_pair["client_a"].get("/api/v1/proposals", params=_params(a, ua.id))
    assert r.status_code == 200
    data = r.json()
    ids = {x["id"] for x in data["items"]}
    assert p_pending.id in ids
    assert p_accepted.id not in ids
    assert p_rejected.id not in ids
    assert set(data.keys()) >= {"items", "total", "limit", "offset"}


def test_list_proposals_explicit_status_filters(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    p_pending = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="pending", title="p1", commit=True
    )
    p_accepted = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="accepted", title="p2", commit=True
    )
    p_rejected = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="rejected", title="p3", commit=True
    )
    rp = cross_space_pair["client_a"].get("/api/v1/proposals", params={**_params(a, ua.id), "status": "pending"})
    assert rp.status_code == 200
    assert p_pending.id in {x["id"] for x in rp.json()["items"]}

    ra = cross_space_pair["client_a"].get("/api/v1/proposals", params={**_params(a, ua.id), "status": "accepted"})
    assert ra.status_code == 200
    assert p_accepted.id in {x["id"] for x in ra.json()["items"]}

    rr = cross_space_pair["client_a"].get("/api/v1/proposals", params={**_params(a, ua.id), "status": "rejected"})
    assert rr.status_code == 200
    assert p_rejected.id in {x["id"] for x in rr.json()["items"]}


def test_list_proposals_status_all_includes_decided(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    p_pending = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="pending", title="a", commit=True
    )
    p_accepted = factories.create_test_proposal(
        db, space_id=a, created_by_user_id=ua.id, status="accepted", title="b", commit=True
    )
    r = cross_space_pair["client_a"].get("/api/v1/proposals", params={**_params(a, ua.id), "status": "all"})
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["items"]}
    assert p_pending.id in ids and p_accepted.id in ids


def test_list_proposals_excludes_other_space(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    factories.create_test_proposal(db, space_id=b, created_by_user_id=ub.id, commit=True)
    p_a = factories.create_test_proposal(db, space_id=a, created_by_user_id=ua.id, commit=True)
    r = cross_space_pair["client_a"].get("/api/v1/proposals", params=_params(a, ua.id))
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["items"]}
    assert p_a.id in ids
    assert all(row.get("space_id") == a for row in r.json()["items"])


def test_list_proposals_invalid_status_returns_422(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    r = cross_space_pair["client_a"].get("/api/v1/proposals", params={**_params(a, ua.id), "status": "not_a_status"})
    assert r.status_code == 422
    body = r.json()
    assert body.get("error") == "validation_error"
    assert "message" in body


def test_get_proposal_detail_general_shape(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    existing = factories.create_test_memory_entry(
        db,
        space_id=a,
        content="seed",
        scope_type="agent",
        namespace="agent.test",
        owner_user_id=ua.id,
        commit=True,
    )
    existing.visibility = "space_shared"
    db.commit()
    prop = factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        proposal_type="memory_update",
        payload_json={
            "operation": "update",
            "target_memory_id": existing.id,
            "proposed_content": "proposed text",
            "memory_type": "semantic",
            "target_scope": "agent",
            "target_namespace": "agent.test",
            "target_visibility": "private",
            "sensitivity_level": "normal",
        },
        commit=True,
    )
    r = cross_space_pair["client_a"].get(f"/api/v1/proposals/{prop.id}", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    assert out.get("id") == prop.id
    assert out.get("proposal_type") == "memory_update"
    assert "proposed_title" in out and "status" in out
