"""PostgreSQL queue concurrency and correctness tests.

Validates that PostgresQueueService correctly uses SELECT ... FOR UPDATE SKIP LOCKED
so concurrent workers never claim the same job, and that all queue semantics
(priority, scheduled_at ordering, retry, reclaim, heartbeat, terminal-state
protection) work against a real PostgreSQL backend.

Tests use local committed-engine fixtures that clear only the durable rows this
file creates before and after each test. Queue code opens its own independent
sessions, so it needs committed cross-session state; the fixtures guarantee that
committed rows from one test never leak into another without paying the cost of
truncating the whole schema for every queue behavior case.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.jobs.queue import PostgresQueueService


# ── Helpers ────────────────────────────────────────────────────────────────────

def _space_user() -> tuple[str, str]:
    """Return (space_id, user_id) guaranteed to exist in test DB."""
    from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID
    return PERSONAL_SPACE_ID, DEFAULT_USER_ID


def _reset_queue_test_rows(db_engine) -> None:
    """Remove committed rows created by this test module.

    The global ``db_engine_isolated`` fixture truncates the whole schema. That is
    useful for generic committed-engine tests, but it dominates the runtime of
    this queue file. These tests only create queue rows, default tenant rows, and
    a small Run/Agent FK chain for agent_run reclaim cases.
    """
    space_id, user_id = _space_user()
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        db.execute(text("DELETE FROM run_execution_locks"))
        db.execute(text("DELETE FROM job_events"))
        db.execute(text("DELETE FROM jobs"))
        db.execute(text("DELETE FROM runs"))
        db.execute(text("DELETE FROM context_snapshots"))
        db.execute(text("UPDATE agents SET current_version_id = NULL"))
        db.execute(text("DELETE FROM agent_versions"))
        db.execute(text("DELETE FROM agents"))
        db.execute(
            text(
                "DELETE FROM space_memberships "
                "WHERE id = 'default_membership' OR space_id = :space_id OR user_id = :user_id"
            ),
            {"space_id": space_id, "user_id": user_id},
        )
        db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        db.execute(text("DELETE FROM spaces WHERE id = :space_id"), {"space_id": space_id})
        db.commit()


def _seed_queue_defaults(db_engine) -> None:
    space_id, user_id = _space_user()
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        db.execute(
            text(
                "INSERT INTO spaces (id, name, type, created_at, updated_at) "
                "VALUES (:space_id, 'Personal', 'personal', now(), now())"
            ),
            {"space_id": space_id},
        )
        db.execute(
            text(
                "INSERT INTO users (id, email, display_name, status, created_at, updated_at) "
                "VALUES (:user_id, 'default@example.com', 'Default User', 'active', now(), now())"
            ),
            {"user_id": user_id},
        )
        db.execute(
            text(
                "INSERT INTO space_memberships "
                "(id, space_id, user_id, role, status, created_at, updated_at) "
                "VALUES ('default_membership', :space_id, :user_id, 'owner', 'active', now(), now())"
            ),
            {"space_id": space_id, "user_id": user_id},
        )
        db.commit()


@pytest.fixture(scope="function")
def queue_db_engine(db_engine):
    _reset_queue_test_rows(db_engine)
    _seed_queue_defaults(db_engine)
    try:
        yield db_engine
    finally:
        _reset_queue_test_rows(db_engine)


@pytest.fixture(scope="function")
def queue_service(queue_db_engine):
    Session = sessionmaker(bind=queue_db_engine)
    return PostgresQueueService(Session)


def _enqueue(q, job_type="test_job", *, space_id, user_id, priority=0,
             scheduled_at=None, max_attempts=3, payload=None) -> Any:
    return asyncio.run(q.enqueue(
        job_type,
        payload or {},
        space_id=space_id,
        user_id=user_id,
        priority=priority,
        max_attempts=max_attempts,
        scheduled_at=scheduled_at,
    ))


def _backdate(db_engine, job_id: str, seconds: int) -> None:
    """Backdate updated_at and heartbeat_at to simulate a stuck job."""
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        db.execute(
            text("UPDATE jobs SET heartbeat_at = :old, updated_at = :old WHERE id = :id"),
            {"old": datetime.now(UTC) - timedelta(seconds=seconds), "id": job_id},
        )
        db.commit()


# ── Concurrency: no double-claim ───────────────────────────────────────────────

class TestConcurrentClaim:
    def test_two_workers_claim_different_jobs(self, queue_service):
        """Two concurrent workers must each claim a distinct job (no double-claim)."""
        q = queue_service
        space_id, user_id = _space_user()

        j1 = _enqueue(q, space_id=space_id, user_id=user_id)
        j2 = _enqueue(q, space_id=space_id, user_id=user_id)

        claimed_ids = []
        errors = []

        def claim_one(worker_id):
            try:
                job = asyncio.run(q.claim_next(worker_id))
                if job is not None:
                    claimed_ids.append(job.id)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=claim_one, args=("worker-1",))
        t2 = threading.Thread(target=claim_one, args=("worker-2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert len(claimed_ids) == 2, f"Expected 2 distinct claimed jobs, got {len(claimed_ids)}: {claimed_ids}"
        assert set(claimed_ids) == {j1.id, j2.id}, "Workers must claim different jobs"

    def test_one_pending_job_claimed_by_exactly_one_worker(self, queue_service):
        """With one pending job and racing workers, exactly one claims it."""
        q = queue_service
        space_id, user_id = _space_user()

        _enqueue(q, space_id=space_id, user_id=user_id)

        claimed = []
        errors = []

        def claim_one(worker_id):
            try:
                job = asyncio.run(q.claim_next(worker_id))
                claimed.append(job)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=claim_one, args=(f"w{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        non_null = [j for j in claimed if j is not None]
        assert len(non_null) == 1, f"Exactly one worker must claim the job, got {len(non_null)}"


# ── Priority and scheduled_at ordering ─────────────────────────────────────────

class TestOrdering:
    def test_high_priority_claimed_before_low(self, queue_service):
        """Jobs with higher priority are claimed before lower priority jobs."""
        q = queue_service
        space_id, user_id = _space_user()

        _enqueue(q, space_id=space_id, user_id=user_id, priority=0)
        high = _enqueue(q, space_id=space_id, user_id=user_id, priority=10)

        first = asyncio.run(q.claim_next("w1"))
        assert first is not None
        assert first.id == high.id, f"High priority job must be claimed first, got {first.id}"

    def test_earlier_scheduled_at_claimed_first_at_same_priority(self, queue_service):
        """Among equal-priority jobs, the earlier scheduled_at is claimed first."""
        q = queue_service
        space_id, user_id = _space_user()

        now = datetime.now(UTC)
        _enqueue(q, space_id=space_id, user_id=user_id, priority=0,
                 scheduled_at=now + timedelta(seconds=1))
        earlier = _enqueue(q, space_id=space_id, user_id=user_id, priority=0,
                           scheduled_at=now - timedelta(seconds=10))

        first = asyncio.run(q.claim_next("w1"))
        assert first is not None
        assert first.id == earlier.id, "Earlier scheduled_at must be claimed first"

    def test_future_scheduled_jobs_not_claimed(self, queue_service):
        """Jobs with scheduled_at in the future must not be claimed."""
        q = queue_service
        space_id, user_id = _space_user()

        future = datetime.now(UTC) + timedelta(hours=1)
        _enqueue(q, space_id=space_id, user_id=user_id, scheduled_at=future)

        claimed = asyncio.run(q.claim_next("w1"))
        assert claimed is None, "Future-scheduled job must not be claimed immediately"


# ── Retry and failure semantics ────────────────────────────────────────────────

class TestRetryAndFailure:
    def test_fail_job_below_max_retries_returns_to_pending(self, queue_service):
        """A failed job with attempts < max_attempts goes back to pending for retry."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=3)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.fail_job(job.id, "transient error"))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "pending", f"Expected pending for retry, got {refreshed.status}"

    def test_fail_job_at_max_attempts_becomes_failed(self, queue_service):
        """A job that exhausts all attempts transitions to 'failed'."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.fail_job(job.id, "permanent error"))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "failed", f"Expected failed at max attempts, got {refreshed.status}"

    def test_complete_job_transitions_to_completed(self, queue_service):
        """Completing a job sets status to 'completed'."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.complete_job(job.id, result={"done": True}))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "completed"

    def test_cancel_pending_job_transitions_to_cancelled(self, queue_service):
        """Cancelling a pending job sets status to 'cancelled'."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.cancel_job(job.id))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "cancelled"

    def test_cancel_running_job_transitions_to_cancelled(self, queue_service):
        """Cancelling a running job is allowed and sets status to 'cancelled'."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.cancel_job(job.id))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "cancelled"


