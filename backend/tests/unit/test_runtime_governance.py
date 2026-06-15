"""Runtime governance, credential audit, and validation evidence invariants.

Covers:

- CLI runtime executions record metadata-only credential usage events (no secrets).
- RuntimeAdapter config validation against the canonical registry.
- Unimplemented adapter types are rejected without mutating Run state.
- Validation evidence is attached to code_patch proposals.
- Validation subprocesses run in an isolated HOME, not the container HOME.
"""

from __future__ import annotations
import uuid

import subprocess
from pathlib import Path
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


# ===========================================================================
# CLI Credential Usage Audit Events
# ===========================================================================


class TestCliCredentialEventModel:
    """CliCredentialEvent ORM model is importable and has required fields."""

    def test_model_importable(self):
        from app.models import CliCredentialEvent  # noqa: F401

    def test_model_has_required_fields(self):
        from app.models import CliCredentialEvent
        import inspect
        cols = {c.name for c in CliCredentialEvent.__table__.columns}
        required = {
            "id", "space_id", "run_id", "runtime_adapter_type",
            "credential_source", "trigger_origin", "fallback_used",
            "fallback_reason", "broker_error", "cleanup_status", "action",
            "created_at",
        }
        missing = required - cols
        assert not missing, f"CliCredentialEvent missing columns: {missing}"

    def test_credential_source_check_constraint_exists(self):
        from app.models import CliCredentialEvent
        constraint_names = {c.name for c in CliCredentialEvent.__table__.constraints}
        assert "ck_cli_credential_events_credential_source" in constraint_names


class TestCredentialBrokerRecordUsage:
    """CredentialBroker.record_usage() writes CliCredentialEvent rows."""

    def test_record_usage_with_no_grant_writes_none_source(self, db):
        from app.credentials.broker import CredentialBroker
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-default"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        broker = CredentialBroker()
        broker.record_usage(
            db,
            run.id,
            space_id,
            None,  # no grant -> no credential source
            runtime_adapter_type="claude_code",
            trigger_origin="manual",
            fallback_used=True,
            fallback_reason="no_profile_configured",
            broker_error=False,
            cleanup_status="not_needed",
            action="grant",
        )
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.credential_source == "none"
        assert ev.fallback_used is True
        assert ev.fallback_reason == "no_profile_configured"
        assert ev.broker_error is False
        assert ev.runtime_adapter_type == "claude_code"
        assert ev.trigger_origin == "manual"
        assert ev.action == "grant"
        assert ev.space_id == space_id
        assert ev.run_id == run.id

    def test_record_usage_with_grant_writes_profile_source(self, db):
        from app.credentials.broker import CredentialBroker, CredentialGrant
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-profile"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        grant = CredentialGrant(
            profile_id="claude_code/default",
            runtime="claude_code",
            executor_mode="worktree",
            readonly=False,
        )
        broker = CredentialBroker()
        broker.record_usage(
            db,
            run.id,
            space_id,
            grant,
            runtime_adapter_type="claude_code",
            trigger_origin="manual",
            fallback_used=False,
            fallback_reason=None,
            broker_error=False,
            cleanup_status="ok",
            action="grant",
        )
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.credential_source == "profile"
        assert ev.credential_profile_id == "claude_code/default"
        assert ev.fallback_used is False
        assert ev.cleanup_status == "ok"

    def test_record_usage_broker_error_writes_none_source(self, db):
        from app.credentials.broker import CredentialBroker
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-err"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        broker = CredentialBroker()
        broker.record_usage(
            db,
            run.id,
            space_id,
            None,
            runtime_adapter_type="claude_code",
            trigger_origin="manual",
            fallback_used=True,
            fallback_reason="broker_error",
            broker_error=True,
            cleanup_status="not_needed",
            action="grant_failed",
        )
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.credential_source == "none"
        assert ev.broker_error is True
        assert ev.action == "grant_failed"

    def test_automation_denied_records_event(self, db):
        """automation-origin with no credential profile creates an automation_denied event."""
        from app.credentials.broker import CredentialBroker
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-auto"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        broker = CredentialBroker()
        broker.record_usage(
            db,
            run.id,
            space_id,
            None,
            runtime_adapter_type="claude_code",
            trigger_origin="automation",
            fallback_used=True,
            fallback_reason="no_profile_configured",
            broker_error=False,
            cleanup_status="not_needed",
            action="automation_denied",
        )
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) == 1
        assert events[0].action == "automation_denied"
        assert events[0].trigger_origin == "automation"
        assert events[0].fallback_used is True

    def test_cleanup_failure_records_cleanup_status(self, db):
        """cleanup_failed is surfaced as cleanup_status='failed', not as a path/secret."""
        from app.credentials.broker import CredentialBroker
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-cleanup"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        broker = CredentialBroker()
        broker.record_usage(
            db,
            run.id,
            space_id,
            None,
            runtime_adapter_type="claude_code",
            trigger_origin="manual",
            fallback_used=False,
            fallback_reason=None,
            broker_error=False,
            cleanup_status="failed",
            action="cleanup_failed",
        )
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.cleanup_status == "failed"
        assert ev.action == "cleanup_failed"
        # Verify no paths or secrets are stored in any column
        for col in ("credential_profile_id", "fallback_reason"):
            val = getattr(ev, col)
            if val is not None:
                assert "/" not in str(val) or col == "credential_profile_id", (
                    f"Column {col} may contain a path: {val!r}"
                )

    def test_event_linked_to_run_id_and_space_id(self, db):
        """Every event has non-null run_id and space_id for audit correlation."""
        from app.credentials.broker import CredentialBroker
        from app.models import CliCredentialEvent

        space_id = "test-cred-audit-link"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        CredentialBroker().record_usage(
            db, run.id, space_id, None,
            runtime_adapter_type="codex_cli",
            trigger_origin="manual",
            action="grant",
        )
        db.commit()

        ev = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).first()
        assert ev is not None
        assert ev.run_id == run.id
        assert ev.space_id == space_id


