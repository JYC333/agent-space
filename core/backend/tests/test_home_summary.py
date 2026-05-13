"""Home summary API (read-only aggregation)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

pytestmark = pytest.mark.canonical

from app.agents.agent_service import AgentService
from app.models import ActivityRecord, Agent, AgentVersion, Artifact, Job, Proposal, Run, RuntimeAdapter
from app.runs.run_service import RunService
from app.schemas import AgentCreate, RunCreate, TaskCreate
from app.tasks.service import TaskService
from tests.conftest import SPACE, USER, ensure_space, ensure_user

AUTH = f"space_id={SPACE}&user_id={USER}"


def _new_id() -> str:
    return str(ULID())


def _seed_agent(db) -> Agent:
    return AgentService(db).create(
        AgentCreate(name="Home summary test agent"),
        requesting_user_id=USER,
    )


def _create_run(db, agent: Agent, **kwargs) -> Run:
    data = RunCreate(**kwargs) if kwargs else RunCreate()
    return RunService(db).create_run(
        agent_id=agent.id,
        data=data,
        space_id=SPACE,
        user_id=USER,
    )


def test_home_summary_200_and_sections(client, db):
    r = client.get(f"/api/v1/home/summary?{AUTH}")
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
        "suggested_actions",
    ):
        assert key in data
    assert "count" in data["pending_proposals"]
    assert "items" in data["pending_proposals"]
    assert "real_adapters_configured_count" in data["runtime_status"]


def test_recent_runs_only_current_space(client, db):
    ensure_space(db, "space-9b", "S9b")
    ensure_user(db, "u9b", "space-9b")
    aid = _new_id()
    vid = _new_id()
    db.add(
        Agent(
            id=aid,
            space_id="space-9b",
            owner_user_id="u9b",
            name="Other agent",
        )
    )
    db.add(
        AgentVersion(
            id=vid,
            agent_id=aid,
            space_id="space-9b",
            version_label="v1",
        )
    )
    db.commit()
    rid_other = _new_id()
    db.add(
        Run(
            id=rid_other,
            space_id="space-9b",
            agent_id=aid,
            agent_version_id=vid,
            status="succeeded",
            mode="live",
        )
    )
    db.commit()

    agent = _seed_agent(db)
    run_local = RunService(db).create_run(
        agent_id=agent.id,
        data=RunCreate(),
        space_id=SPACE,
        user_id=USER,
    )
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    run_ids = {x["id"] for x in res.json()["recent_runs"]}
    assert run_local.id in run_ids
    assert rid_other not in run_ids


def test_active_runs_status_filter(client, db):
    agent = _seed_agent(db)
    rq = _create_run(db, agent)
    db.query(Run).filter(Run.id == rq.id).update({"status": "running"})
    db.commit()
    _create_run(db, agent)
    ok = _create_run(db, agent)
    db.query(Run).filter(Run.id == ok.id).update({"status": "succeeded"})
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    active = res.json()["active_runs"]
    for row in active:
        assert row["status"] in ("queued", "running", "waiting_for_review")


def test_pending_proposals_count_and_preview(client, db):
    now = datetime.now(UTC)
    p1 = Proposal(
        id=_new_id(),
        space_id=SPACE,
        proposal_type="memory_update",
        status="pending",
        title="T1",
        payload_json={"proposed_content": "x"},
        created_by_user_id=USER,
        urgency="high",
        expires_at=now + timedelta(days=1),
    )
    p2 = Proposal(
        id=_new_id(),
        space_id=SPACE,
        proposal_type="memory_update",
        status="waiting_for_review",
        title="T2",
        payload_json={"proposed_content": "y"},
        created_by_user_id=USER,
        review_deadline=now + timedelta(days=2),
        preview=True,
    )
    p3 = Proposal(
        id=_new_id(),
        space_id=SPACE,
        proposal_type="memory_update",
        status="accepted",
        title="Done",
        payload_json={"proposed_content": "z"},
        created_by_user_id=USER,
    )
    db.add_all([p1, p2, p3])
    db.commit()

    res = client.get(f"/api/v1/home/summary?{AUTH}")
    sec = res.json()["pending_proposals"]
    assert sec["count"] == 2
    titles = {x["title"] for x in sec["items"]}
    assert titles == {"T1", "T2"}
    hi = next(x for x in sec["items"] if x["title"] == "T1")
    assert hi["urgency"] == "high"
    assert hi["expires_at"] is not None
    assert hi["expired"] is False
    pr = next(x for x in sec["items"] if x["title"] == "T2")
    assert pr["preview"] is True


def test_expired_proposal_item(client, db):
    now = datetime.now(UTC)
    p = Proposal(
        id=_new_id(),
        space_id=SPACE,
        proposal_type="memory_update",
        status="pending",
        title="Expired",
        payload_json={},
        created_by_user_id=USER,
        expires_at=now - timedelta(hours=1),
    )
    db.add(p)
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    item = next(x for x in res.json()["pending_proposals"]["items"] if x["title"] == "Expired")
    assert item["expired"] is True


def test_recent_artifacts_no_content_column(client, db):
    agent = _seed_agent(db)
    run = _create_run(db, agent)
    db.add(
        Artifact(
            id=_new_id(),
            space_id=SPACE,
            run_id=run.id,
            artifact_type="log",
            title="Art",
            content="SECRET BODY NOT IN RESPONSE",
            preview=True,
        )
    )
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    arts = res.json()["recent_artifacts"]
    assert len(arts) >= 1
    art = arts[0]
    assert "content" not in art
    assert "SECRET" not in res.text


def test_task_summary_and_active_tasks(client, db):
    TaskService(db).create(
        TaskCreate(title="Open A", status="inbox"),
        SPACE,
        USER,
    )
    TaskService(db).create(
        TaskCreate(title="Review me", status="needs_review"),
        SPACE,
        USER,
    )
    TaskService(db).create(
        TaskCreate(title="Blocked", status="blocked"),
        SPACE,
        USER,
    )
    TaskService(db).create(
        TaskCreate(title="Done", status="done"),
        SPACE,
        USER,
    )
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    ts = res.json()["task_summary"]
    assert ts["needs_review_count"] >= 1
    assert ts["blocked_count"] >= 1
    assert ts["done_count"] >= 1
    assert ts["total_open"] >= 3
    active = res.json()["active_tasks"]
    statuses = {t["status"] for t in active}
    assert "done" not in statuses
    assert "cancelled" not in statuses
    assert all(
        t["status"] in ("inbox", "ready", "claimed", "in_progress", "needs_review", "blocked")
        for t in active
    )


def test_run_stats_today(client, db):
    agent = _seed_agent(db)
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    old_run = _create_run(db, agent)
    db.query(Run).filter(Run.id == old_run.id).update(
        {
            "created_at": day_start - timedelta(days=1),
            "status": "failed",
        }
    )
    _create_run(db, agent, mode="dry_run")
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    st = res.json()["run_stats_today"]
    assert st["created"] >= 1
    assert st["dry_run_count"] >= 1


def test_job_queue_status(client, db):
    db.add(
        Job(
            id=_new_id(),
            space_id=SPACE,
            job_type="test",
            status="pending",
        )
    )
    db.add(
        Job(
            id=_new_id(),
            space_id=SPACE,
            job_type="test",
            status="running",
        )
    )
    db.add(
        Job(
            id=_new_id(),
            space_id=SPACE,
            job_type="test",
            status="failed",
            error="boom",
            attempts=0,
            max_attempts=3,
        )
    )
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    jq = res.json()["job_queue_status"]
    assert jq["queued"] >= 1
    assert jq["running"] >= 1
    assert jq["failed"] >= 1
    assert jq["retryable"] >= 1


def test_runtime_status_and_suggested_actions(client, db):
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    rt = res.json()["runtime_status"]
    assert rt["real_adapters_configured_count"] == 0
    assert isinstance(rt["configured_adapter_types"], list)
    labels = [a["label"] for a in res.json()["suggested_actions"]]
    assert any("runtime adapter" in x.lower() for x in labels)

    db.add(
        RuntimeAdapter(
            id=_new_id(),
            space_id=SPACE,
            name="Echo",
            adapter_type="echo",
            enabled=True,
        )
    )
    db.commit()
    res2 = client.get(f"/api/v1/home/summary?{AUTH}")
    assert res2.json()["runtime_status"]["real_adapters_configured_count"] == 1
    labels2 = [a["label"] for a in res2.json()["suggested_actions"]]
    assert not any("runtime adapter" in x.lower() for x in labels2)


def test_suggested_actions_from_counts(client, db):
    agent = _seed_agent(db)
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    failed = _create_run(db, agent)
    db.query(Run).filter(Run.id == failed.id).update(
        {"status": "failed", "created_at": day_start + timedelta(hours=1)}
    )
    db.add(
        Proposal(
            id=_new_id(),
            space_id=SPACE,
            proposal_type="memory_update",
            status="pending",
            title="P",
            payload_json={},
            created_by_user_id=USER,
        )
    )
    TaskService(db).create(TaskCreate(title="NR", status="needs_review"), SPACE, USER)
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    actions = res.json()["suggested_actions"]
    ids = {a["id"] for a in actions}
    assert "review-pending-proposals" in ids
    assert "inspect-failed-runs" in ids
    assert "review-tasks-needs-review" in ids


def test_get_summary_is_read_only(client, db):
    from app.models import Task

    before = db.query(Task).count()
    r = client.get(f"/api/v1/home/summary?{AUTH}")
    assert r.status_code == 200
    after = db.query(Task).count()
    assert before == after


def test_activity_summary_counts(client, db):
    now = datetime.now(UTC)
    db.add(
        ActivityRecord(
            id=_new_id(),
            space_id=SPACE,
            activity_type="t",
            title="raw1",
            status="raw",
            created_at=now - timedelta(days=1),
            occurred_at=now - timedelta(days=1),
        )
    )
    db.add(
        ActivityRecord(
            id=_new_id(),
            space_id=SPACE,
            activity_type="t2",
            title="today",
            status="processed",
            created_at=now,
            occurred_at=now,
        )
    )
    db.commit()
    res = client.get(f"/api/v1/home/summary?{AUTH}")
    act = res.json()["activity_summary"]
    assert act["raw_count"] >= 1
    assert act["today_count"] >= 1
    assert act["recent_count"] >= 1


def test_home_module_has_no_context_builder_or_execution():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "home"
    for name in ("summary_service.py", "api.py"):
        text = (root / name).read_text()
        assert "context_builder" not in text
        assert "ContextBuilder" not in text
        _forbidden_runtime = bytes.fromhex("46616b6552756e74696d65").decode("ascii")
        assert _forbidden_runtime not in text
        assert "RunExecutionService" not in text
        assert "MemoryEntry" not in text
