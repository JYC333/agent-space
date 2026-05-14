"""Home summary aggregates reflect durable workflow state and tenant boundaries."""

from __future__ import annotations

from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    return {"space_id": space_id, "user_id": user_id}


def test_home_summary_tracks_activity_proposals_runs_and_excludes_other_space(
    api_client, db, cross_space_pair
):
    db.commit()
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]

    empty_a = api_client.get("/api/v1/home/summary", params=_params(a, ua.id)).json()
    empty_b = api_client.get("/api/v1/home/summary", params=_params(b, ub.id)).json()
    assert empty_a["pending_proposals"]["count"] == 0
    assert empty_a["activity_summary"]["raw_count"] == 0
    assert len(empty_a["active_runs"]) == 0
    assert empty_b["pending_proposals"]["count"] == 0

    api_client.post(
        "/api/v1/activity",
        params=_params(a, ua.id),
        json={"source_type": "user_input", "content": "home-wf", "title": "t"},
    )
    factories.create_test_proposal(
        db,
        space_id=a,
        created_by_user_id=ua.id,
        status="pending",
        commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    db.commit()

    filled_a = api_client.get("/api/v1/home/summary", params=_params(a, ua.id)).json()
    assert filled_a["activity_summary"]["raw_count"] >= 1
    assert filled_a["pending_proposals"]["count"] >= 1
    assert len(filled_a["active_runs"]) >= 1
    active_ids = {r["id"] for r in filled_a["active_runs"]}
    assert run.id in active_ids

    still_b = api_client.get("/api/v1/home/summary", params=_params(b, ub.id)).json()
    assert still_b["activity_summary"]["raw_count"] == 0
    assert still_b["pending_proposals"]["count"] == 0
    assert len(still_b["active_runs"]) == 0


def test_home_summary_suggests_runtime_when_space_has_no_enabled_adapter(
    api_client, db, cross_space_pair
):
    db.commit()
    b = cross_space_pair["space_b_id"]
    ub = cross_space_pair["user_b"]
    data = api_client.get("/api/v1/home/summary", params=_params(b, ub.id)).json()
    if data["runtime_status"]["real_adapters_configured_count"] == 0:
        labels = {a["id"] for a in data["suggested_actions"]}
        assert "configure-runtime-adapter" in labels