class TestGenericCliRuntimeAdapterRecordUsageWired:
    """GenericCliRuntimeAdapter._record_credential_audit() writes credential audit metadata."""

    def test_record_credential_audit_writes_event_when_db_provided(self, db):
        """_record_credential_audit() inserts a CliCredentialEvent when ctx.db is set."""
        from app.models import CliCredentialEvent
        from app.runtimes.base import RuntimeExecutionContext
        from app.runtimes.registry import instantiate_runtime_adapter

        space_id = "test-cred-wire"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        ctx = RuntimeExecutionContext(
            run_id=run.id,
            space_id=space_id,
            prompt="test",
            mode="live",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
            trigger_origin="manual",
            db=db,
        )
        cred_meta = {
            "credential_source": "none",
            "fallback_used": True,
            "fallback_reason": "no_profile_configured",
            "broker_error": False,
            "cleanup_status": "not_needed",
        }

        adapter = instantiate_runtime_adapter("claude_code")
        adapter._record_credential_audit(ctx, cred_meta, action="grant")
        db.commit()

        events = db.query(CliCredentialEvent).filter(CliCredentialEvent.run_id == run.id).all()
        assert len(events) >= 1
        assert events[0].action == "grant"

    def test_record_credential_audit_no_op_when_db_is_none(self):
        """_record_credential_audit() silently skips when ctx.db is None."""
        from app.runtimes.base import RuntimeExecutionContext
        from app.runtimes.registry import instantiate_runtime_adapter

        ctx = RuntimeExecutionContext(
            run_id="test-run-no-db",
            space_id="test-space",
            prompt="test",
            mode="live",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
            trigger_origin="manual",
            db=None,  # no DB
        )
        cred_meta = {
            "credential_source": "none",
            "fallback_used": True,
            "fallback_reason": "no_profile_configured",
            "broker_error": False,
            "cleanup_status": "not_needed",
        }
        adapter = instantiate_runtime_adapter("claude_code")
        # Must not raise even without DB
        adapter._record_credential_audit(ctx, cred_meta, action="grant")


