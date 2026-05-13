"""Task board foundation (product Task ORM, boards, Run linkage)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.canonical

from app.agents.agent_service import AgentService
from app.models import (
    Agent,
    AgentVersion,
    Artifact,
    BoardColumn,
    Credential,
    Job,
    ModelProvider,
    Proposal,
    Run,
    RuntimeAdapter,
    TaskRun,
    ContextSnapshot,
)
from app.schemas import AgentCreate, TaskCreate
from app.tasks.service import TaskService
from tests.conftest import ensure_space, ensure_workspace

SPACE = "personal"
USER = "default_user"


@pytest.fixture
def seeded_agent(db):
    svc = AgentService(db)
    return svc.create(
        AgentCreate(name="Task board agent", description="test"),
        requesting_user_id=USER,
    )


def test_board_crud_space_scoped(client, db):
    r = client.post("/api/v1/boards", json={"name": "Main", "board_type": "workspace"})
    assert r.status_code == 201
    board_id = r.json()["id"]
    assert r.json()["space_id"] == SPACE

    lst = client.get("/api/v1/boards")
    assert lst.status_code == 200
    assert any(b["id"] == board_id for b in lst.json()["items"])

    one = client.get(f"/api/v1/boards/{board_id}")
    assert one.status_code == 200
    assert one.json()["name"] == "Main"

    patch = client.patch(f"/api/v1/boards/{board_id}", json={"name": "Renamed"})
    assert patch.status_code == 200
    assert patch.json()["name"] == "Renamed"


def test_board_create_default_columns(client, db):
    r = client.post("/api/v1/boards", json={"name": "With cols", "create_default_columns": True})
    assert r.status_code == 201
    board_id = r.json()["id"]
    keys = {c.status_key for c in db.query(BoardColumn).filter(BoardColumn.board_id == board_id).all()}
    assert keys == {"inbox", "ready", "in_progress", "needs_review", "done", "blocked", "cancelled"}


def test_task_crud_and_board_column(client, db):
    br = client.post("/api/v1/boards", json={"name": "B1"})
    board_id = br.json()["id"]
    inbox = (
        db.query(BoardColumn)
        .filter(BoardColumn.board_id == board_id, BoardColumn.status_key == "inbox")
        .one()
    )
    tr = client.post(
        "/api/v1/tasks",
        json={
            "title": "T1",
            "board_id": board_id,
            "column_id": inbox.id,
        },
    )
    assert tr.status_code == 201
    task_id = tr.json()["id"]
    assert tr.json()["board_id"] == board_id
    assert tr.json()["column_id"] == inbox.id

    lst = client.get("/api/v1/tasks")
    assert lst.status_code == 200
    assert any(t["id"] == task_id for t in lst.json()["items"])

    g = client.get(f"/api/v1/tasks/{task_id}")
    assert g.status_code == 200

    p = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "ready"})
    assert p.status_code == 200
    assert p.json()["status"] == "ready"


def test_cross_space_board_rejected(client, db):
    ensure_space(db, "space-2", "Other")
    r = client.post("/api/v1/boards?space_id=space-2", json={"name": "Other board"})
    assert r.status_code == 201
    other_board_id = r.json()["id"]

    t = client.post("/api/v1/tasks", json={"title": "Bad", "board_id": other_board_id})
    assert t.status_code == 400

    g = client.get(f"/api/v1/boards/{other_board_id}")
    assert g.status_code == 404


def test_task_not_job_and_post_runs_no_job(client, db, seeded_agent):
    jobs_before = db.query(Job).count()
    tr = client.post(
        "/api/v1/tasks",
        json={"title": "Product task", "assigned_agent_id": seeded_agent.id},
    )
    assert tr.status_code == 201
    task_id = tr.json()["id"]
    assert db.query(Job).filter(Job.id == task_id).first() is None
    assert db.query(Job).count() == jobs_before

    arts_before = db.query(Artifact).count()
    props_before = db.query(Proposal).count()
    runs_before = db.query(Run).count()
    tr_before = db.query(TaskRun).count()

    rr = client.post(f"/api/v1/tasks/{task_id}/runs", json={})
    assert rr.status_code == 201
    run_json = rr.json()
    assert run_json["status"] == "queued"
    assert db.query(Job).count() == jobs_before
    assert db.query(Artifact).count() == arts_before
    assert db.query(Proposal).count() == props_before
    assert db.query(Run).count() == runs_before + 1
    assert db.query(TaskRun).count() == tr_before + 1

    link = db.query(TaskRun).filter(TaskRun.task_id == task_id).one()
    assert link.run_id == run_json["id"]
    run = db.query(Run).filter(Run.id == run_json["id"]).one()
    assert run.status == "queued"
    assert run.started_at is None
    assert run.task_id == task_id
    assert db.query(TaskRun).filter(TaskRun.task_id == task_id, TaskRun.run_id == run.id).count() == 1


def test_list_task_runs_uses_taskrun_when_run_task_id_null(client, db, seeded_agent):
    """GET /tasks/{id}/runs must follow task_runs; Run.task_id may be null (e.g. non-primary link)."""
    t = client.post(
        "/api/v1/tasks",
        json={"title": "Retry-linked", "assigned_agent_id": seeded_agent.id},
    )
    assert t.status_code == 201
    task_id = t.json()["id"]

    from app.runs.run_service import RunService
    from app.schemas import RunCreate

    run_svc = RunService(db)
    run2 = run_svc.create_run(
        agent_id=seeded_agent.id,
        data=RunCreate(),
        space_id=SPACE,
        user_id=USER,
    )
    assert run2.task_id is None

    TaskService(db).link_task_to_run(
        space_id=SPACE,
        task_id=task_id,
        run_id=run2.id,
        role="retry",
    )
    db.refresh(run2)
    assert run2.task_id is None

    r = client.get(f"/api/v1/tasks/{task_id}/runs")
    assert r.status_code == 200
    run_ids = {item["link"]["run_id"] for item in r.json()["items"]}
    assert run2.id in run_ids
    del seeded_agent
    ensure_workspace(db, "ws-1", SPACE, name="WS")
    cred = Credential(
        id="cred-p6",
        space_id=SPACE,
        name="c",
        credential_type="api_key",
        secret_ref="ref",
    )
    mp = ModelProvider(
        id="mp-p6",
        space_id=SPACE,
        name="p",
        provider_type="test",
        credential_id=cred.id,
    )
    ad = RuntimeAdapter(
        id="ad-p6",
        space_id=SPACE,
        name="a",
        adapter_type="echo",
        provider_id=mp.id,
    )
    agent = Agent(id="ag-p6", space_id=SPACE, name="A")
    ver = AgentVersion(
        id="ver-p6",
        agent_id=agent.id,
        space_id=SPACE,
        version_label="v1",
        model_provider_id=mp.id,
        runtime_adapter_id=ad.id,
    )
    agent.current_version_id = ver.id
    snap = ContextSnapshot(id="snap-p6", space_id=SPACE, source_refs_json=[])
    run = Run(
        id="run-p6",
        space_id=SPACE,
        agent_id=agent.id,
        agent_version_id=ver.id,
        context_snapshot_id=snap.id,
        workspace_id="ws-1",
        run_type="agent",
        trigger_origin="manual",
        status="queued",
        mode="live",
    )
    art = Artifact(
        id="art-p6",
        space_id=SPACE,
        run_id=run.id,
        artifact_type="report",
        title="out.txt",
        content="x" * 5000,
    )
    prop = Proposal(
        id="prop-p6",
        space_id=SPACE,
        created_by_run_id=run.id,
        proposal_type="memory_update",
        title="prop",
        risk_level="low",
        urgency="normal",
    )
    db.add_all([cred, mp, ad, agent, ver, snap, run, art, prop])
    db.commit()

    t = client.post("/api/v1/tasks", json={"title": "Linked", "workspace_id": "ws-1"})
    task_id = t.json()["id"]
    ts = TaskService(db)
    ts.link_task_to_run(space_id=SPACE, task_id=task_id, run_id=run.id, role="primary")
    ts.link_task_to_artifact(space_id=SPACE, task_id=task_id, artifact_id=art.id, role="output")
    ts.link_task_to_proposal(space_id=SPACE, task_id=task_id, proposal_id=prop.id, role="main_change")

    runs = client.get(f"/api/v1/tasks/{task_id}/runs")
    assert runs.status_code == 200
    body = runs.json()
    assert body["total"] >= 1
    item = next(x for x in body["items"] if x["link"]["run_id"] == run.id)
    assert item["run"]["id"] == run.id

    arts = client.get(f"/api/v1/tasks/{task_id}/artifacts")
    assert arts.status_code == 200
    a0 = next(x for x in arts.json()["items"] if x["artifact_id"] == art.id)
    assert a0["artifact"]["title"] == "out.txt"
    assert "content" not in a0["artifact"]

    props = client.get(f"/api/v1/tasks/{task_id}/proposals")
    assert props.status_code == 200
    p0 = next(x for x in props.json()["items"] if x["proposal_id"] == prop.id)
    assert p0["proposal"]["title"] == "prop"


def test_task_artifact_link_wrong_space_rejected(db):
    ensure_space(db, "space-2", "S2")
    t = TaskService(db).create(
        TaskCreate(title="T"),
        SPACE,
        USER,
    )
    art = Artifact(
        id="art-ws",
        space_id="space-2",
        artifact_type="log",
        title="other",
    )
    db.add(art)
    db.commit()
    with pytest.raises(HTTPException) as ei:
        TaskService(db).link_task_to_artifact(
            space_id=SPACE,
            task_id=t.id,
            artifact_id=art.id,
        )
    assert ei.value.status_code == 400


def test_board_tasks_listing(client, db):
    br = client.post("/api/v1/boards", json={"name": "List board"})
    board_id = br.json()["id"]
    client.post("/api/v1/tasks", json={"title": "On board", "board_id": board_id})
    r = client.get(f"/api/v1/boards/{board_id}/tasks")
    assert r.status_code == 200
    assert r.json()["total"] >= 1
