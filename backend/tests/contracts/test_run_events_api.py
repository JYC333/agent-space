"""HTTP contract: GET /runs/{run_id}/events endpoint."""
from __future__ import annotations

from tests.support import factories


REQUIRED_EVENT_FIELDS = {
    "id", "space_id", "run_id", "event_index", "event_type", "status", "created_at",
}


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def test_events_endpoint_returns_page_schema(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import settings

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params=_params(a),
    )
    assert r.status_code == 200
    page = r.json()
    assert set(page.keys()) >= {"items", "total", "limit", "offset"}
    assert isinstance(page["items"], list)


def test_events_endpoint_items_have_required_fields(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    svc.append_event(run_id=run.id, space_id=a, event_type="runtime_selected", status="succeeded")
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params=_params(a),
    )
    assert r.status_code == 200
    page = r.json()
    assert page["total"] >= 2
    for item in page["items"]:
        assert REQUIRED_EVENT_FIELDS <= set(item.keys()), f"Missing fields in event: {item}"


def test_events_endpoint_ordered_by_event_index(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    svc.append_event(run_id=run.id, space_id=a, event_type="runtime_selected", status="succeeded")
    svc.append_event(run_id=run.id, space_id=a, event_type="adapter_invoked", status="running")
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params=_params(a),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    indexes = [item["event_index"] for item in items]
    assert indexes == sorted(indexes), "Events must be ordered by event_index ascending"


def test_events_endpoint_404_for_unknown_run(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    r = cross_space_pair["client_a"].get(
        "/api/v1/runs/nonexistent-run-id/events",
        params=_params(a),
    )
    assert r.status_code == 404


def test_event_type_filter_total_reflects_filtered_count(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """event_type filter is applied before count — total must equal filtered event count."""
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    for _ in range(3):
        svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    for _ in range(2):
        svc.append_event(run_id=run.id, space_id=a, event_type="runtime_selected", status="succeeded")
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params={"space_id": a, "event_type": "context_compiled"},
    )
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 3
    assert len(page["items"]) == 3
    assert all(item["event_type"] == "context_compiled" for item in page["items"])


def test_status_filter_total_reflects_filtered_count(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """status filter is applied before count — total must equal filtered event count."""
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    svc.append_event(run_id=run.id, space_id=a, event_type="adapter_completed", status="failed",
                     error_code="adapter_runtime_error")
    svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    svc.append_event(run_id=run.id, space_id=a, event_type="runtime_selected", status="succeeded")
    db.commit()

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params={"space_id": a, "status": "failed"},
    )
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["status"] == "failed"


def test_event_type_filter_pagination_is_correct(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    """Filtered total must equal the full filtered set; page must respect limit/offset on that set."""
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    # 5 context_compiled events interleaved with 3 runtime_selected
    for _ in range(5):
        svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    for _ in range(3):
        svc.append_event(run_id=run.id, space_id=a, event_type="runtime_selected", status="succeeded")
    db.commit()

    # page 1: first 3 of 5 context_compiled
    r1 = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params={"space_id": a, "event_type": "context_compiled", "limit": 3, "offset": 0},
    )
    assert r1.status_code == 200
    p1 = r1.json()
    assert p1["total"] == 5       # total = filtered count, not total row count
    assert len(p1["items"]) == 3

    # page 2: remaining 2 of 5 context_compiled
    r2 = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/events",
        params={"space_id": a, "event_type": "context_compiled", "limit": 3, "offset": 3},
    )
    assert r2.status_code == 200
    p2 = r2.json()
    assert p2["total"] == 5
    assert len(p2["items"]) == 2
    assert all(item["event_type"] == "context_compiled" for item in p2["items"])


def test_events_cross_space_access_denied(api_client, db, cross_space_pair, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.events import RunEventService

    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    svc = RunEventService(db)
    svc.append_event(run_id=run.id, space_id=a, event_type="context_compiled", status="succeeded")
    db.commit()

    # Client B tries to access space A's run — must be 404 (not 403, run not found in their space)
    r = cross_space_pair["client_b"].get(
        f"/api/v1/runs/{run.id}/events",
        params={"space_id": b},
    )
    assert r.status_code == 404
