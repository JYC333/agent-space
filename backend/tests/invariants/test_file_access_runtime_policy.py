"""Invariants for file-access runtime adapter policy enforcement.

These tests prove the hard policy rules that prevent file-access local CLI runtimes
from executing without proper sandbox isolation.  They are invariants — they
must hold across all code changes.

Invariants covered:
  1. claude_code and codex_cli require worktree sandbox (risk_level=high).
  2. medium/dry_run cannot execute a file-access CLI runtime — blocked pre-execution.
  3. high/worktree can execute a file-access CLI runtime — permitted.
  4. critical/one_shot_docker returns the explicit unsupported error, not silent fallback.
  5. No runtime silently falls back to the default adapter.
  6. failed git diff/status collection produces materialization_error, not silent no-op.
  7. "codex_cli" is canonical; "codex" alone does not instantiate a runtime adapter.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decision(risk_level: str):
    from app.runs.runtime_policy import RuntimePolicyDecision, required_sandbox_level_for_risk
    return RuntimePolicyDecision(
        required_sandbox_level=required_sandbox_level_for_risk(risk_level),
        risk_level=risk_level,
        policy_snapshot={},
    )


# ---------------------------------------------------------------------------
# 1. File-access runtimes require worktree (validate_file_access_adapter_policy)
# ---------------------------------------------------------------------------

class TestFileAccessAdapterRequiresWorktree:
    def test_claude_code_low_risk_blocked(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="claude_code",
            decision=_decision("low"),
        )
        assert msg is not None
        assert "worktree" in msg
        assert "claude_code" in msg

    def test_codex_cli_low_risk_blocked(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="codex_cli",
            decision=_decision("low"),
        )
        assert msg is not None
        assert "codex_cli" in msg

    def test_file_access_policy_derives_from_runtime_adapter_spec(self):
        from app.runtimes.specs import get_runtime_adapter_spec
        assert get_runtime_adapter_spec("claude_code").sandbox.requires_file_access is True
        assert get_runtime_adapter_spec("codex_cli").sandbox.requires_file_access is True
        assert get_runtime_adapter_spec("model_api").sandbox.requires_file_access is False

    def test_claude_code_high_risk_allowed(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="claude_code",
            decision=_decision("high"),
        )
        assert msg is None

    def test_codex_cli_high_risk_allowed(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="codex_cli",
            decision=_decision("high"),
        )
        assert msg is None


# ---------------------------------------------------------------------------
# 2. medium/dry_run cannot execute file-access adapters
# ---------------------------------------------------------------------------

class TestMediumRiskBlocksFileAccess:
    def test_claude_code_medium_risk_returns_policy_error(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="claude_code",
            decision=_decision("medium"),
        )
        assert msg is not None
        assert "dry_run" in msg or "worktree" in msg

    def test_codex_cli_medium_risk_returns_policy_error(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        msg = validate_file_access_adapter_policy(
            adapter_type="codex_cli",
            decision=_decision("medium"),
        )
        assert msg is not None


# ---------------------------------------------------------------------------
# 3. Non-file-access adapters are not blocked at lower risk levels
# ---------------------------------------------------------------------------

class TestNonFileAccessAdaptersNotBlocked:
    def test_model_api_low_risk_not_blocked(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        assert validate_file_access_adapter_policy(
            adapter_type="model_api", decision=_decision("low")
        ) is None

    def test_capability_low_risk_not_blocked(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        assert validate_file_access_adapter_policy(
            adapter_type="capability", decision=_decision("low")
        ) is None

    def test_model_api_medium_risk_not_blocked(self):
        from app.runs.runtime_policy import validate_file_access_adapter_policy
        assert validate_file_access_adapter_policy(
            adapter_type="model_api", decision=_decision("medium")
        ) is None


# ---------------------------------------------------------------------------
# 4. critical/one_shot_docker is explicit unsupported (RunExecutionService level)
#    Tested via policy mapping; actual HTTP test is in workflow tests.
# ---------------------------------------------------------------------------

class TestCriticalRiskMapsToOneShot:
    def test_critical_risk_maps_to_one_shot_docker(self):
        from app.runs.runtime_policy import required_sandbox_level_for_risk
        assert required_sandbox_level_for_risk("critical") == "one_shot_docker"

    def test_one_shot_docker_decision_is_correct_level(self):
        d = _decision("critical")
        assert d.required_sandbox_level == "one_shot_docker"
        assert d.risk_level == "critical"


# ---------------------------------------------------------------------------
# 5. No silent fallback to default adapter — registry raises on unknown adapter_type
# ---------------------------------------------------------------------------

class TestNoSilentFallbackToDefault:
    def test_unknown_adapter_type_raises_key_error(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        with pytest.raises(KeyError):
            instantiate_runtime_adapter("totally_unknown_adapter")

    def test_instantiate_capability_is_explicit(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        from app.runtimes.adapters.capability import CapabilityRuntimeAdapter
        adapter = instantiate_runtime_adapter("capability")
        assert isinstance(adapter, CapabilityRuntimeAdapter)

    def test_registry_is_not_exhausted_on_unknown(self):
        """is_adapter_type_implemented returns False, not True, for unknowns."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("unknown_fallback_type")
        assert not is_adapter_type_implemented("")
        assert not is_adapter_type_implemented("default_fallback")


