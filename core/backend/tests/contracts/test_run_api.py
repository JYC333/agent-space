"""HTTP contract: runs, nested collections, and execute semantics are space-scoped."""

from __future__ import annotations

from tests.support import factories
from app.models import AgentVersion


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_get_run_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    r = api_client.get(
        f"/api/v1/runs/{run.id}",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404
    err = r.json()
    assert err.get("error") == "not_found"


def test_list_run_activities_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    factories.create_test_activity(
        db,
        space_id=a,
        actor_user_id=ua.id,
        activity_type="run.execution.started",
        source_run_id=run.id,
        commit=True,
    )
    r = api_client.get(
        f"/api/v1/runs/{run.id}/activities",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_list_run_artifacts_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    factories.create_test_artifact(db, space_id=a, run_id=run.id, commit=True)
    r = api_client.get(
        f"/api/v1/runs/{run.id}/artifacts",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_list_run_proposals_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    factories.create_test_proposal(
        db,
        space_id=a,
        run_id=run.id,
        created_by_user_id=ua.id,
        commit=True,
    )
    r = api_client.get(
        f"/api/v1/runs/{run.id}/proposals",
        params=_params(b, ub.id),
    )
    assert r.status_code == 404


def test_run_detail_success_has_stable_fields(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    r = api_client.get(f"/api/v1/runs/{run.id}", params=_params(a, ua.id))
    assert r.status_code == 200
    out = r.json()
    for key in (
        "id",
        "space_id",
        "status",
        "mode",
        "run_type",
        "agent_id",
        "agent_version_id",
        "error_message",
        "error_json",
        "output_json",
    ):
        assert key in out


def test_terminal_run_re_execute_returns_409(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    ex1 = api_client.post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a, ua.id),
    )
    assert ex1.status_code == 200
    assert ex1.json().get("status") in ("succeeded", "failed")

    ex2 = api_client.post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a, ua.id),
    )
    assert ex2.status_code == 409
    assert ex2.json().get("error") == "conflict"


def test_run_execution_surfaces_audit_activity_types(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    ex = api_client.post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a, ua.id),
    )
    assert ex.status_code == 200

    r = api_client.get(
        f"/api/v1/runs/{run.id}/activities",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    page = r.json()
    assert set(page.keys()) >= {"items", "total", "limit", "offset"}
    types = {it.get("activity_type") for it in page["items"]}
    assert "run.execution.started" in types
    assert ("run.execution.succeeded" in types) or ("run.execution.failed" in types)


def test_execute_with_disabled_runtime_adapter_marks_run_failed(api_client, db, cross_space_pair):
    """Product contract: POST execute attempts execution and returns the updated Run.

    A disabled ``RuntimeAdapter`` is not a client request validation error: the
    server performs resolution, marks the run **failed**, and returns **HTTP 200**
    with ``error_json.error_code == adapter_disabled``. This matches
    ``RunExecutionService`` semantics (mutation + auditable failure), not
    ``409`` pre-flight rejection.
    """
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    disabled = factories.create_test_runtime_adapter(
        db,
        space_id=a,
        name="disabled-echo",
        adapter_type="echo",
        enabled=False,
        commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    ver_row = (
        db.query(AgentVersion)
        .filter(AgentVersion.id == agent.current_version_id)
        .first()
    )
    assert ver_row is not None
    ver_row.runtime_adapter_id = disabled.id
    db.commit()

    run = factories.create_test_run(
        db, space_id=a, user_id=ua.id, agent=agent, commit=True,
    )
    r = api_client.post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a, ua.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "failed"
    err = body.get("error_json") or {}
    assert err.get("error_code") == "adapter_disabled"
