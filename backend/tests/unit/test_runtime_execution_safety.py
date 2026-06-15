"""Runtime execution safety invariants.

Covers:

- A long-running job with an active heartbeat is NOT reclaimed as stuck.
- A job without a heartbeat past the stale threshold IS reclaimable.
- The same run_id cannot be executed concurrently by two workers
  (duplicate_execution error code).
- Non-UTF-8 file changes in the worktree are surfaced as skipped (not_utf8),
  not silently ignored.
"""

from __future__ import annotations
import uuid

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.support import factories


# ===========================================================================
# Helpers
# ===========================================================================


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "hi") -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.invalid"],
        check=True, capture_output=True, cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        check=True, capture_output=True, cwd=str(path),
    )
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True, capture_output=True, cwd=str(path),
    )


def _patch_success_adapter_without_artifact(monkeypatch) -> None:
    """Execute successfully without entering unrelated runtime artifact persistence."""
    from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _adapter_type: ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text="")),
    )


# ===========================================================================
# Heartbeat prevents stale job reclaim
# ===========================================================================


def _make_queue_svc(db):
    """Build a PostgresQueueService backed by the test session's engine."""
    from app.jobs.queue import PostgresQueueService
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db.bind)
    return PostgresQueueService(db_factory=Session)


def _dt(dt: datetime) -> str:
    """Serialize datetime for PostgreSQL text() parameters (ISO format)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(sep=" ")


class TestHeartbeatPreventsReclaim:
    """PostgresQueueService.reclaim_stuck_jobs uses COALESCE(heartbeat_at, updated_at).
    A job with a fresh heartbeat_at must never be reclaimed even when updated_at is stale."""

    def test_job_with_fresh_heartbeat_is_not_reclaimed(self, db):
        """A running job whose heartbeat_at is recent must survive reclaim sweeps."""
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-fresh"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-test",
        )
        db.add(job)
        db.flush()

        # Force updated_at to be stale (1 hour ago) but heartbeat_at to be fresh (10s ago).
        stale_ts = datetime.now(UTC) - timedelta(hours=1)
        fresh_hb = datetime.now(UTC) - timedelta(seconds=10)

        db.execute(text("""
            UPDATE jobs SET updated_at = :stale, heartbeat_at = :fresh
            WHERE id = :id
        """), {"stale": _dt(stale_ts), "fresh": _dt(fresh_hb), "id": job.id})
        db.commit()

        # Call _reclaim_stuck_sync directly using the test engine
        svc = _make_queue_svc(db)
        n = svc._reclaim_stuck_sync(600)

        # Our job must NOT have been reclaimed.
        assert n == 0, f"Expected 0 reclaimed but got {n}"
        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.status == "running", "Fresh-heartbeat job was incorrectly reclaimed"

    def test_job_with_fresh_heartbeat_not_reclaimed_even_at_strict_threshold(self, db):
        """A job heartbeating every 60s is safe with a 600s threshold."""
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-strict"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-test",
        )
        db.add(job)
        db.flush()

        stale_ts = datetime.now(UTC) - timedelta(hours=2)
        # Heartbeat 59s ago — just inside the 60s interval, well within 600s threshold
        fresh_hb = datetime.now(UTC) - timedelta(seconds=59)

        db.execute(text("""
            UPDATE jobs SET updated_at = :stale, heartbeat_at = :fresh
            WHERE id = :id
        """), {"stale": _dt(stale_ts), "fresh": _dt(fresh_hb), "id": job.id})
        db.commit()

        n = _make_queue_svc(db)._reclaim_stuck_sync(600)
        assert n == 0
        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.status == "running"


# ===========================================================================
# No heartbeat: stale job is reclaimable
# ===========================================================================


class TestNoHeartbeatIsReclaimable:
    """A job with no heartbeat (heartbeat_at IS NULL) past the stale threshold must
    be reclaimed using the existing updated_at fallback via COALESCE."""

    def test_job_without_heartbeat_past_threshold_is_reclaimed(self, db):
        """heartbeat_at IS NULL + updated_at stale → reclaimed."""
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-null"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-test",
        )
        db.add(job)
        db.flush()

        # updated_at stale, heartbeat_at NULL — old-style stuck job
        stale_ts = datetime.now(UTC) - timedelta(hours=2)
        db.execute(text("""
            UPDATE jobs SET updated_at = :stale, heartbeat_at = NULL
            WHERE id = :id
        """), {"stale": _dt(stale_ts), "id": job.id})
        db.commit()

        n = _make_queue_svc(db)._reclaim_stuck_sync(600)

        assert n >= 1, "Expected stale job (no heartbeat) to be reclaimed"
        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.status == "pending", f"Expected pending after reclaim, got {reloaded.status}"

    def test_job_with_stale_heartbeat_is_reclaimed(self, db):
        """heartbeat_at older than the threshold → reclaimed (process crashed without cleanup)."""
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-stale"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-test",
        )
        db.add(job)
        db.flush()

        # Both updated_at and heartbeat_at are stale
        stale_ts = datetime.now(UTC) - timedelta(hours=2)
        stale_hb = datetime.now(UTC) - timedelta(hours=2)
        db.execute(text("""
            UPDATE jobs SET updated_at = :stale, heartbeat_at = :hb
            WHERE id = :id
        """), {"stale": _dt(stale_ts), "hb": _dt(stale_hb), "id": job.id})
        db.commit()

        n = _make_queue_svc(db)._reclaim_stuck_sync(600)

        assert n >= 1
        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.status == "pending"

    def test_touch_heartbeat_updates_heartbeat_at(self, db):
        """touch_heartbeat() updates heartbeat_at to now."""
        from app.models import Job

        space_id = "test-hb-touch"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
        )
        db.add(job)
        db.commit()

        before = datetime.now(UTC)
        _make_queue_svc(db)._touch_heartbeat_sync(job.id)
        after = datetime.now(UTC)

        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.heartbeat_at is not None, "heartbeat_at was not set"
        # heartbeat_at should be between before and after
        hb = reloaded.heartbeat_at
        if hb.tzinfo is None:
            from datetime import timezone
            hb = hb.replace(tzinfo=timezone.utc)
        assert before <= hb <= after, (
            f"heartbeat_at {hb} not in [{before}, {after}]"
        )


# ===========================================================================
# Execution lock prevents duplicate run execution
# ===========================================================================


class TestExecutionLock:
    """RunExecutionLockService prevents duplicate concurrent execution."""

    def test_first_acquire_succeeds(self, db):
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-acquire"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        svc = RunExecutionLockService(db)
        acquired = svc.try_acquire(run.id, worker_id="worker-A")
        assert acquired is True

        # Clean up
        svc.release(run.id)
        db.commit()

    def test_acquire_does_not_commit_pending_run_mutation(self, db):
        from sqlalchemy.orm import sessionmaker

        from app.models import Run
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-no-business-commit"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        run.status = "failed"  # pending in the caller session; do not flush
        svc = RunExecutionLockService(db)
        assert svc.try_acquire(run.id, worker_id="worker-no-commit") is True

        FreshSession = sessionmaker(bind=db.bind)
        fresh = FreshSession()
        try:
            persisted = fresh.query(Run).filter(Run.id == run.id).first()
            assert persisted.status == "queued"
        finally:
            fresh.close()

        db.rollback()
        svc.release(run.id)

    def test_second_acquire_same_run_id_fails(self, db):
        """A second acquire on the same run_id while the first is held must return False."""
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-dup"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        svc = RunExecutionLockService(db)
        acquired_first = svc.try_acquire(run.id, worker_id="worker-A")
        assert acquired_first is True

        db.commit()  # make the lock visible to the next attempt

        # Simulate a second worker using the same session (or a different one
        # in the same DB — the PK constraint fires either way)
        from sqlalchemy.orm import sessionmaker
        Session2 = sessionmaker(bind=db.bind)
        db2 = Session2()
        try:
            svc2 = RunExecutionLockService(db2)
            acquired_second = svc2.try_acquire(run.id, worker_id="worker-B")
            assert acquired_second is False, (
                "Second lock acquire on the same run_id should fail"
            )
        finally:
            db2.close()

        # Clean up
        svc.release(run.id)
        db.commit()

    def test_release_allows_re_acquire(self, db):
        """After release, the lock can be acquired again."""
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-reacquire"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        svc = RunExecutionLockService(db)
        svc.try_acquire(run.id, worker_id="worker-A")
        db.commit()
        svc.release(run.id)
        db.commit()

        # Should now be acquirable again
        acquired = svc.try_acquire(run.id, worker_id="worker-C")
        assert acquired is True
        svc.release(run.id)
        db.commit()

    def test_release_does_not_commit_pending_run_mutation(self, db):
        from sqlalchemy.orm import sessionmaker

        from app.models import Run, RunExecutionLock
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-release-no-business-commit"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        svc = RunExecutionLockService(db)
        assert svc.try_acquire(run.id, worker_id="worker-release-no-commit") is True

        run.status = "failed"  # pending in caller session; release must not persist it
        svc.release(run.id)
        db.rollback()

        FreshSession = sessionmaker(bind=db.bind)
        fresh = FreshSession()
        try:
            persisted = fresh.query(Run).filter(Run.id == run.id).first()
            assert persisted.status == "queued"
            assert (
                fresh.query(RunExecutionLock)
                .filter(RunExecutionLock.run_id == run.id)
                .first()
                is None
            )
        finally:
            fresh.close()

    def test_release_is_idempotent(self, db):
        """Releasing a lock that doesn't exist is a no-op (no exception)."""
        from app.runs.execution_lock import RunExecutionLockService
        from tests.support import factories

        space_id = "test-lock-idempotent"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        svc = RunExecutionLockService(db)
        svc.release(run.id)  # no lock exists — must not raise
        db.commit()

    def test_run_execution_service_returns_duplicate_execution_on_second_attempt(self, db):
        """When a lock is held, RunExecutionService.execute_run returns duplicate_execution
        error code without re-executing the run."""
        from app.runs.execution import RunExecutionService
        from app.runs.execution_lock import RunExecutionLockService
        from app.models import AgentVersion

        space_id = "test-dup-exec"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        # Acquire the lock with "worker-A" before calling execute_run with "worker-B"
        lock_svc = RunExecutionLockService(db)
        lock_svc.try_acquire(run.id, worker_id="worker-A")
        db.commit()

        # Worker B attempts to execute the same run while A holds the lock
        result = RunExecutionService(db).execute_run(
            run.id, space_id=space_id, worker_id="worker-B"
        )
        assert result.success is False
        assert result.error_code == "duplicate_execution"
        assert "already being executed" in result.error

        # Run status must remain queued (no mutation happened)
        from app.models import Run
        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "queued", (
            f"Run status mutated despite lock conflict: {run_row.status}"
        )

        # Clean up lock
        lock_svc.release(run.id)
        db.commit()

    def test_lock_released_after_successful_run(self, db, monkeypatch):
        """After execute_run succeeds the lock row must be gone from the DB."""
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion, Run
        from app.models import RunExecutionLock

        _patch_success_adapter_without_artifact(monkeypatch)
        space_id = "test-lock-cleanup-ok"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=space_id, worker_id="worker-X")

        db.expire_all()
        lock = db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
        assert lock is None, "Lock row was not cleaned up after successful execution"
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "succeeded"

    def test_lock_released_after_failed_run(self, db):
        """After execute_run fails the lock row must also be cleaned up."""
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion, Run
        from app.models import RunExecutionLock

        space_id = "test-lock-cleanup-fail"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # critical risk → fails with one_shot_docker error
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "critical", "default_adapter_type": "model_api"}
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        result = RunExecutionService(db).execute_run(run.id, space_id=space_id, worker_id="worker-Y")
        assert result.success is False

        db.expire_all()
        lock = db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
        assert lock is None, "Lock row was not cleaned up after failed execution"

    def test_cancelled_run_preserves_cancelled_status_not_succeeded(self, db):
        """Cancellation race — lock must be released and run remains cancelled."""
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion, Run, RunExecutionLock

        space_id = "test-lock-cancel"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        original_refresh = db.refresh

        def _patch_refresh(obj):
            original_refresh(obj)
            if isinstance(obj, Run) and obj.id == run.id:
                obj.status = "cancelled"

        with patch.object(db, "refresh", side_effect=_patch_refresh):
            result = RunExecutionService(db).execute_run(
                run.id, space_id=space_id, worker_id="worker-Z"
            )

        assert result.error_code == "run_cancelled"
        assert result.success is False

        db.expire_all()
        lock = db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
        assert lock is None, "Lock not released after cancellation"
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "cancelled"