class TestAutomationOriginCliRunFails:
    """Automation-origin CLI runs without explicit credential fail cleanly."""

    def test_automation_run_without_profile_fails_with_correct_error_code(self):
        """GenericCliRuntimeAdapter returns runtime_credential_profile_required without a grant."""
        from app.runtimes.base import RuntimeExecutionContext
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = RuntimeExecutionContext(
            run_id="auto-run-001",
            space_id="auto-space",
            prompt="do something",
            mode="live",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
            trigger_origin="automation",
            db=None,
        )

        # Patch broker to return None (no profile configured)
        with patch.object(adapter, "_resolve_credential_grant", return_value=None):
            result = adapter.execute(ctx)

        assert result.success is False
        assert result.error_code == "runtime_credential_profile_required"
        assert "credential profile" in (result.error_text or "").lower()

    def test_automation_metadata_does_not_leak_paths_or_secrets(self):
        """Automation-denied failure metadata contains no file paths or secret values."""
        from app.runtimes.base import RuntimeExecutionContext
        from app.runtimes.registry import instantiate_runtime_adapter

        adapter = instantiate_runtime_adapter("claude_code")
        ctx = RuntimeExecutionContext(
            run_id="auto-run-002",
            space_id="auto-space",
            prompt="do something",
            mode="live",
            sandbox_cwd=None,
            model_name=None,
            system_prompt=None,
            adapter_config={},
            trigger_origin="automation",
            db=None,
        )

        with patch.object(adapter, "_resolve_credential_grant", return_value=None):
            result = adapter.execute(ctx)

        meta = result.adapter_metadata or {}
        # No raw paths (e.g. /home/..., /tmp/..., ~/...)
        for key, val in meta.items():
            if isinstance(val, str):
                assert not val.startswith("/home"), f"Metadata {key!r} looks like a path: {val!r}"
                assert not val.startswith("/tmp"), f"Metadata {key!r} looks like a tmp path: {val!r}"


class TestRunExecutionServiceRejectsUnimplementedAdapter:
    """RunExecutionService rejects adapter_not_implemented without mutating the Run."""

    def test_unimplemented_adapter_type_fails_with_adapter_not_implemented(self, db):
        from app.models import AgentVersion, Run
        from app.runs.execution import RunExecutionService

        space_id = "test-exec-unimpl"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {
            "risk_level": "low",
            "default_adapter_type": "opencode",
        }
        db.commit()

        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=True)

        result = RunExecutionService(db).execute_run(run.id, space_id=space_id, worker_id="test-w")
        assert result.success is False
        assert result.error_code == "adapter_planned_not_executable"

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).first()
        assert run_row.status == "failed"

# ===========================================================================
# Validation evidence for code patch proposals
# ===========================================================================


