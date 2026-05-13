"""
Tests for DatabaseQueueService and the built-in agent_run job handler.
"""
import pytest
import pytest_asyncio
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, UTC

from app.models import Space
from app.jobs.queue import DatabaseQueueService
from app.jobs.handlers import get_handler, list_registered

pytestmark = pytest.mark.canonical

SPACE = "personal"
USER = "default_user"


@pytest.fixture
def db_factory(db_engine):
    Session = sessionmaker(bind=db_engine)
    return Session


@pytest.fixture
def queue(db_factory):
    return DatabaseQueueService(db_factory)


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

def test_agent_run_handler_is_registered():
    assert "agent_run" in list_registered()


def test_get_handler_returns_callable():
    handler = get_handler("agent_run")
    assert callable(handler)


def test_get_handler_returns_none_for_unknown():
    assert get_handler("nonexistent_job_type") is None


# ---------------------------------------------------------------------------
# handle_agent_run contract:
#   - payload.run_id  → execute the existing queued Run.
#   - payload.task_id → create a Run for the product Task (canonical
#                       TaskRun link), then execute.
#   - payload.agent_id → create a Run, then execute.
# ---------------------------------------------------------------------------

def test_handle_agent_run_executes_existing_run_via_echo_adapter(db_engine, monkeypatch):
    """A queued Run drives through the default echo adapter to ``succeeded``."""
    from sqlalchemy.orm import sessionmaker
    from app.agents.agent_service import AgentService
    from app.jobs.handlers import handle_agent_run
    from app.models import Run
    from app.runs.run_service import RunService
    from app.schemas import AgentCreate, RunCreate

    Session = sessionmaker(bind=db_engine)
    monkeypatch.setattr("app.db.SessionLocal", Session)

    db = Session()
    try:
        agent = AgentService(db).create(
            AgentCreate(name="Job handler test agent"),
            requesting_user_id=USER,
        )
        run = RunService(db).create_run(
            agent_id=agent.id,
            data=RunCreate(),
            space_id=SPACE,
            user_id=USER,
        )
        run_id = run.id
    finally:
        db.close()

    job = type("Job", (), {
        "payload": {"run_id": run_id},
        "space_id": SPACE,
        "user_id": USER,
    })()
    result = handle_agent_run(job)
    assert result == {"run_id": run_id, "status": "succeeded"}

    db2 = Session()
    try:
        fetched = db2.query(Run).filter(Run.id == run_id).one()
        assert fetched.status == "succeeded"
        assert fetched.started_at is not None
        assert fetched.ended_at is not None
    finally:
        db2.close()


def test_handle_agent_run_raises_without_known_payload_id():
    """No run_id / task_id / agent_id → handler raises so the queue marks failed."""
    from app.jobs.handlers import handle_agent_run

    job = type("Job", (), {"payload": {}, "space_id": SPACE, "user_id": USER})()
    with pytest.raises(ValueError):
        handle_agent_run(job)


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_creates_pending_job(queue):
    job = await queue.enqueue(
        "agent_run",
        {"prompt": "hello"},
        space_id=SPACE,
        user_id=USER,
    )
    assert job.id
    assert job.status == "pending"
    assert job.job_type == "agent_run"
    assert job.space_id == SPACE
    assert job.user_id == USER
    assert job.attempts == 0


@pytest.mark.asyncio
async def test_enqueue_sets_priority(queue):
    job = await queue.enqueue(
        "agent_run", {}, space_id=SPACE, user_id=USER, priority=10
    )
    assert job.priority == 10


@pytest.mark.asyncio
async def test_enqueue_sets_max_attempts(queue):
    job = await queue.enqueue(
        "agent_run", {}, space_id=SPACE, user_id=USER, max_attempts=5
    )
    assert job.max_attempts == 5


@pytest.mark.asyncio
async def test_enqueue_future_scheduled_at(queue):
    future = datetime.now(UTC) + timedelta(hours=1)
    job = await queue.enqueue(
        "agent_run", {}, space_id=SPACE, user_id=USER, scheduled_at=future
    )
    assert job.scheduled_at is not None


# ---------------------------------------------------------------------------
# claim_next
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_next_returns_pending_job(queue):
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    job = await queue.claim_next("worker-1")
    assert job is not None
    assert job.status == "claimed"
    assert job.claimed_by == "worker-1"


@pytest.mark.asyncio
async def test_claim_next_returns_none_when_empty(queue):
    job = await queue.claim_next("worker-1")
    assert job is None


@pytest.mark.asyncio
async def test_claim_next_respects_priority(queue):
    low = await queue.enqueue("agent_run", {"p": 0}, space_id=SPACE, user_id=USER, priority=0)
    high = await queue.enqueue("agent_run", {"p": 10}, space_id=SPACE, user_id=USER, priority=10)
    claimed = await queue.claim_next("worker-1")
    assert claimed.priority == 10