# ===========================================================================
# Non-UTF-8 file changes are skipped with evidence
# ===========================================================================


class TestNonUtf8FilesSkipped:
    """Non-UTF-8 file changes must be surfaced as skipped (reason=not_utf8),
    not silently omitted.  incomplete_patch=True is set when ops exist alongside
    the skipped non-UTF-8 file."""

    def test_non_utf8_file_skipped_in_real_git_repo(self, tmp_path, db):
        """A file with non-UTF-8 bytes in the worktree is skipped with reason=not_utf8."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal

        space_id = "test-nonutf8-skip"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.flush()
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")

        # Add a text file that we will modify (to produce an op)
        (repo / "main.py").write_text("x = 1", encoding="utf-8")
        subprocess.run(["git", "add", "main.py"], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(
            ["git", "commit", "-m", "add main.py"],
            check=True, capture_output=True, cwd=str(repo),
        )

        # Modify main.py (this becomes a replace_file op)
        (repo / "main.py").write_text("x = 2", encoding="utf-8")

        # Write a non-UTF-8 file that is untracked (will appear as ??)
        latin1_bytes = "café résumé".encode("latin-1")  # valid latin-1, invalid UTF-8
        (repo / "latin1_data.txt").write_bytes(latin1_bytes)

        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=repo)

        # main.py should be collected, latin1_data.txt should be skipped
        assert result.proposal_created is True, "Expected proposal for main.py"
        assert result.incomplete_patch is True, "Expected incomplete_patch=True when non-UTF-8 file skipped"
        assert any(
            s["reason"] == "not_utf8" and "latin1_data" in s["path"]
            for s in result.skipped
        ), f"Expected not_utf8 entry in skipped, got: {result.skipped}"

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        assert prop.payload_json["incomplete_patch"] is True
        assert any(
            s["reason"] == "not_utf8" for s in prop.payload_json.get("skipped_changes", [])
        )

    def test_only_non_utf8_file_changed_creates_no_proposal(self, tmp_path, db):
        """When ALL changes are non-UTF-8 files, no proposal is created.
        The outcome is visible in WorktreeCollectionResult.no_op_reason."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal

        space_id = "test-nonutf8-only"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.flush()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "base.txt", "base")

        # Only a non-UTF-8 untracked file — no text ops
        latin1_bytes = "naïve façade".encode("latin-1")
        (repo / "encoding_issue.bin").write_bytes(latin1_bytes)

        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=repo)

        assert result.proposal_created is False
        assert any(s["reason"] == "not_utf8" for s in result.skipped)
        assert result.no_op_reason is not None

        proposals = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
        assert len(proposals) == 0, "No proposal should be created when all changes are non-UTF-8"