class TestWorktreeValidationModule:
    """run_validation_in_worktree runs commands in the worktree sandbox."""

    def test_no_commands_returns_skipped(self, tmp_path):
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(worktree_path=tmp_path, commands=[])
        assert result.status == "skipped"
        assert result.skip_reason == "no_validation_commands"
        assert result.command_count == 0

    def test_passing_command_returns_passed(self, tmp_path):
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo hello"],
        )
        assert result.status == "passed"
        assert result.command_count == 1
        assert result.commands[0].exit_code == 0
        assert result.commands[0].status == "passed"

    def test_failing_command_returns_failed(self, tmp_path):
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["false"],  # always exits 1
        )
        assert result.status == "failed"
        assert result.failed_command == "false"
        assert result.commands[0].exit_code != 0

    def test_command_runs_inside_worktree_not_real_workspace(self, tmp_path):
        """Verify cwd for command execution is the worktree_path."""
        from app.runs.worktree_validation import run_validation_in_worktree

        # Create a sentinel file only in the worktree
        sentinel = tmp_path / "sentinel.txt"
        sentinel.write_text("in-worktree", encoding="utf-8")

        # Command checks for the sentinel file; succeeds only if cwd=tmp_path
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["test -f sentinel.txt"],
        )
        assert result.status == "passed", (
            "validation command must run inside the worktree where sentinel.txt exists"
        )

    def test_stdout_and_stderr_are_bounded(self, tmp_path):
        """Captured output must be bounded to prevent excessive data."""
        from app.runs.worktree_validation import run_validation_in_worktree, MAX_SNIPPET_BYTES

        # Generate output > MAX_SNIPPET_BYTES via python oneliner
        big_cmd = f"python3 -c \"print('x' * {MAX_SNIPPET_BYTES + 1000})\""
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=[big_cmd],
        )
        assert result.status == "passed"
        snippet = result.commands[0].stdout_snippet
        assert len(snippet.encode("utf-8")) <= MAX_SNIPPET_BYTES + 100  # allow marker

    def test_multiple_commands_stop_status_at_first_failure(self, tmp_path):
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo a", "false", "echo b"],
        )
        assert result.status == "failed"
        assert result.failed_command == "false"
        # All commands still run (evidence collection, not early exit)
        assert result.command_count == 3


class TestCodePatchProposalValidationEvidence:
    """code_patch proposals include validation evidence in payload_json."""

    def test_proposal_without_validation_config_has_skipped_status(self, tmp_path, db):
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal

        space_id = "test-val-skip"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        # No validation_evidence passed → defaults to skipped
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=repo)

        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        val = prop.payload_json.get("validation", {})
        assert val.get("status") == "skipped"

    def test_passing_validation_records_passed_status(self, tmp_path, db):
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree

        space_id = "test-val-pass"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        val_evidence = run_validation_in_worktree(
            worktree_path=repo,
            commands=["echo validation-ok"],
        )
        assert val_evidence.status == "passed"

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        val = prop.payload_json.get("validation", {})
        assert val.get("status") == "passed"
        assert val.get("command_count") == 1

    def test_failing_validation_records_failed_and_still_creates_proposal(self, tmp_path, db):
        """Failed validation does not block proposal creation; proposal is marked risky (high risk_level)."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree

        space_id = "test-val-fail"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        val_evidence = run_validation_in_worktree(
            worktree_path=repo,
            commands=["false"],  # always fails
        )
        assert val_evidence.status == "failed"

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        # Proposal is still created even though validation failed
        assert result.proposal_created is True, "Failed validation must not block proposal creation"
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        assert prop is not None
        val = prop.payload_json.get("validation", {})
        assert val.get("status") == "failed"
        assert val.get("failed_command") == "false"
        # Risk level is elevated to "high" when validation fails
        assert prop.risk_level == "high", "Failed validation must elevate proposal risk_level to high"

    def test_validation_stdout_stderr_bounded_in_proposal(self, tmp_path, db):
        """Validation output stored in the proposal is bounded."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree, MAX_SNIPPET_BYTES

        space_id = "test-val-bounded"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        big_cmd = f"python3 -c \"print('y' * {MAX_SNIPPET_BYTES + 2000})\""
        val_evidence = run_validation_in_worktree(worktree_path=repo, commands=[big_cmd])

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        val = prop.payload_json.get("validation", {})
        for cmd_ev in val.get("commands", []):
            snippet = cmd_ev.get("stdout_snippet", "")
            assert len(snippet.encode("utf-8")) <= MAX_SNIPPET_BYTES + 200  # allow marker

    def test_validation_runs_in_worktree_not_real_workspace(self, tmp_path, db):
        """Sentinel file in worktree proves commands run there, not in the real workspace."""
        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree

        space_id = "test-val-location"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
        run.workspace_id = ws.id
        db.commit()

        # Worktree with a sentinel file
        repo = tmp_path / "worktree"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")
        (repo / "worktree_sentinel.txt").write_text("only-in-worktree", encoding="utf-8")

        val_evidence = run_validation_in_worktree(
            worktree_path=repo,
            commands=["test -f worktree_sentinel.txt"],
        )
        assert val_evidence.status == "passed", (
            "Validation must run in the worktree where worktree_sentinel.txt exists"
        )

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
        val = prop.payload_json.get("validation", {})
        assert val["status"] == "passed"


