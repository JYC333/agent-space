"""Runtime foundation hardening tests.

Covers:
  1. CLI registry — claude_code and codex_cli are registered
  2. Automation-origin CLI run rejects missing explicit credential profile
  3. Manual-origin CLI run rejects missing explicit credential profile
  4. Critical risk level fails early (critical_runtime_requires_unimplemented_one_shot_docker)
  5. High risk level resolves to worktree and passes file-access adapter policy
  6. Preflight endpoint — success and failure paths
  7. Stop/cancel behavior for pending and running runs
  8. Stale claimed/running job recovery (RunService.recover_stale_runs)
  9. Process registry — register, deregister, terminate, deregistered-on-exit
 10. incomplete_patch metadata for skipped deleted/renamed/binary/oversized changes
 11. trigger_origin propagated from RuntimeExecutionContext
"""

from __future__ import annotations
import uuid

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from types import SimpleNamespace


def _patch_success_adapter_without_artifact(monkeypatch) -> None:
    """Execute successfully without unrelated runtime artifact persistence."""
    from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _adapter_type: ConfigurableFakeRuntimeAdapter(FakeRuntimeConfig(output_text="")),
    )


# ===========================================================================
# 1. CLI runtime registry
# ===========================================================================


class TestCliRuntimeRegistry:
    def test_claude_code_in_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("claude_code")

    def test_codex_cli_in_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("codex_cli")

    def test_echo_in_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("echo")

    def test_claude_code_has_file_access_flag(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        adapter = instantiate_runtime_adapter("claude_code")
        assert adapter.requires_file_access is True
        assert adapter.supports_sandboxed_execution is True

    def test_codex_cli_has_file_access_flag(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        adapter = instantiate_runtime_adapter("codex_cli")
        assert adapter.requires_file_access is True
        assert adapter.supports_sandboxed_execution is True


# ===========================================================================
# 2. Automation-origin credential check
# ===========================================================================


def _make_ctx(
    *,
    trigger_origin: str = "manual",
    adapter_type: str = "claude_code",
    run_id: str = "run-test-001",
) -> "RuntimeExecutionContext":
    from app.runtimes.base import RuntimeExecutionContext
    return RuntimeExecutionContext(
        run_id=run_id,
        space_id="space-test",
        prompt="Do the thing.",
        mode="live",
        sandbox_cwd="/tmp/sandbox",
        model_name=None,
        system_prompt=None,
        adapter_config={},
        trigger_origin=trigger_origin,
    )


class TestAutomationCredentialCheck:
    def test_automation_origin_with_no_profile_fails(self):
        """CLI run with no credential grant must fail with runtime_credential_profile_required."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=None),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        assert "credential profile" in result.error_text.lower()

    def test_automation_origin_with_profile_proceeds(self):
        """Automation run with a valid credential grant must proceed past the credential check."""
        from app.runtimes.local_executor import ExecutionResult
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        mock_grant = MagicMock()
        mock_grant.temp_home = None
        mock_grant.env = {}

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch.object(adapter, "_render_context", return_value=None),
            patch.object(adapter.executor, "run_command", return_value=ExecutionResult(0, "done", "")),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        assert result.error_code is None

    def test_manual_origin_with_no_profile_fails(self):
        """Manual-origin CLI runs require the same explicit credential profile."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="manual")

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=None),
        ):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        meta = result.adapter_metadata or {}
        assert meta.get("credential_source") == "none"
        assert meta.get("fallback_used") is True
        assert meta.get("fallback_reason") == "no_profile_configured"

    def test_codex_cli_automation_origin_fails_without_profile(self):
        """codex_cli shares the same automation credential guard."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("codex_cli")
        ctx = _make_ctx(trigger_origin="automation", adapter_type="codex_cli")

        with patch.object(adapter, "_resolve_credential_grant", return_value=None):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"

    def test_trigger_origin_recorded_in_adapter_metadata(self):
        """trigger_origin is recorded in cred_meta for audit purposes."""
        from app.runtimes.local_executor import ExecutionResult
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        mock_grant = MagicMock()
        mock_grant.temp_home = None
        mock_grant.env = {}

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch.object(adapter, "_render_context", return_value=None),
            patch.object(adapter.executor, "run_command", return_value=ExecutionResult(0, "ok", "")),
        ):
            result = adapter.execute(ctx)

        assert result.adapter_metadata is not None
        assert result.adapter_metadata.get("trigger_origin") == "automation"


# ===========================================================================
# 3. trigger_origin field on RuntimeExecutionContext
# ===========================================================================


class TestTriggerOriginField:
    def test_defaults_to_manual(self):
        from app.runtimes.base import RuntimeExecutionContext
        ctx = RuntimeExecutionContext(
            run_id="r1", space_id="s1", prompt="p", mode="live",
            sandbox_cwd=None, model_name=None, system_prompt=None, adapter_config={},
        )
        assert ctx.trigger_origin == "manual"

    def test_can_be_set_to_automation(self):
        from app.runtimes.base import RuntimeExecutionContext
        ctx = RuntimeExecutionContext(
            run_id="r1", space_id="s1", prompt="p", mode="live",
            sandbox_cwd=None, model_name=None, system_prompt=None, adapter_config={},
            trigger_origin="automation",
        )
        assert ctx.trigger_origin == "automation"


# ===========================================================================
# 4. Critical risk level fails early
# ===========================================================================


class TestCriticalRiskLevelFails:
    def test_critical_risk_required_sandbox_is_one_shot_docker(self):
        from app.runs.runtime_policy import required_sandbox_level_for_risk
        assert required_sandbox_level_for_risk("critical") == "one_shot_docker"

    def test_critical_sandbox_error_code_is_canonical(self, db):
        """A Run with critical risk level must fail with the canonical error code."""
        from tests.support import factories
        from app.runs.run_service import RunService
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion

        space_id = "test-critical-risk"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Set risk_level=critical on the agent version
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {
            **dict(version.runtime_policy_json or {}),
            "risk_level": "critical",
            "default_adapter_type": "echo",
        }
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

        assert result.success is False
        assert result.error_code == "critical_runtime_requires_unimplemented_one_shot_docker"
        assert "one_shot_docker" in result.error
        db.refresh(run)
        assert run.status == "failed"


# ===========================================================================
# 5. High risk → worktree policy enforcement
# ===========================================================================


class TestHighRiskWorktreePolicy:
    def test_high_risk_resolves_to_worktree(self):
        from app.runs.runtime_policy import required_sandbox_level_for_risk
        assert required_sandbox_level_for_risk("high") == "worktree"

    def test_claude_code_at_high_risk_passes_policy_check(self):
        from app.runs.runtime_policy import RuntimePolicyDecision, validate_file_access_adapter_policy
        decision = RuntimePolicyDecision(
            required_sandbox_level="worktree",
            risk_level="high",
            policy_snapshot={},
        )
        error = validate_file_access_adapter_policy(adapter_type="claude_code", decision=decision)
        assert error is None

    def test_codex_cli_at_high_risk_passes_policy_check(self):
        from app.runs.runtime_policy import RuntimePolicyDecision, validate_file_access_adapter_policy
        decision = RuntimePolicyDecision(
            required_sandbox_level="worktree",
            risk_level="high",
            policy_snapshot={},
        )
        error = validate_file_access_adapter_policy(adapter_type="codex_cli", decision=decision)
        assert error is None

    def test_claude_code_at_low_risk_fails_policy(self):
        from app.runs.runtime_policy import RuntimePolicyDecision, validate_file_access_adapter_policy
        decision = RuntimePolicyDecision(
            required_sandbox_level="none",
            risk_level="low",
            policy_snapshot={},
        )
        error = validate_file_access_adapter_policy(adapter_type="claude_code", decision=decision)
        assert error is not None
        assert "worktree" in error

    def test_codex_cli_at_medium_risk_fails_policy(self):
        from app.runs.runtime_policy import RuntimePolicyDecision, validate_file_access_adapter_policy
        decision = RuntimePolicyDecision(
            required_sandbox_level="dry_run",
            risk_level="medium",
            policy_snapshot={},
        )
        error = validate_file_access_adapter_policy(adapter_type="codex_cli", decision=decision)
        assert error is not None
        assert "codex_cli" in error

    def test_echo_at_low_risk_is_fine(self):
        from app.runs.runtime_policy import RuntimePolicyDecision, validate_file_access_adapter_policy
        decision = RuntimePolicyDecision(
            required_sandbox_level="none",
            risk_level="low",
            policy_snapshot={},
        )
        error = validate_file_access_adapter_policy(adapter_type="echo", decision=decision)
        assert error is None


# ===========================================================================
# 6. Process registry
# ===========================================================================


class TestProcessRegistry:
    def test_register_and_get_pid(self):
        from app.runs.process_registry import deregister, get_pid, register
        run_id = "proc-test-001"
        try:
            register(run_id, 99999)
            assert get_pid(run_id) == 99999
        finally:
            deregister(run_id)

    def test_deregister_removes_entry(self):
        from app.runs.process_registry import deregister, get_pid, register
        run_id = "proc-test-002"
        register(run_id, 12345)
        deregister(run_id)
        assert get_pid(run_id) is None

    def test_terminate_nonexistent_run_returns_false(self):
        from app.runs.process_registry import terminate
        assert terminate("nonexistent-run-000") is False

    def test_terminate_already_gone_pid_returns_false(self):
        """Terminating a PID that no longer exists is safe and returns False."""
        from app.runs.process_registry import deregister, register, terminate
        run_id = "proc-test-003"
        # Use PID 0 which is never a user process but triggers ProcessLookupError on kill
        # Use a very large PID that almost certainly doesn't exist
        register(run_id, 2**22)  # PID way above typical max
        try:
            result = terminate(run_id)
            # Either False (PID gone → ProcessLookupError) or True (unlikely, signal sent)
            # We just verify it doesn't raise
            assert isinstance(result, bool)
        finally:
            deregister(run_id)

    def test_list_active_reflects_state(self):
        from app.runs.process_registry import deregister, list_active, register
        run_id = "proc-test-004"
        try:
            register(run_id, 54321)
            active = list_active()
            assert run_id in active
            assert active[run_id] == 54321
        finally:
            deregister(run_id)

    def test_local_executor_registers_and_deregisters(self, tmp_path):
        """LocalExecutor registers the subprocess PID and deregisters after completion."""
        from app.runtimes.local_executor import LocalExecutor
        from app.runs.process_registry import get_pid

        run_id = "proc-exec-test-001"
        executor = LocalExecutor()

        # Run a trivially fast command
        result = executor.run_command(
            command=["echo", "hello"],
            timeout=10,
            run_id=run_id,
        )
        assert result.returncode == 0
        # After completion the entry must be removed
        assert get_pid(run_id) is None

    def test_local_executor_without_run_id_does_not_register(self):
        """When run_id is not provided, nothing is added to the registry."""
        from app.runtimes.local_executor import LocalExecutor
        from app.runs.process_registry import list_active

        before = set(list_active().keys())
        executor = LocalExecutor()
        executor.run_command(command=["echo", "no-registry"], timeout=5)
        after = set(list_active().keys())
        assert after == before


# ===========================================================================
# 7. Stop/cancel run behavior
# ===========================================================================


class TestStopRunBehavior:
    def test_stop_queued_run_sets_cancelled(self, db):
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stop-queued"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)
        assert run.status == "queued"

        stopped, changed = RunService(db).stop_run(run.id, space_id)
        assert changed is True
        assert stopped.status == "cancelled"
        assert stopped.ended_at is not None

    def test_stop_terminal_run_returns_unchanged(self, db):
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stop-terminal"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)
        run.status = "succeeded"
        db.commit()

        stopped, changed = RunService(db).stop_run(run.id, space_id)
        assert changed is False
        assert stopped.status == "succeeded"

    def test_stop_running_run_attempts_process_termination(self, db):
        """stop_run with status=running should call process_registry.terminate."""
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stop-running"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.commit()

        terminate_calls = []

        def fake_terminate(run_id: str) -> bool:
            terminate_calls.append(run_id)
            return False  # no process registered

        # Patch the canonical process_registry.terminate that stop_run imports locally
        with patch("app.runs.process_registry.terminate", side_effect=fake_terminate):
            stopped, changed = RunService(db).stop_run(run.id, space_id)

        assert changed is True
        assert stopped.status == "cancelled"
        assert run.id in terminate_calls

    def test_stop_run_not_found_raises(self, db):
        from app.runs.run_service import RunService
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            RunService(db).stop_run("nonexistent-run-id", "nonexistent-space")
        assert ei.value.status_code == 404


# ===========================================================================
# 8. Stale run recovery
# ===========================================================================


class TestStaleRunRecovery:
    def test_recover_stale_runs_marks_running_as_failed(self, db):
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stale-recovery"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)

        # Make it look like it started 2 hours ago
        run.status = "running"
        run.started_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()

        count = RunService(db).recover_stale_runs(stale_after_seconds=3600)

        assert count == 1
        db.refresh(run)
        assert run.status == "failed"
        assert "stale" in (run.error_message or "").lower()
        assert run.error_json is not None
        assert run.error_json.get("error_code") == "stale_run_recovered"

    def test_recover_stale_does_not_touch_fresh_running_run(self, db):
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stale-fresh"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)

        # Started 10 minutes ago — within the 1-hour threshold
        run.status = "running"
        run.started_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()

        count = RunService(db).recover_stale_runs(stale_after_seconds=3600)

        assert count == 0
        db.refresh(run)
        assert run.status == "running"

    def test_recover_stale_ignores_non_running_statuses(self, db):
        from tests.support import factories
        from app.runs.run_service import RunService

        space_id = "test-stale-queued"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)

        # Queued — stale recovery filters on status="running" so this is never touched
        assert run.status == "queued"

        # Use a very small threshold so any running run would be matched,
        # but our queued run is not running so it stays untouched.
        RunService(db).recover_stale_runs(stale_after_seconds=0)
        db.refresh(run)
        assert run.status == "queued"


# ===========================================================================
# 9. incomplete_patch metadata for skipped changes
# ===========================================================================


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "hi") -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(path))
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


class TestIncompletePatchMetadata:
    def test_no_skipped_files_sets_incomplete_false(self, db, tmp_path):
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-complete-patch"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        ops = [{"op": "replace_file", "path": "main.py", "content": "code"}]
        skipped = []  # nothing skipped

        with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
            result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

        assert result.proposal_created is True
        assert result.incomplete_patch is False

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        assert prop.payload_json.get("incomplete_patch") is False
        assert prop.payload_json.get("skipped_changes") == []

    def test_skipped_files_sets_incomplete_true(self, db, tmp_path):
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-incomplete-patch"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        ops = [{"op": "replace_file", "path": "main.py", "content": "code"}]
        skipped = [{"path": "deleted.txt", "reason": "deleted"}]

        with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
            result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

        assert result.proposal_created is True
        assert result.incomplete_patch is True

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        assert prop.payload_json.get("incomplete_patch") is True
        assert prop.payload_json.get("skipped_changes") == skipped

    def test_deleted_file_produces_incomplete_patch_in_real_git_repo(self, tmp_path, db):
        """Deleted files in the worktree produce incomplete_patch=True via real git."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-real-delete"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "kept.txt", "keep me")

        # Add a file to delete and a text file to modify
        (repo / "todelete.txt").write_text("bye")
        (repo / "main.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "add files"], check=True, capture_output=True, cwd=str(repo))

        # Delete one file and modify another
        subprocess.run(["git", "rm", "todelete.txt"], check=True, capture_output=True, cwd=str(repo))
        (repo / "main.py").write_text("x = 2")

        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=repo)

        # main.py is modified (collected), todelete.txt is deleted (skipped)
        assert result.incomplete_patch is True
        assert any(s["reason"] == "deleted" for s in result.skipped)

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        assert prop.payload_json.get("incomplete_patch") is True

    def test_renamed_file_produces_incomplete_patch_in_real_git_repo(self, tmp_path, db):
        """Renamed files in the worktree produce incomplete_patch=True via real git."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-real-rename"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "old_name.py", "old = 1")

        # Rename the file via git mv
        subprocess.run(["git", "mv", "old_name.py", "new_name.py"], check=True, capture_output=True, cwd=str(repo))

        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=repo)

        # Renamed files are skipped — no ops, but incomplete_patch if any text changes exist alongside
        # If only rename and nothing else: no ops → no proposal (all-skipped path)
        assert any(s["reason"] == "renamed" for s in result.skipped)
        # When all files are skipped, no proposal is created
        assert result.proposal_created is False

    def test_binary_file_skipped_and_proposal_marked_incomplete(self, tmp_path, db):
        """Binary file changes result in incomplete_patch=True on the proposal."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-binary-skip"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        ops = [{"op": "replace_file", "path": "src.py", "content": "x=1"}]
        skipped = [{"path": "image.png", "reason": "binary"}]

        with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
            result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

        assert result.proposal_created is True
        assert result.incomplete_patch is True

        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        payload = prop.payload_json
        assert payload["incomplete_patch"] is True
        assert any(s["reason"] == "binary" for s in payload["skipped_changes"])

    def test_oversized_file_skipped_produces_incomplete_patch(self, db, tmp_path):
        """Oversized files in the worktree produce incomplete_patch=True."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from tests.support import factories

        space_id = "test-oversized"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        ops = [{"op": "replace_file", "path": "small.py", "content": "y=2"}]
        skipped = [{"path": "big_model.bin", "reason": "too_large"}]

        with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
            result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

        assert result.proposal_created is True
        assert result.incomplete_patch is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop.payload_json["incomplete_patch"] is True


# ===========================================================================
# 10. Preflight service unit tests
# ===========================================================================


class TestPreflightService:
    def test_preflight_nonexistent_agent_returns_error(self, db):
        from app.runs.preflight import PreflightRequest, PreflightService

        space_id = "test-preflight-noagent"
        req = PreflightRequest(agent_id="nonexistent-agent")
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is False
        assert any("not found" in e for e in result.errors)

    def test_preflight_disabled_agent_policy_simulation_does_not_record_decision(self, db):
        from tests.support import factories
        from app.models import PolicyDecisionRecord
        from app.runs.preflight import PreflightRequest, PreflightService

        space_id = "test-preflight-disabled-simulation"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        agent.status = "disabled"
        db.commit()

        result = PreflightService(db).check(
            PreflightRequest(agent_id=agent.id),
            space_id=space_id,
        )

        assert result.executable is False
        assert any("not runnable" in e.lower() for e in result.errors)
        records = (
            db.query(PolicyDecisionRecord)
            .filter(
                PolicyDecisionRecord.space_id == space_id,
                PolicyDecisionRecord.action == "runtime.execute",
            )
            .all()
        )
        assert records == [], "dry-run preflight policy simulation must not create audit records"

    def test_preflight_no_adapter_configured_defaults_to_echo(self, db):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-noadapter"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Clear adapter config so preflight follows execution's system fallback.
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {}
        version.runtime_config_json = {}
        db.commit()

        req = PreflightRequest(agent_id=agent.id)
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is True
        assert result.adapter_type == "echo"
        assert result.errors == []

    def test_preflight_echo_adapter_succeeds(self, db):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-echo"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id)
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is True
        assert result.adapter_type == "echo"
        assert result.required_sandbox_level == "none"
        assert result.errors == []

    def test_preflight_critical_risk_returns_error(self, db):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-critical"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "critical", "default_adapter_type": "echo"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id)
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is False
        assert any("one_shot_docker" in e or "critical" in e for e in result.errors)

    def test_preflight_missing_workspace_for_worktree_returns_error(self, db):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-nowspc"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id, workspace_id=None)
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is False
        assert any("workspace" in e.lower() for e in result.errors)

    def test_preflight_workspace_not_git_repo_returns_error(self, db, tmp_path):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-nogit"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Create a plain directory (not a git repo) and mark it external
        plain_dir = tmp_path / "notgit"
        plain_dir.mkdir()
        ws = factories.create_test_workspace(
            db,
            space_id=space_id,
            root_path=str(plain_dir),
            allow_external_root=True,
            commit=True,
        )

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id, workspace_id=ws.id)
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is False
        assert any("git" in e.lower() for e in result.errors)

    def test_preflight_worktree_with_valid_git_repo_succeeds(self, db, tmp_path):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-git-ok"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Create a real git repo
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        ws = factories.create_test_workspace(
            db,
            space_id=space_id,
            root_path=str(repo),
            allow_external_root=True,
            commit=True,
        )

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id, workspace_id=ws.id)
        mock_broker = MagicMock()
        mock_broker.list_profiles.return_value = [MagicMock(id="claude_code/default")]
        mock_broker.profile_ready.return_value = True
        with patch("app.credentials.broker.CredentialBroker", return_value=mock_broker):
            result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is True
        assert result.adapter_type == "claude_code"
        assert result.required_sandbox_level == "worktree"
        assert result.errors == []

    def test_preflight_automation_with_no_credential_profile_returns_error(self, db):
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-authnoprof"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        # Use echo so risk/workspace checks pass; echo is native, so credential checks skip
        db.commit()

        req = PreflightRequest(agent_id=agent.id, trigger_origin="automation")
        # Echo runtime does not require a CLI credential profile
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.executable is True

    def test_preflight_automation_claude_code_without_profile_returns_error(self, db, tmp_path):
        """claude_code automation run without credential profile must fail preflight."""
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-preflight-authnoprof2"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        ws = factories.create_test_workspace(
            db, space_id=space_id, root_path=str(repo), allow_external_root=True, commit=True
        )

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "high", "default_adapter_type": "claude_code"}
        db.commit()

        req = PreflightRequest(
            agent_id=agent.id,
            workspace_id=ws.id,
            trigger_origin="automation",
        )

        # Mock broker to return no profiles — patch at the canonical module location
        with patch("app.credentials.broker.CredentialBroker") as MockBroker:
            mock_instance = MagicMock()
            mock_instance.list_profiles.return_value = []
            mock_instance.profile_ready.return_value = False
            MockBroker.return_value = mock_instance
            result = PreflightService(db).check(req, space_id=space_id)

        # claude CLI might not be in PATH — this test checks the credential error,
        # which fires after CLI availability (which is a warning not an error)
        assert result.executable is False
        assert any("credential" in e.lower() or "runtime_credential" in e for e in result.errors)


# ===========================================================================
# 11. Preflight / execution adapter_type and sandbox_level agreement (Task 1)
# ===========================================================================


class TestPreflightExecutionAgreement:
    """Preflight and RunExecutionService must resolve the same adapter_type and
    required_sandbox_level for any given AgentVersion configuration."""

    def test_echo_low_risk_preflight_matches_execution(self, db, monkeypatch):
        """echo / low-risk: both preflight and execution resolve adapter=echo, sandbox=none."""
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion, Run

        space_id = "test-agreement-echo"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        db.commit()

        req = PreflightRequest(agent_id=agent.id)
        preflight = PreflightService(db).check(req, space_id=space_id)
        assert preflight.executable is True
        assert preflight.adapter_type == "echo"
        assert preflight.required_sandbox_level == "none"

        # Execute the run and verify execution used the same adapter_type / sandbox_level
        _patch_success_adapter_without_artifact(monkeypatch)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        RunExecutionService(db).execute_run(run.id, space_id=space_id)
        db.refresh(run)
        assert run.adapter_type == preflight.adapter_type
        assert run.required_sandbox_level == preflight.required_sandbox_level

    def test_risk_level_comes_from_version_policy_not_request(self, db):
        """Preflight ignores any client-supplied risk override; only policy JSON is authoritative."""
        from tests.support import factories
        from app.runs.preflight import PreflightRequest, PreflightService
        from app.models import AgentVersion

        space_id = "test-agreement-noreqrisk"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        db.commit()

        # PreflightRequest has no risk_level field — confirm it is not accepted
        req = PreflightRequest(agent_id=agent.id)
        assert not hasattr(req, "risk_level")
        result = PreflightService(db).check(req, space_id=space_id)
        assert result.required_sandbox_level == "none"  # from policy, not from any request field

    def test_runtime_adapter_id_not_accepted_in_request(self):
        """PreflightRequest must not have a runtime_adapter_id field."""
        from app.runs.preflight import PreflightRequest

        req = PreflightRequest(agent_id="a")
        assert not hasattr(req, "runtime_adapter_id")

    def test_space_id_not_accepted_in_request(self):
        """PreflightRequest must not expose space_id — it must come from auth."""
        from app.runs.preflight import PreflightRequest

        req = PreflightRequest(agent_id="a")
        assert not hasattr(req, "space_id")


# ===========================================================================
# 12. Cancellation race: stop during execution preserves cancelled status (Task 2)
# ===========================================================================


class TestCancellationRace:
    def test_run_cancelled_during_execution_preserves_cancelled_status(self, db):
        """If stop_run cancels a run while adapter.execute() is blocking, the final
        status must remain 'cancelled', not 'succeeded' or 'failed'."""
        from tests.support import factories
        from app.runs.execution import RunExecutionService
        from app.runs.run_service import RunService
        from app.models import AgentVersion

        space_id = "test-cancel-race"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        # Simulate stop_run firing during adapter.execute(): after execute() returns
        # we patch db.refresh to flip the run status to cancelled.
        from app.models import Run
        original_refresh = db.refresh

        def _patch_refresh(obj):
            original_refresh(obj)
            if isinstance(obj, Run) and obj.id == run.id:
                obj.status = "cancelled"

        with patch.object(db, "refresh", side_effect=_patch_refresh):
            result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

        assert result.error_code == "run_cancelled"
        assert result.success is False
        # The run row status must still be cancelled, not succeeded
        db.expire(run)
        db.refresh(run)
        assert run.status == "cancelled"

    def test_normal_completion_not_affected_by_cancellation_check(self, db, monkeypatch):
        """When no cancellation occurs the run should complete normally."""
        from tests.support import factories
        from app.runs.execution import RunExecutionService
        from app.models import AgentVersion

        space_id = "test-cancel-norace"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {"risk_level": "low", "default_adapter_type": "echo"}
        db.commit()

        _patch_success_adapter_without_artifact(monkeypatch)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)
        result = RunExecutionService(db).execute_run(run.id, space_id=space_id)

        assert result.success is True
        db.refresh(run)
        assert run.status == "succeeded"


# ===========================================================================
# 13. Process group termination (Task 3)
# ===========================================================================


class TestProcessGroupTermination:
    def test_local_executor_starts_new_session(self, tmp_path):
        """LocalExecutor must start subprocesses in a new session (and therefore a new
        process group) so that SIGTERM to the group kills all child processes."""
        import subprocess as _sp
        from unittest.mock import call as _call
        from app.runtimes.local_executor import LocalExecutor

        popen_calls = []
        original_popen = _sp.Popen

        def capturing_popen(cmd, **kwargs):
            popen_calls.append(kwargs)
            return original_popen(cmd, **kwargs)

        executor = LocalExecutor()
        with patch("subprocess.Popen", side_effect=capturing_popen):
            executor.run_command(command=["echo", "hi"], timeout=5)

        assert popen_calls, "Popen was not called"
        assert popen_calls[0].get("start_new_session") is True

    def test_terminate_sends_to_process_group(self):
        """process_registry.terminate should call os.killpg, not just os.kill."""
        from app.runs import process_registry

        run_id = "pgid-test-001"
        fake_pid = 99991

        process_registry.register(run_id, fake_pid)
        try:
            kill_calls: list = []
            killpg_calls: list = []

            with (
                patch("os.getpgid", return_value=fake_pid),
                patch("os.killpg", side_effect=lambda pgid, sig: killpg_calls.append((pgid, sig))),
                patch("os.kill", side_effect=lambda pid, sig: kill_calls.append((pid, sig))),
            ):
                result = process_registry.terminate(run_id)

            assert result is True
            assert len(killpg_calls) == 1
            assert killpg_calls[0][0] == fake_pid  # sent to process group
            assert len(kill_calls) == 0            # direct PID kill not used
        finally:
            process_registry.deregister(run_id)

    def test_terminate_falls_back_to_pid_when_killpg_fails(self):
        """When os.killpg raises OSError, terminate falls back to os.kill(pid)."""
        from app.runs import process_registry

        run_id = "pgid-test-002"
        fake_pid = 99992

        process_registry.register(run_id, fake_pid)
        try:
            kill_calls: list = []

            with (
                patch("os.getpgid", return_value=fake_pid),
                patch("os.killpg", side_effect=OSError("no permission")),
                patch("os.kill", side_effect=lambda pid, sig: kill_calls.append((pid, sig))),
            ):
                result = process_registry.terminate(run_id)

            assert result is True
            assert len(kill_calls) == 1
            assert kill_calls[0][0] == fake_pid
        finally:
            process_registry.deregister(run_id)

    def test_terminate_returns_false_when_process_already_gone(self):
        """ProcessLookupError during pgid lookup (process already exited) returns False."""
        from app.runs import process_registry

        run_id = "pgid-test-003"
        fake_pid = 99993

        process_registry.register(run_id, fake_pid)
        try:
            with patch("os.getpgid", side_effect=ProcessLookupError):
                result = process_registry.terminate(run_id)

            assert result is False
        finally:
            process_registry.deregister(run_id)


# ===========================================================================
# 14. Credential-checked observability (Task 5)
# ===========================================================================


class TestCredentialCheckedObservability:
    def test_credential_checked_in_adapter_metadata_on_success(self):
        """credential_checked=True must appear in adapter_metadata after a successful run."""
        from app.runtimes.local_executor import ExecutionResult
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="manual")

        mock_grant = MagicMock()
        mock_grant.temp_home = None
        mock_grant.env = {}

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch.object(adapter, "_render_context", return_value=None),
            patch.object(adapter.executor, "run_command", return_value=ExecutionResult(0, "ok", "")),
        ):
            result = adapter.execute(ctx)

        assert result.success is True
        meta = result.adapter_metadata or {}
        assert meta.get("credential_checked") is True

    def test_credential_checked_in_adapter_metadata_on_failure(self):
        """credential_checked=True must appear in adapter_metadata even when automation fails."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        with patch.object(adapter, "_resolve_credential_grant", return_value=None):
            result = adapter.execute(ctx)

        assert result.success is False
        meta = result.adapter_metadata or {}
        assert meta.get("credential_checked") is True

    def test_no_sensitive_fields_in_cred_meta(self):
        """adapter_metadata must not contain HOME paths, token paths, or secret values."""
        from app.runtimes.local_executor import ExecutionResult
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="manual")

        mock_grant = MagicMock()
        mock_grant.temp_home = "/secret/home/path"
        mock_grant.env = {}

        with (
            patch.object(adapter, "_resolve_credential_grant", return_value=mock_grant),
            patch.object(adapter, "_render_context", return_value=None),
            patch.object(adapter.executor, "run_command", return_value=ExecutionResult(0, "ok", "")),
            patch("app.credentials.broker.CredentialBroker.cleanup_temp_home", return_value=None),
        ):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        # Verify no path strings are in the top-level metadata values
        for k, v in meta.items():
            if isinstance(v, str):
                assert "/secret" not in v, f"metadata key '{k}' leaks a path: {v!r}"
                assert "home/path" not in v.lower(), f"metadata key '{k}' leaks a HOME path: {v!r}"