# ===========================================================================
# Durable lock release after execution
# ===========================================================================


def _fresh_session(db):
    """Return a new independent session backed by the same engine as *db*."""
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=db.bind)()


class TestDurableLockRelease:
    """After execute_run (success, failure, cancellation), a fresh DB session must
    see no run_execution_locks row.  This proves the DELETE is committed durably,
    not just flushed in-session."""

    def test_lock_absent_in_fresh_session_after_success(self, db, monkeypatch):
        from app.models import AgentVersion, RunExecutionLock
        from app.runs.execution import RunExecutionService

        _patch_success_adapter_without_artifact(monkeypatch)
        space_id = "test-durable-lock-ok"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        RunExecutionService(db).execute_run(run.id, space_id=space_id, worker_id="worker-fresh-ok")

        db2 = _fresh_session(db)
        try:
            lock = db2.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
            assert lock is None, "Lock row persists in a fresh session after successful execution"
        finally:
            db2.close()

    def test_lock_absent_in_fresh_session_after_failure(self, db):
        from app.models import AgentVersion, RunExecutionLock
        from app.runs.execution import RunExecutionService

        space_id = "test-durable-lock-fail"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "critical", "default_adapter_type": "model_api"}
        db.commit()
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        result = RunExecutionService(db).execute_run(run.id, space_id=space_id, worker_id="worker-fresh-fail")
        assert result.success is False

        db2 = _fresh_session(db)
        try:
            lock = db2.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
            assert lock is None, "Lock row persists in a fresh session after failed execution"
        finally:
            db2.close()

    def test_lock_absent_in_fresh_session_after_cancellation_race(self, db):
        from app.models import AgentVersion, Run, RunExecutionLock
        from app.runs.execution import RunExecutionService

        space_id = "test-durable-lock-cancel"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        original_refresh = db.refresh

        def _patch_refresh(obj):
            original_refresh(obj)
            if isinstance(obj, Run) and obj.id == run.id:
                obj.status = "cancelled"

        with patch.object(db, "refresh", side_effect=_patch_refresh):
            result = RunExecutionService(db).execute_run(
                run.id, space_id=space_id, worker_id="worker-fresh-cancel"
            )
        assert result.error_code == "run_cancelled"

        db2 = _fresh_session(db)
        try:
            lock = db2.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
            assert lock is None, "Lock row persists in a fresh session after cancellation"
        finally:
            db2.close()