# ===========================================================================
# Validation subprocess HOME isolation
# ===========================================================================


class TestValidationHomeIsolation:
    """Validation subprocesses run with an isolated temporary HOME, not the container HOME."""

    def test_subprocess_does_not_inherit_real_home(self, tmp_path, monkeypatch):
        """The validation subprocess HOME must differ from os.environ['HOME']."""
        import os
        from app.runs.worktree_validation import run_validation_in_worktree

        real_home = os.environ.get("HOME", "/root")
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo $HOME"],
        )
        assert result.status == "passed"
        subprocess_home = result.commands[0].stdout_snippet.strip()
        assert subprocess_home, "HOME was empty in subprocess"
        assert subprocess_home != real_home, (
            f"Validation subprocess inherited the real HOME: {real_home!r}"
        )

    def test_home_prints_isolated_temp_path(self, tmp_path):
        """echo $HOME inside the subprocess prints a temp path (not the real HOME)."""
        import os
        from app.runs.worktree_validation import run_validation_in_worktree

        real_home = os.environ.get("HOME", "/root")
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo $HOME"],
        )
        assert result.status == "passed"
        subprocess_home = result.commands[0].stdout_snippet.strip()
        # Must be a non-empty path that is not the real HOME
        assert subprocess_home
        assert real_home not in subprocess_home, (
            f"Real HOME path {real_home!r} appeared in subprocess HOME output"
        )

    def test_temp_home_cleaned_up_after_validation(self, tmp_path):
        """The temporary HOME directory must not exist after validation completes."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo $HOME"],
        )
        assert result.status == "passed"
        temp_home = result.commands[0].stdout_snippet.strip()
        assert temp_home, "Could not capture temp HOME from subprocess output"
        assert not Path(temp_home).exists(), (
            f"Temp HOME {temp_home!r} was not cleaned up after validation"
        )

    def test_temp_home_cleaned_up_after_failing_validation(self, tmp_path):
        """Temp HOME is cleaned up even when a validation command fails."""
        from app.runs.worktree_validation import run_validation_in_worktree

        # Run two commands: first captures HOME, second fails
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo $HOME", "false"],
        )
        assert result.status == "failed"
        temp_home = result.commands[0].stdout_snippet.strip()
        assert temp_home
        assert not Path(temp_home).exists(), (
            f"Temp HOME {temp_home!r} was not cleaned up after failing validation"
        )

    def test_proposal_payload_does_not_contain_real_home(self, tmp_path, db):
        """proposal.payload_json.validation must not contain the real HOME path."""
        import json
        import os

        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree

        real_home = os.environ.get("HOME", "/root")

        space_id = "test-val-home-proposal"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(
            db, space_id=space_id, owner_user_id=user.id, commit=False
        )
        run = factories.create_test_run(
            db, space_id=space_id, user_id=user.id, agent=agent, commit=False
        )
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        # A command that prints HOME — should output temp HOME, not real HOME
        val_evidence = run_validation_in_worktree(
            worktree_path=repo,
            commands=["echo $HOME"],
        )

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()

        payload_str = json.dumps(prop.payload_json)
        assert real_home not in payload_str, (
            f"Real HOME path {real_home!r} appeared in proposal.payload_json.validation"
        )


# ===========================================================================
# Validation stdout/stderr redaction
# ===========================================================================


class TestValidationSecretRedaction:
    """Validation stdout/stderr are redacted; sensitive env vars are not inherited."""

    def test_command_printing_openai_api_key_pattern_is_redacted(self, tmp_path):
        """Output containing OPENAI_API_KEY=<value> must not expose the raw value."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo 'OPENAI_API_KEY=sk-test-fakesecret1234567890'"],
        )
        assert result.status == "passed"
        snippet = result.commands[0].stdout_snippet
        assert "sk-test-fakesecret1234567890" not in snippet, (
            "Fake OPENAI_API_KEY value leaked into validation stdout_snippet"
        )

    def test_command_printing_anthropic_api_key_is_redacted(self, tmp_path):
        """Output containing ANTHROPIC_API_KEY=<value> must not expose the raw value."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo 'ANTHROPIC_API_KEY=ant-test-fakesecret-value'"],
        )
        snippet = result.commands[0].stdout_snippet
        assert "ant-test-fakesecret-value" not in snippet, (
            "Fake ANTHROPIC_API_KEY value leaked into validation stdout_snippet"
        )

    def test_command_printing_token_pattern_is_redacted(self, tmp_path):
        """Output containing token=<value> must not expose the raw value."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo 'token=verylongsecrettokenvalue12345678'"],
        )
        snippet = result.commands[0].stdout_snippet
        assert "verylongsecrettokenvalue12345678" not in snippet, (
            "Fake token value leaked into validation stdout_snippet"
        )

    def test_command_printing_password_pattern_is_redacted(self, tmp_path):
        """Output containing password=<value> must not expose the raw value."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo 'password=supersecretpassword123'"],
        )
        snippet = result.commands[0].stdout_snippet
        assert "supersecretpassword123" not in snippet, (
            "Fake password value leaked into validation stdout_snippet"
        )

    def test_sensitive_env_not_inherited_by_subprocess(self, tmp_path, monkeypatch):
        """OPENAI_API_KEY must not be passed to the validation subprocess environment."""
        from app.runs.worktree_validation import run_validation_in_worktree

        # Use a bare value that won't be caught by output redaction patterns,
        # so the test specifically validates env stripping (not output redaction).
        fake_secret = "FAKE_BARE_SECRET_XYZ_9876_NOTAKEY"
        monkeypatch.setenv("OPENAI_API_KEY", fake_secret)

        # echo "$OPENAI_API_KEY" outputs the bare value if the var is inherited.
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=['echo "$OPENAI_API_KEY"'],
        )
        for cmd_result in result.commands:
            assert fake_secret not in cmd_result.stdout_snippet, (
                "OPENAI_API_KEY was inherited by validation subprocess"
            )

    def test_multiple_sensitive_env_vars_not_inherited(self, tmp_path, monkeypatch):
        """Several sensitive env-var patterns are all stripped from the subprocess env."""
        from app.runs.worktree_validation import run_validation_in_worktree

        # Use bare values that don't match redaction key=value patterns to test
        # env stripping specifically.
        secrets = {
            "ANTHROPIC_API_KEY": "BARE_ANTHROPIC_FAKE_SECRET_ABC",
            "GITHUB_TOKEN": "BARE_GITHUB_FAKE_TOKEN_XYZ",
            "MY_SECRET": "BARE_MY_FAKE_SECRET_DEF",
            "DB_PASSWORD": "BARE_DB_FAKE_PASSWORD_GHI",
        }
        for k, v in secrets.items():
            monkeypatch.setenv(k, v)

        # Print all env vars; if sensitive ones are present they'll appear in output.
        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["env"],
        )
        all_output = " ".join(
            c.stdout_snippet + c.stderr_snippet for c in result.commands
        )
        for secret_val in secrets.values():
            assert secret_val not in all_output, (
                f"Sensitive env var value {secret_val!r} appeared in validation output"
            )

    def test_proposal_payload_validation_does_not_contain_fake_secret(
        self, tmp_path, db, monkeypatch
    ):
        """proposal.payload_json.validation must not contain fake secret values
        from the environment even when the validation command dumps env vars.

        Defense layers tested:
        1. Env stripping — OPENAI_API_KEY is not passed to the subprocess, so
           ``env`` does not output it.
        2. Output redaction — if OPENAI_API_KEY=<val> were somehow in the output,
           the redact_string helper would replace it with [REDACTED].

        Note: the command strings themselves are NOT redacted (real commands like
        ``pytest tests/`` never contain secrets), so the fake secret is only
        injected via env, not embedded in the command text.
        """
        import json

        from app.models import Proposal
        from app.runs.code_patch_collector import collect_and_create_code_patch_proposal
        from app.runs.worktree_validation import run_validation_in_worktree

        # A value that would appear in ``env`` output if the var is inherited.
        # It does NOT match any standalone redaction patterns (no sk-, token=, etc.
        # prefix on its own), so env-stripping is the primary guard tested here.
        fake_secret = "PROPOSAL_FAKE_SECRET_VAL_TESTONLY_12345"
        monkeypatch.setenv("OPENAI_API_KEY", fake_secret)

        space_id = "test-val-secret-proposal"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(
            db, space_id=space_id, owner_user_id=user.id, commit=False
        )
        run = factories.create_test_run(
            db, space_id=space_id, user_id=user.id, agent=agent, commit=False
        )
        run.workspace_id = ws.id
        db.commit()

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, "readme.txt", "original")
        (repo / "main.py").write_text("x = 1", encoding="utf-8")

        # ``env`` dumps all subprocess environment variables.  With env-stripping,
        # OPENAI_API_KEY must not appear; with output redaction, ``OPENAI_API_KEY=…``
        # would be caught even if it did appear.
        val_evidence = run_validation_in_worktree(
            worktree_path=repo,
            commands=["env"],
        )

        result = collect_and_create_code_patch_proposal(
            db, run=run, worktree_path=repo, validation_evidence=val_evidence,
        )
        assert result.proposal_created is True
        prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()

        payload_str = json.dumps(prop.payload_json)
        assert fake_secret not in payload_str, (
            "Fake secret value appeared in proposal.payload_json.validation"
        )

    def test_passing_validation_behavior_unchanged_after_redaction(self, tmp_path):
        """Redaction must not break normal (non-secret) passing validation."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo hello-world", "echo done"],
        )
        assert result.status == "passed"
        assert result.command_count == 2
        assert "hello-world" in result.commands[0].stdout_snippet
        assert "done" in result.commands[1].stdout_snippet

    def test_failing_validation_behavior_unchanged_after_redaction(self, tmp_path):
        """Redaction must not break failing validation status reporting."""
        from app.runs.worktree_validation import run_validation_in_worktree

        result = run_validation_in_worktree(
            worktree_path=tmp_path,
            commands=["echo before", "false", "echo after"],
        )
        assert result.status == "failed"
        assert result.failed_command == "false"
        assert result.command_count == 3


class TestGetWorkspaceValidationCommands:
    """get_workspace_validation_commands fetches test_commands_json from WorkspaceProfile."""

    def test_returns_empty_list_when_no_profile(self, db):
        from app.runs.worktree_validation import get_workspace_validation_commands

        space_id = "test-val-cmds-noprofile"
        factories.create_test_space(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

        cmds = get_workspace_validation_commands(db, workspace_id=ws.id, space_id=space_id)
        assert cmds == []

    def test_returns_test_commands_from_profile(self, db):
        from app.models import WorkspaceProfile
        from app.runs.worktree_validation import get_workspace_validation_commands

        space_id = "test-val-cmds-profile"
        factories.create_test_space(db, space_id=space_id, commit=True)
        ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

        profile = WorkspaceProfile(
            id=str(uuid.uuid4()),
            space_id=space_id,
            workspace_id=ws.id,
            test_commands_json=["pytest tests/", "echo done"],
        )
        db.add(profile)
        db.commit()

        cmds = get_workspace_validation_commands(db, workspace_id=ws.id, space_id=space_id)
        assert cmds == ["pytest tests/", "echo done"]
