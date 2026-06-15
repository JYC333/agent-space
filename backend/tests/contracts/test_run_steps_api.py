"""HTTP contract: GET /runs/{run_id}/steps endpoint (M3)."""
from __future__ import annotations

from tests.support import factories


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def test_steps_endpoint_returns_page_schema(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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

    cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a),
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(a),
    )
    assert r.status_code == 200
    page = r.json()
    assert set(page.keys()) >= {"items", "total", "limit", "offset"}
    assert isinstance(page["items"], list)
    assert page["total"] >= 1


def test_steps_endpoint_items_have_required_fields(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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

    cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a),
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(a),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1

    required_fields = {"id", "space_id", "run_id", "actor_id", "step_index", "step_type", "status"}
    for item in items:
        assert required_fields <= set(item.keys()), f"missing fields in {item}"
        assert item["space_id"] == a
        assert item["run_id"] == run.id
        assert item["actor_id"] is not None


def test_steps_endpoint_items_ordered_by_step_index(api_client, db, cross_space_pair, tmp_path, monkeypatch):
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

    cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a),
    )

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(a),
    )
    items = r.json()["items"]
    indexes = [it["step_index"] for it in items]
    assert indexes == sorted(indexes)


def test_steps_endpoint_cross_space_returns_404(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    r = cross_space_pair["client_b"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(b),
    )
    assert r.status_code == 404


def test_steps_endpoint_execution_step_types_present_after_success(
    api_client, db, cross_space_pair, tmp_path, monkeypatch
):
    """Contract: an executed run must surface the coarse execution step types."""
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

    ex = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run.id}/execute",
        params=_params(a),
    )
    assert ex.status_code == 200

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(a),
    )
    assert r.status_code == 200
    types = {it["step_type"] for it in r.json()["items"]}
    assert "queued" in types
    assert "completed" in types or any(t in types for t in ("failed", "adapter_started"))


def test_steps_endpoint_empty_run_returns_empty_page(api_client, db, cross_space_pair):
    """A run that has never been executed has no steps."""
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)

    r = cross_space_pair["client_a"].get(
        f"/api/v1/runs/{run.id}/steps",
        params=_params(a),
    )
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == 0
    assert page["items"] == []