# ===========================================================================
# Orphan lock cleanup in reclaim
# ===========================================================================


class TestOrphanLockCleanup:
    """reclaim_stuck_jobs removes stale execution locks for the reclaimed jobs
    without touching locks held by fresh-heartbeating jobs."""

    def test_stale_job_lock_is_removed_on_reclaim(self, db):
        """Stale agent_run job + matching lock → job reclaimed AND lock deleted."""
        from app.models import Job, RunExecutionLock
        from sqlalchemy import text

        space_id = "test-orphan-stale"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-stale",
            payload_json={"run_id": run.id, "space_id": space_id, "user_id": user.id},
        )
        db.add(job)
        db.flush()
        stale_ts = _dt(datetime.now(UTC) - timedelta(hours=2))
        db.execute(text("UPDATE jobs SET updated_at = :ts, heartbeat_at = :ts WHERE id = :id"),
                   {"ts": stale_ts, "id": job.id})

        lock = RunExecutionLock(
            run_id=run.id,
            locked_at=datetime.now(UTC) - timedelta(hours=2),
            worker_id="worker-stale",
            job_id=job.id,
        )
        db.add(lock)
        db.commit()

        n = _make_queue_svc(db)._reclaim_stuck_sync(600)

        assert n >= 1
        db.expire_all()
        reloaded_job = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded_job.status == "pending"
        assert reloaded_job.heartbeat_at is None, "Reclaimed job retains stale heartbeat_at"
        remaining_lock = db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
        assert remaining_lock is None, "Orphan lock was not removed on reclaim"

    def test_fresh_heartbeat_job_lock_is_preserved(self, db):
        """Fresh-heartbeating job is not reclaimed and its lock is not touched."""
        from app.models import Job, RunExecutionLock
        from sqlalchemy import text

        space_id = "test-orphan-fresh"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-fresh",
            payload_json={"run_id": run.id, "space_id": space_id, "user_id": user.id},
        )
        db.add(job)
        db.flush()
        stale_ts = _dt(datetime.now(UTC) - timedelta(hours=2))
        fresh_hb = _dt(datetime.now(UTC) - timedelta(seconds=10))
        db.execute(text(
            "UPDATE jobs SET updated_at = :stale, heartbeat_at = :hb WHERE id = :id"
        ), {"stale": stale_ts, "hb": fresh_hb, "id": job.id})

        lock = RunExecutionLock(
            run_id=run.id,
            locked_at=datetime.now(UTC) - timedelta(hours=2),
            worker_id="worker-fresh",
            job_id=job.id,
        )
        db.add(lock)
        db.commit()

        n = _make_queue_svc(db)._reclaim_stuck_sync(600)

        assert n == 0, "Fresh-heartbeat job was incorrectly reclaimed"
        db.expire_all()
        remaining_lock = db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first()
        assert remaining_lock is not None, "Active run lock was removed for a fresh-heartbeat job"

    def test_lock_cleanup_failure_writes_job_event_and_reclaim_continues(self, db_engine_isolated):
        """Best-effort stale lock cleanup failures are visible in job events."""
        from app.jobs.queue import PostgresQueueService
        from app.models import Job, JobEvent, RunExecutionLock
        from sqlalchemy import text
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine_isolated)
        db = Session()
        space_id = "test-orphan-cleanup-warning"
        try:
            factories.create_test_space(db, space_id=space_id, commit=True)
            user = factories.create_test_user(db, space_id=space_id, commit=True)
            agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
            run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

            job = Job(
                id=str(uuid.uuid4()),
                space_id=space_id,
                user_id=user.id,
                job_type="agent_run",
                status="running",
                attempts=1,
                max_attempts=3,
                scheduled_at=datetime.now(UTC),
                claimed_by="worker-stale",
                payload_json={"run_id": run.id, "space_id": space_id, "user_id": user.id},
            )
            db.add(job)
            db.flush()
            stale_ts = _dt(datetime.now(UTC) - timedelta(hours=2))
            db.execute(text("UPDATE jobs SET updated_at = :ts, heartbeat_at = :ts WHERE id = :id"),
                       {"ts": stale_ts, "id": job.id})
            db.add(
                RunExecutionLock(
                    run_id=run.id,
                    locked_at=datetime.now(UTC) - timedelta(hours=2),
                    worker_id="worker-stale",
                    job_id=job.id,
                )
            )
            db.commit()

            class FailingLockCleanupSession:
                def __init__(self):
                    self.inner = Session()

                def execute(self, statement, params=None, *args, **kwargs):
                    if "DELETE FROM run_execution_locks" in str(statement):
                        raise RuntimeError("forced lock cleanup failure")
                    return self.inner.execute(statement, params, *args, **kwargs)

                def __getattr__(self, name):
                    return getattr(self.inner, name)

            svc = PostgresQueueService(db_factory=FailingLockCleanupSession)
            n = svc._reclaim_stuck_sync(600)

            assert n >= 1
            db.expire_all()
            reloaded_job = db.query(Job).filter(Job.id == job.id).first()
            assert reloaded_job.status == "pending"
            assert db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run.id).first() is not None

            event = (
                db.query(JobEvent)
                .filter(JobEvent.job_id == job.id, JobEvent.event_type == "warning")
                .one_or_none()
            )
            assert event is not None
            assert event.message == "orphan run execution lock cleanup failed during stuck-job reclaim"
            assert event.data == {
                "operation": "reclaim_stuck_jobs",
                "diagnostic": "orphan_run_execution_lock_cleanup_failed",
            }
        finally:
            db.close()

    def test_stale_lock_cleanup_does_not_affect_unrelated_active_run(self, db):
        """Reclaiming job A's stale lock must not delete job B's active lock."""
        from app.models import Job, RunExecutionLock
        from sqlalchemy import text

        space_id = "test-orphan-unrelated"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        run_a = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        run_b = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        # Stale job for run_a
        job_a = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-stale-a",
            payload_json={"run_id": run_a.id, "space_id": space_id, "user_id": user.id},
        )
        # Fresh-heartbeat job for run_b
        job_b = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-fresh-b",
            payload_json={"run_id": run_b.id, "space_id": space_id, "user_id": user.id},
        )
        db.add(job_a)
        db.add(job_b)
        db.flush()

        stale_ts = _dt(datetime.now(UTC) - timedelta(hours=2))
        fresh_hb = _dt(datetime.now(UTC) - timedelta(seconds=5))
        db.execute(text("UPDATE jobs SET updated_at = :ts, heartbeat_at = :ts WHERE id = :id"),
                   {"ts": stale_ts, "id": job_a.id})
        db.execute(text("UPDATE jobs SET updated_at = :stale, heartbeat_at = :hb WHERE id = :id"),
                   {"stale": stale_ts, "hb": fresh_hb, "id": job_b.id})

        lock_a = RunExecutionLock(run_id=run_a.id, locked_at=datetime.now(UTC) - timedelta(hours=2),
                                  worker_id="worker-stale-a", job_id=job_a.id)
        lock_b = RunExecutionLock(run_id=run_b.id, locked_at=datetime.now(UTC) - timedelta(seconds=5),
                                  worker_id="worker-fresh-b", job_id=job_b.id)
        db.add(lock_a)
        db.add(lock_b)
        db.commit()

        _make_queue_svc(db)._reclaim_stuck_sync(600)

        db.expire_all()
        assert db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run_a.id).first() is None, \
            "Stale lock for run_a should have been removed"
        assert db.query(RunExecutionLock).filter(RunExecutionLock.run_id == run_b.id).first() is not None, \
            "Active lock for run_b was incorrectly removed"