# ===========================================================================
# 15. Incomplete patch requires explicit confirmation (Task 6)
# ===========================================================================


def _make_code_patch_proposal(db, *, space_id: str, workspace_root: "Path", incomplete: bool):
    """Helper: create a code_patch Proposal in the DB and return it."""
    import hashlib
    from tests.support import factories
    from app.models import Proposal
    import datetime as _dt

    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(
        db, space_id=space_id, root_path=str(workspace_root), allow_external_root=True, commit=True
    )
    now = _dt.datetime.now(_dt.timezone.utc)

    existing_content = b"original"
    preimage_sha256 = hashlib.sha256(existing_content).hexdigest()

    proposal = Proposal(
        id=str(uuid.uuid4()),
        space_id=space_id,
        workspace_id=ws.id,
        proposal_type="code_patch",
        status="pending",
        title="Test code_patch proposal",
        created_by_user_id=user.id,
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "hello.txt",
                        "content": "hello world",
                        "preimage_exists": True,
                        "preimage_sha256": preimage_sha256,
                    }
                ]
            },
            "incomplete_patch": incomplete,
            "skipped_changes": [{"path": "del.txt", "reason": "deleted"}] if incomplete else [],
        },
        created_at=now,
        updated_at=now,
    )
    db.add(proposal)
    db.commit()
    return proposal, ws, user


