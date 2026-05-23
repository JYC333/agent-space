"""API contract tests for the run finalization surface."""
from __future__ import annotations

from ulid import ULID

from app.models import Task, TaskRun
from tests.support import factories


def _id() -> str:
    return str(ULID())


def _params(space_id: str) -> dict[str, str]:
    return {"space_id": space_id}


def _terminal_run(db, *, space_id: str, user_id: str, status: str = "succeeded"):
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id)
    run.status = status
    db.commit()
    return run


def _task_link(db, *, space_id: str, user_id: str, run):
    task = Task(
        id=_id(),
        space_id=space_id,
        title="test task",
        task_type="general",
        status="inbox",
        priority="normal",
        risk_level="low",
        created_by_user_id=user_id,
    )
    db.add(task)
    db.flush()
    link = TaskRun(id=_id(), space_id=space_id, task_id=task.id, run_id=run.id, role="primary")
    db.add(link)
    db.commit()
    return task


class TestPostFinalize:
    def test_finalize_succeeded_run_returns_finalization_out(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        r = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )

        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == run.id
        assert body["status"] == "completed"
        assert body["run_evaluation_id"] is not None
        assert "finalizer_version" in body
        assert "finalized_at" in body
        assert "created_at" in body

    def test_finalize_non_terminal_run_returns_422(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = factories.create_test_run(db, space_id=space, user_id=user.id, commit=True)
        # run is queued by default

        r = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )

        assert r.status_code == 422

    def test_finalize_is_idempotent(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        r1 = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )
        r2 = same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

    def test_finalize_cross_space_returns_404(self, db, cross_space_pair):
        space_b = cross_space_pair["space_b_id"]
        user_b = cross_space_pair["user_b"]
        space_a = cross_space_pair["space_a_id"]
        run = _terminal_run(db, space_id=space_b, user_id=user_b.id, status="succeeded")

        r = cross_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space_a),
        )

        assert r.status_code == 404


class TestGetFinalization:
    def test_get_finalization_returns_latest(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )

        r = same_space_pair["client_a"].get(
            f"/api/v1/runs/{run.id}/finalization",
            params=_params(space),
        )

        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == run.id
        assert body["status"] == "completed"

    def test_get_finalization_404_when_not_finalized(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        r = same_space_pair["client_a"].get(
            f"/api/v1/runs/{run.id}/finalization",
            params=_params(space),
        )

        assert r.status_code == 404


class TestListFinalizations:
    def test_list_finalizations_returns_records(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        same_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/finalize",
            params=_params(space),
        )

        r = same_space_pair["client_a"].get(
            f"/api/v1/runs/{run.id}/finalizations",
            params=_params(space),
        )

        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["run_id"] == run.id

    def test_list_finalizations_empty_when_not_finalized(self, db, same_space_pair):
        space = same_space_pair["space_id"]
        user = same_space_pair["user_a"]
        run = _terminal_run(db, space_id=space, user_id=user.id, status="succeeded")

        r = same_space_pair["client_a"].get(
            f"/api/v1/runs/{run.id}/finalizations",
            params=_params(space),
        )

        assert r.status_code == 200
        assert r.json() == []