# ===========================================================================
# Heartbeat lifecycle
# ===========================================================================


class TestHeartbeatLifecycle:
    """Queue lifecycle operations clear heartbeat_at at the right transitions."""

    def test_reclaimed_job_has_null_heartbeat_at(self, db):
        """After reclaim, heartbeat_at is NULL — the next attempt starts fresh."""
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-lifecycle-reclaim"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)

        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            claimed_by="worker-crash",
        )
        db.add(job)
        db.flush()
        stale = _dt(datetime.now(UTC) - timedelta(hours=3))
        db.execute(text("UPDATE jobs SET updated_at = :ts, heartbeat_at = :ts WHERE id = :id"),
                   {"ts": stale, "id": job.id})
        db.commit()

        _make_queue_svc(db)._reclaim_stuck_sync(600)

        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.status == "pending"
        assert reloaded.heartbeat_at is None, \
            "Reclaimed job still has stale heartbeat_at — next attempt may be prematurely reclaimed"

    def test_start_job_initialises_heartbeat_at(self, db):
        """start_job() sets heartbeat_at to now so the reclaim window opens immediately."""
        from app.models import Job

        space_id = "test-hb-start"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="claimed",
            attempts=0,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
        )
        db.add(job)
        db.commit()

        before = datetime.now(UTC)
        _make_queue_svc(db)._start_job_sync(job.id)
        after = datetime.now(UTC)

        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.heartbeat_at is not None, "start_job did not set heartbeat_at"
        hb = reloaded.heartbeat_at.replace(tzinfo=UTC) if reloaded.heartbeat_at.tzinfo is None \
            else reloaded.heartbeat_at
        assert before <= hb <= after

    def test_complete_job_clears_heartbeat_at(self, db):
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-complete"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="running",
            attempts=1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
        )
        db.add(job)
        db.commit()
        db.execute(text("UPDATE jobs SET heartbeat_at = :hb WHERE id = :id"),
                   {"hb": _dt(datetime.now(UTC)), "id": job.id})
        db.commit()

        _make_queue_svc(db)._complete_job_sync(job.id, {"status": "ok"})

        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.heartbeat_at is None, "complete_job did not clear heartbeat_at"

    def test_cancel_job_clears_heartbeat_at(self, db):
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-cancel"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type="agent_run",
            status="pending",
            attempts=0,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            payload_json={},
        )
        db.add(job)
        db.commit()
        db.execute(text("UPDATE jobs SET heartbeat_at = :hb WHERE id = :id"),
                   {"hb": _dt(datetime.now(UTC)), "id": job.id})
        db.commit()

        _make_queue_svc(db)._cancel_job_sync(job.id)

        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.heartbeat_at is None, "cancel_job did not clear heartbeat_at"

    def test_claim_next_clears_heartbeat_at_from_prior_attempt(self, db):
        """claim_next clears heartbeat_at so a re-claimed job starts with a clean slate.

        Uses a unique job_type per test run so _claim_next_sync only sees this
        test's job regardless of leftover pending rows from earlier tests in the
        same session (e.g. jobs reclaimed to 'pending' by reclaim_stuck_jobs).
        """
        from app.models import Job
        from sqlalchemy import text

        space_id = "test-hb-claim"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        stale_hb = datetime.now(UTC) - timedelta(hours=1)
        # Unique job_type prevents _claim_next_sync from picking up leftover
        # pending rows that were reclaimed by earlier tests in this session.
        unique_job_type = f"test-hb-claim-{str(uuid.uuid4())}"
        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user.id,
            job_type=unique_job_type,
            status="pending",
            attempts=0,
            max_attempts=3,
            scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        db.add(job)
        db.commit()
        db.execute(text("UPDATE jobs SET heartbeat_at = :hb WHERE id = :id"),
                   {"hb": _dt(stale_hb), "id": job.id})
        db.commit()

        claimed = _make_queue_svc(db)._claim_next_sync("worker-claim-test", [unique_job_type])

        assert claimed is not None and claimed.id == job.id
        db.expire_all()
        reloaded = db.query(Job).filter(Job.id == job.id).first()
        assert reloaded.heartbeat_at is None, "claim_next did not clear stale heartbeat_at"