@pytest.mark.asyncio
async def test_claim_next_skips_future_scheduled(queue):
    future = datetime.now(UTC) + timedelta(hours=1)
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER, scheduled_at=future)
    job = await queue.claim_next("worker-1")
    assert job is None  # not yet due


@pytest.mark.asyncio
async def test_claim_next_does_not_double_claim(queue):
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    first = await queue.claim_next("worker-1")
    second = await queue.claim_next("worker-2")
    assert first is not None
    assert second is None  # already claimed


# ---------------------------------------------------------------------------
# start_job / complete_job / fail_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_job_sets_running(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)
    fetched = await queue.get_job(job.id)
    assert fetched.status == "running"
    assert fetched.attempts == 1
    assert fetched.started_at is not None


@pytest.mark.asyncio
async def test_complete_job_sets_completed(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)
    await queue.complete_job(job.id, {"output": "done"})
    fetched = await queue.get_job(job.id)
    assert fetched.status == "completed"
    assert fetched.result == {"output": "done"}
    assert fetched.completed_at is not None


@pytest.mark.asyncio
async def test_fail_job_retries_while_attempts_remain(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER, max_attempts=3)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)  # attempts = 1
    await queue.fail_job(job.id, "transient error")
    fetched = await queue.get_job(job.id)
    assert fetched.status == "pending"  # back to pending for retry


@pytest.mark.asyncio
async def test_fail_job_final_failure_sets_failed(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER, max_attempts=1)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)  # attempts = 1 = max_attempts
    await queue.fail_job(job.id, "fatal error")
    fetched = await queue.get_job(job.id)
    assert fetched.status == "failed"
    assert fetched.error == "fatal error"


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_job(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.cancel_job(job.id)
    fetched = await queue.get_job(job.id)
    assert fetched.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_running_job_is_ignored(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)
    await queue.cancel_job(job.id)
    fetched = await queue.get_job(job.id)
    # cancel only applies to pending/claimed, not running
    assert fetched.status == "running"


# ---------------------------------------------------------------------------
# append_event / get_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_and_get_events(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.append_event(job.id, "status_change", "Job started")
    await queue.append_event(job.id, "log", "Step 1 done", data={"step": 1})
    events = await queue.get_events(job.id)
    assert len(events) == 2
    assert events[0].event_type == "status_change"
    assert events[1].data == {"step": 1}


# ---------------------------------------------------------------------------
# list_jobs / count_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_jobs_space_isolation(queue, db_factory):
    db = db_factory()
    try:
        db.add_all([Space(id="space_a", name="Space A"), Space(id="space_b", name="Space B")])
        db.commit()
    finally:
        db.close()

    await queue.enqueue("agent_run", {}, space_id="space_a", user_id=USER)
    await queue.enqueue("agent_run", {}, space_id="space_b", user_id=USER)
    jobs_a = await queue.list_jobs("space_a")
    assert len(jobs_a) == 1


@pytest.mark.asyncio
async def test_list_jobs_filter_by_status(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    pending = await queue.list_jobs(SPACE, status="pending")
    claimed = await queue.list_jobs(SPACE, status="claimed")
    assert len(pending) == 0
    assert len(claimed) == 1


@pytest.mark.asyncio
async def test_count_jobs(queue):
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    count = await queue.count_jobs(SPACE)
    assert count == 2


@pytest.mark.asyncio
async def test_count_jobs_filter_by_status(queue):
    await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    job2 = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    pending_count = await queue.count_jobs(SPACE, status="pending")
    assert pending_count == 1


# ---------------------------------------------------------------------------
# reclaim_stuck_jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reclaim_stuck_jobs(queue, db_factory):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER, max_attempts=3)
    await queue.claim_next("worker-1")
    await queue.start_job(job.id)  # attempts = 1

    # Manually age the updated_at so it looks stuck
    # Use naive UTC datetime — SQLite stores datetimes without tz info
    from sqlalchemy import text
    db = db_factory()
    try:
        old_ts = (datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=700)).isoformat(sep=" ")
        db.execute(text("UPDATE jobs SET updated_at = :ts WHERE id = :id"),
                   {"ts": old_ts, "id": job.id})
        db.commit()
    finally:
        db.close()

    reclaimed = await queue.reclaim_stuck_jobs(stuck_after_seconds=600)
    assert reclaimed == 1

    fetched = await queue.get_job(job.id)
    assert fetched.status == "pending"


@pytest.mark.asyncio
async def test_reclaim_does_not_reclaim_fresh_jobs(queue):
    job = await queue.enqueue("agent_run", {}, space_id=SPACE, user_id=USER)
    await queue.claim_next("worker-1")
    reclaimed = await queue.reclaim_stuck_jobs(stuck_after_seconds=600)
    assert reclaimed == 0