# ── Terminal-state protection ──────────────────────────────────────────────────

class TestTerminalStateProtection:
    def test_completed_job_cannot_be_failed(self, queue_service):
        """A completed job stays completed even if fail_job is called."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.complete_job(job.id))

        asyncio.run(q.fail_job(job.id, "late failure"))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.status == "completed", "completed job must not be reopened by fail_job"

    def test_failed_job_cannot_be_completed(self, queue_service):
        """A failed job stays failed even if complete_job is called."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.fail_job(job.id, "permanent"))

        asyncio.run(q.complete_job(job.id, result={"done": True}))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.status == "failed", "failed job must not be completed"

    def test_cancelled_job_cannot_be_completed_or_failed(self, queue_service):
        """A cancelled job stays cancelled against both complete_job and fail_job."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.cancel_job(job.id))

        asyncio.run(q.complete_job(job.id, result={"done": True}))
        assert asyncio.run(q.get_job(job.id)).status == "cancelled"

        asyncio.run(q.fail_job(job.id, "noop"))
        assert asyncio.run(q.get_job(job.id)).status == "cancelled"


# ── Worker ownership ────────────────────────────────────────────────────────────

class TestWorkerOwnership:
    """Only the worker that claimed a job may start/heartbeat/complete/fail it."""

    def test_non_owner_cannot_start_claimed_job(self, queue_service):
        q = queue_service
        space_id, user_id = _space_user()
        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("owner"))

        # A different worker cannot start the owner's claimed job.
        asyncio.run(q.start_job(job.id, "intruder"))
        assert asyncio.run(q.get_job(job.id)).status == "claimed"

        # The claiming worker can.
        asyncio.run(q.start_job(job.id, "owner"))
        assert asyncio.run(q.get_job(job.id)).status == "running"

    def test_non_owner_cannot_complete_claimed_job(self, queue_service):
        q = queue_service
        space_id, user_id = _space_user()
        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("owner"))
        asyncio.run(q.start_job(job.id, "owner"))

        # Non-owner complete is a no-op.
        asyncio.run(q.complete_job(job.id, result={"x": 1}, worker_id="intruder"))
        assert asyncio.run(q.get_job(job.id)).status == "running"

        # Owner can complete.
        asyncio.run(q.complete_job(job.id, result={"x": 1}, worker_id="owner"))
        assert asyncio.run(q.get_job(job.id)).status == "completed"

    def test_non_owner_cannot_fail_claimed_job(self, queue_service):
        q = queue_service
        space_id, user_id = _space_user()
        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("owner"))
        asyncio.run(q.start_job(job.id, "owner"))

        # Non-owner fail is a no-op.
        asyncio.run(q.fail_job(job.id, "intruder error", worker_id="intruder"))
        assert asyncio.run(q.get_job(job.id)).status == "running"

        # Owner can fail; with attempts remaining the job returns to pending.
        asyncio.run(q.fail_job(job.id, "owner error", worker_id="owner"))
        assert asyncio.run(q.get_job(job.id)).status == "pending"

    def test_non_owner_cannot_heartbeat_claimed_job(self, queue_service, db_engine):
        q = queue_service
        space_id, user_id = _space_user()
        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("owner"))
        asyncio.run(q.start_job(job.id, "owner"))

        # Backdate so a successful heartbeat would visibly advance the timestamp.
        _backdate(db_engine, job.id, 300)
        stale = asyncio.run(q.get_job(job.id)).heartbeat_at

        # Non-owner heartbeat is a no-op: the stale timestamp is unchanged.
        asyncio.run(q.touch_heartbeat(job.id, "intruder"))
        assert asyncio.run(q.get_job(job.id)).heartbeat_at == stale

        # Owner heartbeat advances it.
        asyncio.run(q.touch_heartbeat(job.id, "owner"))
        assert asyncio.run(q.get_job(job.id)).heartbeat_at > stale

    def test_terminal_job_stays_terminal_even_for_owner(self, queue_service):
        q = queue_service
        space_id, user_id = _space_user()
        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("owner"))
        asyncio.run(q.start_job(job.id, "owner"))
        asyncio.run(q.complete_job(job.id, worker_id="owner"))

        # Even the owner cannot reopen a terminal job.
        asyncio.run(q.fail_job(job.id, "late", worker_id="owner"))
        assert asyncio.run(q.get_job(job.id)).status == "completed"


# ── Heartbeat and stuck-job reclaim ───────────────────────────────────────────

class TestHeartbeatAndReclaim:
    def test_reclaim_stuck_job_resets_to_pending(self, queue_service, db_engine):
        """A stuck running job (no heartbeat) is reset to pending by reclaim."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=3)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "pending", f"Stuck job must return to pending, got {refreshed.status}"
        assert refreshed.claimed_by is None
        assert refreshed.claimed_at is None
        assert refreshed.started_at is None
        assert refreshed.heartbeat_at is None

    def test_reclaim_stuck_claimed_job_with_attempts_remaining_resets_to_pending(self, queue_service, db_engine):
        """A stuck claimed job with attempts remaining returns to pending."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=3)
        asyncio.run(q.claim_next("w1"))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "pending"
        assert refreshed.claimed_by is None
        assert refreshed.claimed_at is None
        assert refreshed.started_at is None
        assert refreshed.heartbeat_at is None

    def test_reclaim_stuck_claimed_job_at_attempt_limit_fails(self, queue_service, db_engine):
        """A stuck claimed job at its attempt ceiling becomes terminal failed."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.claimed_by is None
        assert refreshed.claimed_at is None
        assert refreshed.heartbeat_at is None
        assert refreshed.completed_at is not None
        assert refreshed.error == "job stuck and retry attempts exhausted"

    def test_reclaim_stuck_running_job_at_attempt_limit_fails(self, queue_service, db_engine):
        """A stuck running job at its attempt ceiling becomes terminal failed."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.claimed_by is None
        assert refreshed.claimed_at is None
        assert refreshed.heartbeat_at is None
        assert refreshed.completed_at is not None
        assert refreshed.error == "job stuck and retry attempts exhausted"

    def test_lock_cleanup_failure_writes_warning_event_and_reclaim_continues(
        self, queue_service, db_engine, monkeypatch
    ):
        """Best-effort orphan run lock cleanup failures must be observable."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = "00000000-0000-4000-8000-000000000001"

        job = _enqueue(
            q,
            job_type="agent_run",
            space_id=space_id,
            user_id=user_id,
            max_attempts=3,
            payload={"run_id": run_id, "space_id": space_id, "user_id": user_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        def fail_cleanup(self, db, job_id, run_id):
            raise RuntimeError("forced raw traceback marker")

        monkeypatch.setattr(
            PostgresQueueService,
            "_delete_orphan_run_execution_lock",
            fail_cleanup,
        )

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "pending"

        warnings = [
            event
            for event in asyncio.run(q.get_events(job.id))
            if event.event_type == "warning"
        ]
        assert len(warnings) == 1
        event = warnings[0]
        assert event.message == "orphan run execution lock cleanup failed during stuck-job reclaim"
        assert event.data == {
            "operation": "reclaim_stuck_jobs",
            "diagnostic": "orphan_run_execution_lock_cleanup_failed",
        }
        stored_text = f"{event.message} {event.data}"
        assert "Traceback" not in stored_text
        assert "forced raw traceback marker" not in stored_text

    def test_heartbeating_job_not_reclaimed(self, queue_service):
        """A running job with a recent heartbeat must not be reclaimed."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=3)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.touch_heartbeat(job.id))

        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "running", "Heartbeating job must not be reclaimed"

    def test_completed_job_not_reclaimed(self, queue_service):
        """A completed job must not be reclaimed even if its updated_at is old."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.complete_job(job.id))

        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=0))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed is not None
        assert refreshed.status == "completed", "Completed job must never be reclaimed"

    def test_failed_job_not_reclaimed(self, queue_service):
        """A failed terminal job must never be reset by reclaim."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.fail_job(job.id, "permanent"))

        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=0))

        assert asyncio.run(q.get_job(job.id)).status == "failed"

    def test_cancelled_job_not_reclaimed(self, queue_service):
        """A cancelled terminal job must never be reset by reclaim."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.cancel_job(job.id))

        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=0))

        assert asyncio.run(q.get_job(job.id)).status == "cancelled"

    def test_terminal_jobs_are_not_modified_by_reclaim(self, queue_service, db_engine):
        """Completed, failed, and cancelled jobs are left untouched by reclaim."""
        q = queue_service
        space_id, user_id = _space_user()

        completed = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(completed.id))
        asyncio.run(q.complete_job(completed.id))

        failed = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(failed.id))
        asyncio.run(q.fail_job(failed.id, "permanent"))

        cancelled = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.cancel_job(cancelled.id))

        ids = [completed.id, failed.id, cancelled.id]
        for job_id in ids:
            _backdate(db_engine, job_id, seconds=700)

        before = {job_id: asyncio.run(q.get_job(job_id)).updated_at for job_id in ids}

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed == 0

        assert asyncio.run(q.get_job(completed.id)).status == "completed"
        assert asyncio.run(q.get_job(failed.id)).status == "failed"
        assert asyncio.run(q.get_job(cancelled.id)).status == "cancelled"
        after = {job_id: asyncio.run(q.get_job(job_id)).updated_at for job_id in ids}
        assert after == before

    def test_heartbeat_does_not_update_terminal_jobs(self, queue_service, db_engine):
        """touch_heartbeat must not set heartbeat_at on completed/failed/cancelled jobs."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.complete_job(job.id))  # clears heartbeat_at to NULL, terminal

        asyncio.run(q.touch_heartbeat(job.id))

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            hb = db.execute(
                text("SELECT heartbeat_at FROM jobs WHERE id = :id"), {"id": job.id}
            ).scalar()
        assert hb is None, "heartbeat must not be written to a terminal job"


# ── agent_run reclaim: orphan locks + linked Run recovery ──────────────────────

def _create_running_run(db_engine, *, status: str = "running") -> str:
    """Create a real Run row (full FK chain) in the given non-terminal status.

    Returns the run_id. Committed so independent queue sessions can see it.
    """
    from tests.support.factories import create_test_run
    from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        run = create_test_run(
            db, space_id=PERSONAL_SPACE_ID, user_id=DEFAULT_USER_ID, commit=False
        )
        run.status = status
        db.add(run)
        db.commit()
        return run.id


def _insert_run_lock(db_engine, *, run_id: str, job_id: str, worker_id: str = "w1") -> None:
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        db.execute(
            text(
                "INSERT INTO run_execution_locks (run_id, locked_at, worker_id, job_id) "
                "VALUES (:run_id, :locked_at, :worker_id, :job_id)"
            ),
            {
                "run_id": run_id,
                "locked_at": datetime.now(UTC),
                "worker_id": worker_id,
                "job_id": job_id,
            },
        )
        db.commit()


def _lock_exists(db_engine, run_id: str) -> bool:
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        found = db.execute(
            text("SELECT 1 FROM run_execution_locks WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).scalar()
    return found is not None


def _run_status(db_engine, run_id: str) -> str:
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        return db.execute(
            text("SELECT status FROM runs WHERE id = :id"), {"id": run_id}
        ).scalar()


class TestAgentRunReclaim:
    """Reclaim semantics specific to agent_run jobs and their linked Runs/locks."""

    def test_stuck_agent_run_with_attempts_remaining_returns_to_pending(
        self, queue_service, db_engine
    ):
        """A stuck agent_run job with retries left returns to pending."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = _create_running_run(db_engine)

        job = _enqueue(
            q, job_type="agent_run", space_id=space_id, user_id=user_id,
            max_attempts=3, payload={"run_id": run_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.status == "pending"
        # Retryable: the linked Run is intentionally left non-terminal so the retry
        # can proceed.
        assert _run_status(db_engine, run_id) == "running"

    def test_exhausted_stuck_agent_run_fails_and_recovers_linked_run(
        self, queue_service, db_engine
    ):
        """An exhausted stuck agent_run job becomes failed and its linked
        non-terminal Run is moved to a terminal failed state."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = _create_running_run(db_engine)

        job = _enqueue(
            q, job_type="agent_run", space_id=space_id, user_id=user_id,
            max_attempts=1, payload={"run_id": run_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.status == "failed"
        assert _run_status(db_engine, run_id) == "failed", (
            "linked non-terminal Run must be moved to a terminal state on exhaustion"
        )

    def test_reclaim_does_not_reopen_already_terminal_linked_run(
        self, queue_service, db_engine
    ):
        """A linked Run already in a terminal state is never modified by reclaim."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = _create_running_run(db_engine, status="cancelled")

        job = _enqueue(
            q, job_type="agent_run", space_id=space_id, user_id=user_id,
            max_attempts=1, payload={"run_id": run_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _backdate(db_engine, job.id, seconds=700)

        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert _run_status(db_engine, run_id) == "cancelled", (
            "a terminal Run must not be reopened/overwritten by reclaim"
        )

    def test_orphan_run_execution_lock_is_deleted_on_reclaim(
        self, queue_service, db_engine
    ):
        """Reclaiming a stuck agent_run job deletes its orphan run_execution_lock."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = _create_running_run(db_engine)

        job = _enqueue(
            q, job_type="agent_run", space_id=space_id, user_id=user_id,
            max_attempts=3, payload={"run_id": run_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        _insert_run_lock(db_engine, run_id=run_id, job_id=job.id)
        assert _lock_exists(db_engine, run_id), "precondition: lock row present"
        _backdate(db_engine, job.id, seconds=700)

        reclaimed = asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))
        assert reclaimed >= 1
        assert not _lock_exists(db_engine, run_id), (
            "orphan run_execution_lock must be deleted when its stuck agent_run job is reclaimed"
        )

    def test_cancelled_agent_run_job_not_reopened_by_late_worker(
        self, queue_service, db_engine
    ):
        """A cancelled agent_run job stays cancelled even if a late worker tries to
        complete or fail it (terminal-state protection across the run lifecycle)."""
        q = queue_service
        space_id, user_id = _space_user()
        run_id = _create_running_run(db_engine)

        job = _enqueue(
            q, job_type="agent_run", space_id=space_id, user_id=user_id,
            max_attempts=3, payload={"run_id": run_id},
        )
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.cancel_job(job.id))
        assert asyncio.run(q.get_job(job.id)).status == "cancelled"

        # Late worker callbacks must not reopen the terminal job.
        asyncio.run(q.complete_job(job.id, result={"done": True}))
        assert asyncio.run(q.get_job(job.id)).status == "cancelled"
        asyncio.run(q.fail_job(job.id, "late failure"))
        assert asyncio.run(q.get_job(job.id)).status == "cancelled"


# ── Event appending ────────────────────────────────────────────────────────────

class TestEvents:
    def test_append_and_retrieve_events(self, queue_service):
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.append_event(job.id, "info", "started", {"step": 1}))
        asyncio.run(q.append_event(job.id, "info", "completed", {"step": 2}))

        events = asyncio.run(q.get_events(job.id))
        assert len(events) == 2
        assert events[0].message == "started"
        assert events[1].message == "completed"


# ── Attempt counter semantics ─────────────────────────────────────────────────

class TestAttemptSemantics:
    def test_attempts_incremented_at_claim_not_start(self, queue_service):
        """Attempt counter is incremented during claim_next, not during start_job."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        assert job.attempts == 0

        claimed = asyncio.run(q.claim_next("w1"))
        assert claimed is not None
        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.attempts == 1, "attempt must be incremented at claim time"

        asyncio.run(q.start_job(job.id))
        after_start = asyncio.run(q.get_job(job.id))
        assert after_start.attempts == 1, "start_job must not increment attempts again"

    def test_crash_after_claim_consumes_attempt(self, queue_service, db_engine):
        """A worker that claims then crashes before start still consumes its attempt.

        attempts is incremented at claim time, so a single-attempt job that was
        claimed and then abandoned is at its attempt ceiling and must fail
        terminally rather than be retried.
        """
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))  # attempts -> 1, never started (crash)
        assert asyncio.run(q.get_job(job.id)).attempts == 1

        _backdate(db_engine, job.id, seconds=700)
        asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=600))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.attempts == 1, "claim must have consumed the only attempt"
        assert refreshed.status == "failed", (
            "a job at its attempt ceiling must become terminal failed during reclaim"
        )
        assert refreshed.error == "job stuck and retry attempts exhausted"

    def test_repeated_start_job_does_not_change_attempts(self, queue_service):
        """Calling start_job repeatedly on a running job is a stable no-op."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.start_job(job.id))

        refreshed = asyncio.run(q.get_job(job.id))
        assert refreshed.status == "running"
        assert refreshed.attempts == 1, "repeated start_job must not inflate attempts"

    def test_failed_job_retry_count_correct(self, queue_service):
        """Each claim-fail cycle increments attempts exactly once."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=3)

        for _ in range(3):
            claimed = asyncio.run(q.claim_next("w1"))
            assert claimed is not None
            asyncio.run(q.start_job(claimed.id))
            asyncio.run(q.fail_job(claimed.id, "error"))

        final = asyncio.run(q.get_job(job.id))
        assert final.attempts == 3, f"Expected 3 attempts, got {final.attempts}"
        assert final.status == "failed", f"Expected failed after exhausting retries, got {final.status}"

    def test_start_job_ignored_for_completed_job(self, queue_service):
        """start_job on a completed job must not change its status or inflate attempts."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.complete_job(job.id, result={"done": True}))

        before = asyncio.run(q.get_job(job.id))
        assert before.status == "completed"
        assert before.attempts == 1

        asyncio.run(q.start_job(job.id))

        after = asyncio.run(q.get_job(job.id))
        assert after.status == "completed", "start_job must not reopen a completed job"
        assert after.attempts == 1, "start_job must not inflate attempts on completed job"

    def test_start_job_ignored_for_failed_job(self, queue_service):
        """start_job on a failed job must not change its status."""
        q = queue_service
        space_id, user_id = _space_user()

        job = _enqueue(q, space_id=space_id, user_id=user_id, max_attempts=1)
        asyncio.run(q.claim_next("w1"))
        asyncio.run(q.start_job(job.id))
        asyncio.run(q.fail_job(job.id, "permanent"))

        before = asyncio.run(q.get_job(job.id))
        assert before.status == "failed"

        asyncio.run(q.start_job(job.id))

        after = asyncio.run(q.get_job(job.id))
        assert after.status == "failed", "start_job must not reopen a failed job"
        assert after.attempts == 1, "start_job must not inflate attempts on failed job"

    def test_no_other_jobs_visible_within_test(self, queue_service):
        """Within a single test, only this test's jobs are present."""
        q = queue_service
        space_id, user_id = _space_user()

        _enqueue(q, job_type="orphan_job", space_id=space_id, user_id=user_id)

        claimed = asyncio.run(q.claim_next("w1"))
        assert claimed is not None
        assert claimed.job_type == "orphan_job"

        second = asyncio.run(q.claim_next("w2"))
        assert second is None, "No other jobs should be visible within this test"