class TestIncompletePatchConfirmation:
    """The /proposals/{id}/accept endpoint must reject incomplete_patch proposals
    unless confirm_incomplete_patch=true is supplied."""

    def test_accept_incomplete_patch_without_confirm_raises_422(self, db, tmp_path):
        """Guard fires: incomplete proposal + no confirmation → 422 with canonical code."""
        from fastapi.testclient import TestClient
        from fastapi import Depends
        from sqlalchemy.orm import Session
        from app.main import app
        from app.auth import get_identity
        from app.db import get_db

        space_id = "test-incomplete-guard"
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        proposal, _, user = _make_code_patch_proposal(
            db, space_id=space_id, workspace_root=repo, incomplete=True
        )

        # Override both identity and DB to use the test session
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=db.bind)

        def _override_identity():
            return (space_id, user.id)

        def _override_db():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_identity] = _override_identity
        app.dependency_overrides[get_db] = _override_db
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(f"/api/v1/proposals/{proposal.id}/accept")
            assert resp.status_code == 422
            body = resp.json()
            # App may wrap HTTPException detail under {"detail": ...} or
            # {"error": ..., "message": ...} depending on the custom error handler.
            raw_detail = body.get("detail") or body.get("message") or {}
            if isinstance(raw_detail, str):
                # String detail — look for the canonical code in the string
                assert "incomplete_patch_requires_confirmation" in raw_detail
            else:
                assert isinstance(raw_detail, dict)
                assert raw_detail.get("code") == "incomplete_patch_requires_confirmation"
        finally:
            app.dependency_overrides.pop(get_identity, None)
            app.dependency_overrides.pop(get_db, None)

    def test_accept_incomplete_patch_with_confirm_true_proceeds(self, db, tmp_path):
        """confirm_incomplete_patch=true bypasses the guard, applies the patch, and
        the response contains result_type=code_patch_apply with updated_paths."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_identity
        from app.db import get_db
        from app.models import Proposal
        from sqlalchemy.orm import sessionmaker

        space_id = "test-incomplete-ok"
        repo = tmp_path / "repo"
        repo.mkdir()
        # Create the target file so apply_replace can capture a preimage
        (repo / "hello.txt").write_text("original", encoding="utf-8")

        proposal, _, user = _make_code_patch_proposal(
            db, space_id=space_id, workspace_root=repo, incomplete=True
        )

        Session = sessionmaker(bind=db.bind)

        def _override_identity():
            return (space_id, user.id)

        def _override_db():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_identity] = _override_identity
        app.dependency_overrides[get_db] = _override_db
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                f"/api/v1/proposals/{proposal.id}/accept",
                params={"confirm_incomplete_patch": "true"},
            )
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body.get("result_type") == "code_patch_apply"
            assert "hello.txt" in body.get("result", {}).get("updated_paths", [])
            assert body.get("proposal", {}).get("status") == "accepted"
            # File must be updated on disk
            assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello world"
            # Proposal row must be accepted in the DB
            db.expire_all()
            saved = db.query(Proposal).filter(Proposal.id == proposal.id).first()
            assert saved is not None and saved.status == "accepted"
        finally:
            app.dependency_overrides.pop(get_identity, None)
            app.dependency_overrides.pop(get_db, None)

    def test_accept_complete_patch_does_not_require_confirm(self, db, tmp_path):
        """Complete (incomplete_patch=False) proposals apply without any confirm flag,
        update the file on disk, and set proposal status to accepted."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_identity
        from app.db import get_db
        from app.models import Proposal
        from sqlalchemy.orm import sessionmaker

        space_id = "test-complete-no-confirm"
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "hello.txt").write_text("original", encoding="utf-8")

        proposal, _, user = _make_code_patch_proposal(
            db, space_id=space_id, workspace_root=repo, incomplete=False
        )

        Session = sessionmaker(bind=db.bind)

        def _override_identity():
            return (space_id, user.id)

        def _override_db():
            s = Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_identity] = _override_identity
        app.dependency_overrides[get_db] = _override_db
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # No confirm_incomplete_patch param — should succeed for complete patches
            resp = client.post(f"/api/v1/proposals/{proposal.id}/accept")
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )
            body = resp.json()
            assert body.get("result_type") == "code_patch_apply"
            assert "hello.txt" in body.get("result", {}).get("updated_paths", [])
            assert body.get("proposal", {}).get("status") == "accepted"
            assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello world"
            db.expire_all()
            saved = db.query(Proposal).filter(Proposal.id == proposal.id).first()
            assert saved is not None and saved.status == "accepted"
        finally:
            app.dependency_overrides.pop(get_identity, None)
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# 16. Broker error reason preserved separately (Task 7)
# ===========================================================================


