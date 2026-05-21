"""Unit tests for code_patch proposal → Task linkage (task B).

Tests in this file verify:
  1. A task-linked run that produces a code_patch proposal results in a TaskProposal link.
  2. Re-running link_run_outputs_to_tasks for the same proposal does not duplicate the link.
  3. A run without TaskRun linkage still creates the code_patch proposal normally.
  4. link_run_outputs_to_tasks with code_patch role sets role='code_patch'.
  5. WorktreeCollectionResult.proposal is set when a proposal is created.
  6. WorktreeCollectionResult.proposal is None when no changes are found.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(run_id: str = "run-001", space_id: str = "sp-a", workspace_id: str = "ws-a"):
    run = MagicMock()
    run.id = run_id
    run.space_id = space_id
    run.workspace_id = workspace_id
    run.instructed_by_user_id = "user-a"
    return run


# ===========================================================================
# 1. WorktreeCollectionResult carries the Proposal when created
# ===========================================================================

class TestWorktreeCollectionResultProposal:
    def test_proposal_set_when_changes_found(self, tmp_path):
        """When ops are found, WorktreeCollectionResult.proposal is a Proposal-like object."""
        import subprocess
        from pathlib import Path
        from unittest.mock import MagicMock

        # Set up a real git repo with one committed file
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(repo))
        (repo / "a.txt").write_text("original", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(repo))

        # Modify the file (simulates what the CLI adapter would do)
        (repo / "a.txt").write_text("modified", encoding="utf-8")

        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal

        mock_db = MagicMock()
        mock_run = _make_run()

        result = collect_and_create_code_patch_proposal(mock_db, run=mock_run, worktree_path=repo)

        assert result.proposal_created is True
        assert result.proposal is not None
        assert result.ops_count >= 1

    def test_proposal_none_when_no_changes(self, tmp_path):
        """When no changes are found, WorktreeCollectionResult.proposal is None."""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(repo))
        (repo / "a.txt").write_text("original", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(repo))
        # No modifications

        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal

        mock_db = MagicMock()
        mock_run = _make_run()

        result = collect_and_create_code_patch_proposal(mock_db, run=mock_run, worktree_path=repo)

        assert result.proposal_created is False
        assert result.proposal is None
        assert result.ops_count == 0


# ===========================================================================
# 2. link_run_outputs_to_tasks creates TaskProposal for task-linked runs
# ===========================================================================

class TestLinkRunOutputsToTasks:
    def test_proposal_linked_to_task_when_taskrun_exists(self, db, cross_space_pair):
        """A run linked to a task via TaskRun gets a TaskProposal row for the code_patch proposal."""
        from ulid import ULID
        from app.models import Proposal, Task, TaskProposal, TaskRun, Run
        from app.runs.task_output_linkage import link_run_outputs_to_tasks
        from tests.support import factories

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]

        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        # Create a Task in the same space
        task = Task(
            id=str(ULID()),
            space_id=a,
            title="Test task for linkage",
        )
        db.add(task)
        db.flush()

        # Link the run to the task via TaskRun
        tr = TaskRun(
            id=str(ULID()),
            space_id=a,
            task_id=task.id,
            run_id=run_row.id,
        )
        db.add(tr)
        db.flush()

        # Create a code_patch proposal
        proposal = Proposal(
            id=str(ULID()),
            space_id=a,
            created_by_run_id=run_row.id,
            proposal_type="code_patch",
            status="pending",
            title="Code changes",
            payload_json={"patch": {"operations": []}},
        )
        db.add(proposal)
        db.flush()

        # Call the linkage helper
        link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
        db.commit()

        # Verify TaskProposal was created
        tp = (
            db.query(TaskProposal)
            .filter(TaskProposal.task_id == task.id, TaskProposal.proposal_id == proposal.id)
            .first()
        )
        assert tp is not None
        assert tp.role == "code_patch"
        assert tp.space_id == a

    def test_no_duplicate_task_proposal_on_repeated_call(self, db, cross_space_pair):
        """Calling link_run_outputs_to_tasks twice for the same proposal does not create duplicate rows."""
        from ulid import ULID
        from app.models import Proposal, Task, TaskProposal, TaskRun, Run
        from app.runs.task_output_linkage import link_run_outputs_to_tasks
        from tests.support import factories

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]

        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        task = Task(id=str(ULID()), space_id=a, title="Idempotence task")
        db.add(task)
        db.flush()

        tr = TaskRun(id=str(ULID()), space_id=a, task_id=task.id, run_id=run_row.id)
        db.add(tr)
        db.flush()

        proposal = Proposal(
            id=str(ULID()),
            space_id=a,
            created_by_run_id=run_row.id,
            proposal_type="code_patch",
            status="pending",
            title="Code changes (idempotence)",
            payload_json={"patch": {"operations": []}},
        )
        db.add(proposal)
        db.flush()

        # Call twice
        link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
        db.commit()
        link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
        db.commit()

        count = (
            db.query(TaskProposal)
            .filter(TaskProposal.task_id == task.id, TaskProposal.proposal_id == proposal.id)
            .count()
        )
        assert count == 1, f"Expected exactly 1 TaskProposal, got {count}"

    def test_run_without_taskrun_creates_no_task_proposal(self, db, cross_space_pair):
        """A run with no TaskRun linkage produces no TaskProposal rows."""
        from ulid import ULID
        from app.models import Proposal, TaskProposal, Run
        from app.runs.task_output_linkage import link_run_outputs_to_tasks
        from tests.support import factories

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]

        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        # No TaskRun created

        proposal = Proposal(
            id=str(ULID()),
            space_id=a,
            created_by_run_id=run_row.id,
            proposal_type="code_patch",
            status="pending",
            title="Orphan proposal",
            payload_json={"patch": {"operations": []}},
        )
        db.add(proposal)
        db.commit()

        link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
        db.commit()

        count = (
            db.query(TaskProposal)
            .filter(TaskProposal.proposal_id == proposal.id)
            .count()
        )
        assert count == 0

    def test_cross_space_taskrun_not_linked(self, db, cross_space_pair):
        """TaskRun rows from another space are not matched — cross-space linkage is impossible."""
        from ulid import ULID
        from app.models import Proposal, Task, TaskProposal, TaskRun, Run
        from app.runs.task_output_linkage import link_run_outputs_to_tasks
        from tests.support import factories

        a = cross_space_pair["space_a_id"]
        b = cross_space_pair["space_b_id"]
        ua = cross_space_pair["user_a"]

        # Run is in space A
        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        # Task is in space B
        task_b = Task(id=str(ULID()), space_id=b, title="Space B task")
        db.add(task_b)
        db.flush()

        # Attempt a cross-space TaskRun (space_id=b, run_id from space A)
        # link_run_outputs_to_tasks queries with space_id=run.space_id (a), so space B rows are invisible
        tr_cross = TaskRun(id=str(ULID()), space_id=b, task_id=task_b.id, run_id=run_row.id)
        db.add(tr_cross)
        db.flush()

        proposal = Proposal(
            id=str(ULID()),
            space_id=a,
            created_by_run_id=run_row.id,
            proposal_type="code_patch",
            status="pending",
            title="Cross-space proposal",
            payload_json={"patch": {"operations": []}},
        )
        db.add(proposal)
        db.commit()

        link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
        db.commit()

        # No TaskProposal should be created — cross-space TaskRun is filtered out
        count = (
            db.query(TaskProposal)
            .filter(TaskProposal.proposal_id == proposal.id)
            .count()
        )
        assert count == 0, "Cross-space TaskRun must not produce TaskProposal"