# ── Cross-fixture isolation ────────────────────────────────────────────────────

class TestCrossFixtureIsolation:
    """Prove committed rows do not leak across separate tests / fixtures.

    ``test_a`` commits a job and intentionally does no cleanup; ``test_b`` then
    asserts the queue starts empty. If committed-engine cleanup were broken, the
    committed job from ``test_a`` would survive into ``test_b`` and fail it.
    Method names enforce execution order within the class.
    """

    def test_a_producer_leaves_committed_job(self, queue_service):
        space_id, user_id = _space_user()
        _enqueue(queue_service, job_type="leak_probe", space_id=space_id, user_id=user_id)
        # No explicit cleanup: queue_service cleanup runs on teardown.

    def test_b_consumer_sees_clean_slate(self, queue_service):
        space_id, user_id = _space_user()
        count = asyncio.run(queue_service.count_jobs(space_id))
        assert count == 0, "queue must start empty — committed jobs must not leak across tests"
        claimed = asyncio.run(queue_service.claim_next("probe-worker"))
        assert claimed is None, "no job from a prior test may be claimable"


# ── Durable schema constraints (DB-level) ─────────────────────────────────────

class TestSchemaConstraints:
    """The jobs table enforces durable-queue invariants at the DB layer.

    These use the committed engine and insert rows with raw SQL so they exercise
    the actual CHECK / NOT NULL constraints rather than ORM-side validation.
    """

    def _insert(self, db_engine, **overrides):
        """INSERT a jobs row with sensible defaults; overrides win. Commits."""
        space_id, user_id = _space_user()
        row = {
            "id": overrides.pop("id", None) or "job-constraint-" + str(threading.get_ident()),
            "space_id": space_id,
            "job_type": "test_job",
            "status": "pending",
            "priority": 0,
            "payload_json": "{}",
            "attempts": 0,
            "max_attempts": 3,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        row.update(overrides)
        cols = ", ".join(row.keys())
        params = ", ".join(f":{k}" for k in row.keys())
        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            db.execute(text(f"INSERT INTO jobs ({cols}) VALUES ({params})"), row)
            db.commit()

    def test_enqueued_job_always_has_scheduled_at(self, queue_service):
        """enqueue() never leaves scheduled_at NULL, even when not provided."""
        space_id, user_id = _space_user()
        job = _enqueue(queue_service, space_id=space_id, user_id=user_id)
        assert job.scheduled_at is not None
        refreshed = asyncio.run(queue_service.get_job(job.id))
        assert refreshed.scheduled_at is not None

    def test_scheduled_at_server_default_fills_omitted_value(self, queue_db_engine):
        """A direct insert omitting scheduled_at falls back to the server default."""
        self._insert(queue_db_engine, id="job-sched-default")
        Session = sessionmaker(bind=queue_db_engine)
        with Session() as db:
            sched = db.execute(
                text("SELECT scheduled_at FROM jobs WHERE id = 'job-sched-default'")
            ).scalar()
        assert sched is not None, "scheduled_at must be populated by the server default"

    def test_explicit_null_scheduled_at_is_rejected(self, queue_db_engine):
        """scheduled_at is NOT NULL — an explicit NULL must fail."""
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            self._insert(queue_db_engine, id="job-null-sched", scheduled_at=None)

    def test_invalid_status_is_rejected(self, queue_db_engine):
        """ck_jobs_status rejects a status outside the allowed set."""
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            self._insert(queue_db_engine, id="job-bad-status", status="bogus")

    def test_negative_attempts_is_rejected(self, queue_db_engine):
        """ck_jobs_attempts_nonneg rejects attempts < 0."""
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            self._insert(queue_db_engine, id="job-neg-attempts", attempts=-1)

    def test_nonpositive_max_attempts_is_rejected(self, queue_db_engine):
        """ck_jobs_max_attempts_positive rejects max_attempts <= 0."""
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            self._insert(queue_db_engine, id="job-zero-max", max_attempts=0)


# ── claim_next error propagation ───────────────────────────────────────────────

class TestClaimNextErrorPropagation:
    def test_claim_next_re_raises_database_errors(self):
        """claim_next must propagate DB errors, not swallow them as 'no jobs available'.

        A database failure during claim (e.g. connection loss, bad SQL) must raise,
        not silently return None. Returning None would make the worker believe the
        queue is empty and continue sleeping, hiding the real failure.
        """
        from sqlalchemy.exc import OperationalError

        def broken_factory():
            raise OperationalError("forced DB failure", None, None)

        q = PostgresQueueService(broken_factory)
        with pytest.raises(Exception):
            asyncio.run(q.claim_next("w-error-test"))

    def test_reclaim_re_raises_database_errors(self):
        """reclaim_stuck_jobs must propagate DB errors, not report 0 reclaimed."""
        from sqlalchemy.exc import OperationalError

        def broken_factory():
            raise OperationalError("forced DB failure", None, None)

        q = PostgresQueueService(broken_factory)
        with pytest.raises(Exception):
            asyncio.run(q.reclaim_stuck_jobs(stuck_after_seconds=0))


# ── Claim strategy regression guard ────────────────────────────────────────────

class TestClaimStrategy:
    def test_claim_query_uses_for_update_skip_locked(self):
        """The PostgreSQL claim must keep using FOR UPDATE SKIP LOCKED semantics.

        This is the core of safe concurrent claim; a regression to a non-locking
        SELECT would silently allow double-claims, so guard it statically.
        """
        import inspect as _inspect
        from app.jobs import queue as queue_mod

        src = _inspect.getsource(queue_mod.PostgresQueueService._claim_next_sync)
        normalized = " ".join(src.split()).upper()
        assert "FOR UPDATE SKIP LOCKED" in normalized
        # Claim must target pending rows whose schedule is due.
        assert "STATUS" in normalized and "PENDING" in normalized
        assert "SCHEDULED_AT" in normalized