# ===========================================================================
# Job cancellation linkage
# ===========================================================================


class TestJobCancellationLinkage:
    """Cancelling an agent_run job with payload.run_id cancels the linked Run
    when that Run is not already in a terminal status."""

    def _make_job_with_run(self, db, *, space_id: str, user_id: str, run, job_status: str):
        from app.models import Job
        job = Job(
            id=str(uuid.uuid4()),
            space_id=space_id,
            user_id=user_id,
            job_type="agent_run",
            status=job_status,
            attempts=0 if job_status == "pending" else 1,
            max_attempts=3,
            scheduled_at=datetime.now(UTC),
            payload_json={"run_id": run.id, "space_id": space_id, "user_id": user_id},
        )
        db.add(job)
        db.commit()
        return job

    def test_cancel_pending_job_cancels_queued_run(self, db):
        """Cancelling a pending agent_run job sets the linked queued Run to cancelled."""
        from app.models import Run

        space_id = "test-cancel-link-pending"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        assert run.status == "queued"

        job = self._make_job_with_run(db, space_id=space_id, user_id=user.id, run=run,
                                      job_status="pending")
        _make_queue_svc(db)._cancel_job_sync(job.id)

        db.expire_all()
        from sqlalchemy.orm import sessionmaker
        db2 = sessionmaker(bind=db.bind)()
        try:
            run_row = db2.query(Run).filter(Run.id == run.id).first()
            assert run_row.status == "cancelled", \
                f"Run not cancelled after job cancellation: {run_row.status}"
        finally:
            db2.close()

    def test_cancel_claimed_job_cancels_running_run(self, db):
        """Cancelling a claimed agent_run job cancels the linked Run if non-terminal."""
        from app.models import Run
        from sqlalchemy import text

        space_id = "test-cancel-link-claimed"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        # Simulate in-progress run
        db.execute(text("UPDATE runs SET status = 'running' WHERE id = :id"), {"id": run.id})
        db.commit()

        job = self._make_job_with_run(db, space_id=space_id, user_id=user.id, run=run,
                                      job_status="claimed")
        _make_queue_svc(db)._cancel_job_sync(job.id)

        db.expire_all()
        from sqlalchemy.orm import sessionmaker
        db2 = sessionmaker(bind=db.bind)()
        try:
            run_row = db2.query(Run).filter(Run.id == run.id).first()
            assert run_row.status == "cancelled", \
                f"Running run not cancelled after claimed-job cancellation: {run_row.status}"
        finally:
            db2.close()

    def test_cancel_job_does_not_mutate_succeeded_run(self, db):
        """Cancelling a job must not overwrite a Run that already succeeded."""
        from app.models import Run
        from sqlalchemy import text

        space_id = "test-cancel-link-succeeded"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        db.execute(text("UPDATE runs SET status = 'succeeded' WHERE id = :id"), {"id": run.id})
        db.commit()

        job = self._make_job_with_run(db, space_id=space_id, user_id=user.id, run=run,
                                      job_status="pending")
        _make_queue_svc(db)._cancel_job_sync(job.id)

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "succeeded", \
            "Succeeded run was mutated by job cancellation"

    def test_cancel_job_does_not_mutate_failed_run(self, db):
        """Cancelling a job must not overwrite a Run that already failed."""
        from app.models import Run
        from sqlalchemy import text

        space_id = "test-cancel-link-failed"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        db.execute(text("UPDATE runs SET status = 'failed' WHERE id = :id"), {"id": run.id})
        db.commit()

        job = self._make_job_with_run(db, space_id=space_id, user_id=user.id, run=run,
                                      job_status="pending")
        _make_queue_svc(db)._cancel_job_sync(job.id)

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "failed", "Failed run was mutated by job cancellation"