# ---------------------------------------------------------------------------
# 6. Failed git diff/status collection is materialization error, not silent no-op
#    (structural test — execution.py catches GitCommandError and appends to
#    code_patch_warnings, which lands in output_json.materialization_errors)
# ---------------------------------------------------------------------------

class TestGitFailureBecomesError:
    def test_git_command_error_is_not_swallowed(self):
        """GitCommandError propagates out of collect_worktree_changes."""
        from unittest.mock import patch
        from pathlib import Path
        from app.runs.code_patch_collector import collect_worktree_changes, GitCommandError

        def _fail_git(args, cwd, timeout=30):
            raise GitCommandError("git diff HEAD failed (exit 128): not a git repository")

        with patch("app.runs.code_patch_collector._git", _fail_git):
            with pytest.raises(GitCommandError):
                collect_worktree_changes(Path("/tmp/fakepath"))

    def test_collect_and_create_raises_on_git_failure(self, tmp_path):
        """collect_and_create_code_patch_proposal raises GitCommandError (not silent)."""
        from unittest.mock import MagicMock, patch
        from app.runs.code_patch_collector import (
            collect_and_create_code_patch_proposal,
            GitCommandError,
        )

        mock_run = MagicMock()
        mock_run.id = "run-test-001"
        mock_run.space_id = "space-test"
        mock_run.workspace_id = "ws-test-001"
        mock_run.instructed_by_user_id = "user-test"
        mock_db = MagicMock()

        def _fail_git(args, cwd, timeout=30):
            raise GitCommandError("simulated git failure")

        with patch("app.runs.code_patch_collector._git", _fail_git):
            with pytest.raises(GitCommandError):
                collect_and_create_code_patch_proposal(
                    mock_db,
                    run=mock_run,
                    worktree_path=tmp_path,
                )


# ---------------------------------------------------------------------------
# 7. "codex_cli" is canonical; "codex" alone is not a runtime adapter
# ---------------------------------------------------------------------------

class TestCodexCliIsCanonical:
    def test_codex_cli_instantiates_successfully(self):
        from app.runtimes.registry import instantiate_runtime_adapter
        from app.runtimes.adapters.cli_runtime import GenericCliRuntimeAdapter
        adapter = instantiate_runtime_adapter("codex_cli")
        assert isinstance(adapter, GenericCliRuntimeAdapter)
        assert adapter.adapter_type == "codex_cli"

    def test_codex_alone_does_not_instantiate(self):
        """'codex' (without _cli) must not be a registered runtime adapter."""
        from app.runtimes.registry import instantiate_runtime_adapter
        with pytest.raises(KeyError):
            instantiate_runtime_adapter("codex")

    def test_codex_alone_not_in_registry(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert not is_adapter_type_implemented("codex")

    def test_codex_cli_spec_declares_file_access(self):
        """codex_cli is a file-access runtime (requires_file_access=True)."""
        from app.runtimes.specs import get_runtime_adapter_spec
        assert get_runtime_adapter_spec("codex_cli").sandbox.requires_file_access is True
