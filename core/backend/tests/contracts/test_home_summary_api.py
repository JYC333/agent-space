"""HTTP contract: home summary is space-scoped with a stable aggregate shape."""

from __future__ import annotations
import uuid


from app.auth.session import SESSION_COOKIE, UserSessionService
from app.main import app as _app
from starlette.testclient import TestClient
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_home_summary_empty_stable_shape(api_client, db):
    sid = str(uuid.uuid4())
    factories.create_test_space(db, space_id=sid, name="Empty Home", space_type="team", commit=True)
    u = factories.create_test_user(db, space_id=sid, commit=True)
    _, raw = UserSessionService(db).create(u.id)
    authed = TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)
    r = authed.get(
        "/api/v1/home/summary",
        params=_params(sid, u.id),
    )
    assert r.status_code == 200
    data = r.json()
    for key in (
        "recent_runs",
        "active_runs",
        "pending_proposals",
        "recent_artifacts",
        "task_summary",
        "active_tasks",
        "activity_summary",
        "run_stats_today",
        "job_queue_status",
        "runtime_status",
        "model_provider_status",
        "suggested_actions",
    ):
        assert key in data, f"missing {key}"
    assert isinstance(data["recent_runs"], list)
    assert isinstance(data["active_runs"], list)
    assert isinstance(data["suggested_actions"], list)
    pp = data["pending_proposals"]
    assert set(pp.keys()) >= {"count", "items"}
    assert pp["count"] == 0
    act = data["activity_summary"]
    assert set(act.keys()) >= {"recent_count", "raw_count", "today_count"}
    rt = data["runtime_status"]
    assert set(rt.keys()) >= {
        "real_adapters_configured_count",
        "configured_adapter_types",
        "message",
    }
    mp = data["model_provider_status"]
    assert set(mp.keys()) >= {
        "model_providers_count",
        "enabled_model_providers_count",
        "missing_model_provider_config",
        "message",
    }


def test_home_summary_counts_scoped_and_consistent(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]

    factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        status="pending",
        commit=True,
    )
    factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="user_input",
        commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    factories.create_test_run(
        db,
        space_id=a,
        user_id=ua.id,
        agent=agent,
        commit=True,
    )

    ra = cross_space_pair["client_a"].get("/api/v1/home/summary", params=_params(a, ua.id))
    assert ra.status_code == 200
    ja = ra.json()
    assert ja["pending_proposals"]["count"] >= 1
    assert ja["activity_summary"]["raw_count"] >= 1
    assert len(ja["active_runs"]) >= 1

    rb = cross_space_pair["client_b"].get("/api/v1/home/summary", params=_params(b, ub.id))
    assert rb.status_code == 200
    jb = rb.json()
    assert jb["pending_proposals"]["count"] == 0
    assert jb["activity_summary"]["raw_count"] == 0
    assert len(jb["active_runs"]) == 0


def test_home_summary_runtime_suggested_when_no_enabled_adapters(api_client, db, cross_space_pair):
    b = cross_space_pair["space_b_id"]
    ub = cross_space_pair["user_b"]
    r = cross_space_pair["client_b"].get("/api/v1/home/summary", params=_params(b, ub.id))
    assert r.status_code == 200
    data = r.json()
    if data["runtime_status"]["real_adapters_configured_count"] == 0:
        labels = {a["id"] for a in data["suggested_actions"]}
        assert "configure-runtime-adapter" in labels
