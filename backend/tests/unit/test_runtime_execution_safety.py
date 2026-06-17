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