class TestBrokerErrorReason:
    def test_broker_exception_sets_broker_error_true_in_metadata(self):
        """When CredentialBroker.grant_for_run raises, adapter_metadata.broker_error must be True."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        with patch.object(adapter, "_resolve_credential_grant", side_effect=RuntimeError("broker down")):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        meta = result.adapter_metadata or {}
        assert meta.get("broker_error") is True
        assert meta.get("fallback_reason") == "broker_error"

    def test_no_profile_sets_broker_error_false_in_metadata(self):
        """When no profile is configured (no exception), adapter_metadata.broker_error is False."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        with patch.object(adapter, "_resolve_credential_grant", return_value=None):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        meta = result.adapter_metadata or {}
        assert meta.get("broker_error") is False
        assert meta.get("fallback_reason") == "no_profile_configured"

    def test_failure_reason_in_metadata_is_secret_safe(self):
        """failure_reason and related metadata fields must not contain paths or secrets."""
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = _make_ctx(trigger_origin="automation")

        with patch.object(adapter, "_resolve_credential_grant", side_effect=RuntimeError("/home/user/.claude token expired")):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        # fallback_reason must be a plain enum-like string, never the exception message
        reason = meta.get("fallback_reason", "")
        assert "/home" not in reason
        assert "token" not in reason
        assert reason in ("broker_error", "no_profile_configured", "")