# ===========================================================================
# Duplicate execution: non-retryable, enriched result
# ===========================================================================


class TestDuplicateExecutionQueueSemantics:
    """When execute_run returns duplicate_execution, the handler must:
    - Return a completed result dict (no exception → no retry)
    - Include skipped=True, skip_reason='duplicate_execution', error_code='duplicate_execution'
    - Not create any code_patch proposals."""

    def test_duplicate_execution_handler_result_has_skipped_fields(self, db, monkeypatch):
        """Handler returns the required fields when a lock conflict is detected.

        The handler's internal SessionLocal is patched to use the test engine so
        all data (the pre-committed lock row) is visible to the handler session.
        """
        from sqlalchemy.orm import sessionmaker
        from app.jobs.handlers import _execute_existing_run
        from app.models import AgentVersion
        from app.runs.execution_lock import RunExecutionLockService

        # Redirect SessionLocal in app.db to the test engine so _execute_existing_run
        # can see the lock row that we committed with the `db` fixture session.
        TestSessionCls = sessionmaker(bind=db.bind)
        monkeypatch.setattr("app.db.SessionLocal", TestSessionCls)

        space_id = "test-dup-handler"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        # Hold the lock so execute_run returns duplicate_execution
        lock_svc = RunExecutionLockService(db)
        lock_svc.try_acquire(run.id, worker_id="worker-holder")
        db.commit()

        job = SimpleNamespace(id=str(uuid.uuid4()), space_id=space_id, user_id=user.id, payload=None)
        payload = {"run_id": run.id, "space_id": space_id, "user_id": user.id}

        result = _execute_existing_run(job, payload, run.id)

        assert result.get("skipped") is True, "Handler result missing skipped=True"
        assert result.get("skip_reason") == "duplicate_execution"
        assert result.get("error_code") == "duplicate_execution"
        assert result.get("run_id") == run.id

        # Release lock for cleanup
        lock_svc.release(run.id)

    def test_duplicate_execution_creates_no_proposal(self, db, monkeypatch):
        """No code_patch proposal is created when duplicate_execution prevents execution."""
        from sqlalchemy.orm import sessionmaker
        from app.jobs.handlers import _execute_existing_run
        from app.models import AgentVersion, Proposal
        from app.runs.execution_lock import RunExecutionLockService

        TestSessionCls = sessionmaker(bind=db.bind)
        monkeypatch.setattr("app.db.SessionLocal", TestSessionCls)

        space_id = "test-dup-no-proposal"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "model_api"}
        db.commit()
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        lock_svc = RunExecutionLockService(db)
        lock_svc.try_acquire(run.id, worker_id="worker-holder-np")
        db.commit()

        job = SimpleNamespace(id=str(uuid.uuid4()), space_id=space_id, user_id=user.id, payload=None)
        payload = {"run_id": run.id, "space_id": space_id, "user_id": user.id}
        _execute_existing_run(job, payload, run.id)

        proposals = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).all()
        assert len(proposals) == 0, "duplicate_execution should not create any proposals"

        lock_svc.release(run.id)


# ===========================================================================
# Heartbeat diagnostics schema
# ===========================================================================


class TestJobDiagnosticsSchema:
    """heartbeat_at is present in JobOut and serialises correctly."""

    def test_job_out_includes_heartbeat_at_field(self):
        from app.jobs.schemas import JobOut
        import inspect
        fields = JobOut.model_fields
        assert "heartbeat_at" in fields, "JobOut is missing heartbeat_at field"

    def test_job_out_heartbeat_at_accepts_none(self):
        from app.jobs.schemas import JobOut
        from datetime import timezone
        now = datetime.now(timezone.utc)
        job_data = {
            "id": "test-job-schema",
            "space_id": "test-space",
            "user_id": "test-user",
            "workspace_id": None,
            "agent_id": None,
            "job_type": "agent_run",
            "status": "pending",
            "priority": 0,
            "payload": None,
            "result": None,
            "error": None,
            "attempts": 0,
            "max_attempts": 3,
            "claimed_by": None,
            "claimed_at": None,
            "scheduled_at": now,
            "started_at": None,
            "completed_at": None,
            "heartbeat_at": None,
            "created_at": now,
            "updated_at": now,
        }
        obj = JobOut(**job_data)
        assert obj.heartbeat_at is None

    def test_job_out_heartbeat_at_accepts_datetime(self):
        from app.jobs.schemas import JobOut
        from datetime import timezone
        now = datetime.now(timezone.utc)
        job_data = {
            "id": "test-job-schema-hb",
            "space_id": "test-space",
            "user_id": "test-user",
            "workspace_id": None,
            "agent_id": None,
            "job_type": "agent_run",
            "status": "running",
            "priority": 0,
            "payload": None,
            "result": None,
            "error": None,
            "attempts": 1,
            "max_attempts": 3,
            "claimed_by": "worker-x",
            "claimed_at": now,
            "scheduled_at": now,
            "started_at": now,
            "completed_at": None,
            "heartbeat_at": now,
            "created_at": now,
            "updated_at": now,
        }
        obj = JobOut(**job_data)
        assert obj.heartbeat_at == now