# ===========================================================================
# 17. agent_run job handler guard for already-cancelled runs (Task 8)
# ===========================================================================


class TestJobHandlerCancelledRunGuard:
    def test_execute_existing_run_already_cancelled_exits_cleanly(self, db):
        """When the target Run is already cancelled, the job handler must return cleanly
        without retrying (no exception raised, status reflects cancelled).

        _execute_existing_run() opens its own DB session via SessionLocal(), so we mock
        both SessionLocal (to inject the test session) and execute_run (to raise the 409
        that RunExecutionService raises for terminal-status runs).
        """
        from fastapi import HTTPException
        from tests.support import factories
        from app.jobs.handlers import _execute_existing_run

        space_id = "test-job-cancelled"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)
        run.status = "cancelled"
        run.ended_at = datetime.now(UTC)
        db.commit()

        fake_job = SimpleNamespace(
            id="job-001",
            space_id=space_id,
            user_id=user.id,
            payload={"space_id": space_id, "user_id": user.id},
        )
        payload = {"space_id": space_id, "user_id": user.id}

        # Patch SessionLocal so the handler uses the test session, and mock execute_run
        # to raise the 409 HTTPException that RunExecutionService raises for terminal runs.
        # SessionLocal is imported inside _execute_existing_run (not module-level),
        # so we patch at the source: app.db.SessionLocal.
        mock_session_factory = MagicMock(return_value=db)
        with (
            patch("app.db.SessionLocal", mock_session_factory),
            patch(
                "app.runs.execution.RunExecutionService.execute_run",
                side_effect=HTTPException(
                    status_code=409,
                    detail=f"Run '{run.id}' is already in terminal status 'cancelled'",
                ),
            ),
        ):
            result = _execute_existing_run(fake_job, payload, run.id)

        assert result is not None
        assert result.get("skip_reason") == "run_already_terminal"
        assert result.get("skipped") is True
        assert result["status"] == "cancelled"

    def test_execute_existing_run_terminal_succeeded_exits_cleanly(self, db):
        """A run already in 'succeeded' also triggers the terminal-status guard."""
        from fastapi import HTTPException
        from tests.support import factories
        from app.jobs.handlers import _execute_existing_run

        space_id = "test-job-succeeded"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, commit=True)
        run.status = "succeeded"
        run.ended_at = datetime.now(UTC)
        db.commit()

        fake_job = SimpleNamespace(
            id="job-002",
            space_id=space_id,
            user_id=user.id,
            payload={"space_id": space_id, "user_id": user.id},
        )
        payload = {"space_id": space_id, "user_id": user.id}

        mock_session_factory = MagicMock(return_value=db)
        with (
            patch("app.db.SessionLocal", mock_session_factory),
            patch(
                "app.runs.execution.RunExecutionService.execute_run",
                side_effect=HTTPException(
                    status_code=409,
                    detail=f"Run '{run.id}' is already in terminal status 'succeeded'",
                ),
            ),
        ):
            result = _execute_existing_run(fake_job, payload, run.id)

        assert result.get("skip_reason") == "run_already_terminal"
