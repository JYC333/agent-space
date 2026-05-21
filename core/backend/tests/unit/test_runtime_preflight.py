"""Unit tests for RuntimePreflightService (automation-origin preflight).

Invariants verified:
  1.  ok=True when all conditions are satisfied (CLI adapter).
  2.  Fails with automation_preflight_no_adapter when adapter type is None.
  3.  Fails with automation_preflight_critical_risk when risk_level=critical.
  4.  Fails with automation_preflight_no_credential_profile when CLI adapter has no profile.
  5.  Non-CLI adapter (requires_cli_credential_profile=False) passes even without profile.
  6.  Fails with automation_preflight_no_workspace when file-access adapter lacks workspace_id.
  7.  Non-file-access adapter without workspace_id passes.
  8.  Fails with automation_preflight_workspace_not_git_repo when no HEAD commit.
  9.  Fails with automation_preflight_dirty_workspace when dirty and no allow flag.
  10. ok=True when dirty and allow_dirty_workspace=True.
  11. Error messages contain actionable context.

  parse_allow_dirty_workspace:
  12. Absent key → False.
  13. True bool → True.
  14. False bool → False.
  15. String "true" → raises ValueError with automation_preflight_invalid_runtime_policy.
  16. Misspelled key allow_dirty_workspce → absent/False (not accepted).
"""

from __future__ import annotations

import pytest

from app.runs.runtime_preflight import RuntimePreflightService, PreflightResult
from app.runs.workspace_worktree import WorkspacePreflight


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_preflight(commit_sha: str = "abc123def456" * 3 + "abcd") -> WorkspacePreflight:
    return WorkspacePreflight(
        base_commit_sha=commit_sha,
        is_dirty=False,
        dirty_files=[],
    )


def _dirty_preflight() -> WorkspacePreflight:
    return WorkspacePreflight(
        base_commit_sha="abc123",
        is_dirty=True,
        dirty_files=["src/main.py", "README.md"],
    )


def _no_commit_preflight() -> WorkspacePreflight:
    return WorkspacePreflight(
        base_commit_sha=None,
        is_dirty=False,
        dirty_files=[],
    )


SVC = RuntimePreflightService()


# ===========================================================================
# 1. All conditions satisfied (CLI adapter) → ok=True
# ===========================================================================


def test_all_conditions_satisfied_ok():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id="ws-123",
        workspace_preflight=_clean_preflight(),
        allow_dirty_workspace=False,
    )
    assert result.ok is True
    assert result.error_code is None


# ===========================================================================
# 2. No adapter resolved
# ===========================================================================


def test_no_adapter_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type=None,
        requires_file_access=False,
        requires_cli_credential_profile=False,
        risk_level="medium",
        has_credential_profile=False,
        workspace_id=None,
        workspace_preflight=None,
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_no_adapter"


# ===========================================================================
# 3. risk_level=critical
# ===========================================================================


def test_critical_risk_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="critical",
        has_credential_profile=True,
        workspace_id="ws-123",
        workspace_preflight=_clean_preflight(),
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_critical_risk"


# ===========================================================================
# 4. CLI adapter with no credential profile → fails
# ===========================================================================


def test_cli_adapter_no_credential_profile_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=False,
        workspace_id="ws-123",
        workspace_preflight=_clean_preflight(),
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_no_credential_profile"
    assert "claude_code" in result.error_message


# ===========================================================================
# 5. Non-CLI adapter with no credential profile → passes (check is skipped)
# ===========================================================================


def test_non_cli_adapter_no_credential_profile_ok():
    """echo / capability adapters use API keys, not CLI login state — no profile needed."""
    result = SVC.check_automation_run(
        resolved_adapter_type="echo",
        requires_file_access=False,
        requires_cli_credential_profile=False,   # ← API-key adapter
        risk_level="low",
        has_credential_profile=False,            # no CLI profile exists
        workspace_id=None,
        workspace_preflight=None,
    )
    assert result.ok is True


# ===========================================================================
# 6. File-access adapter without workspace_id
# ===========================================================================


def test_file_access_without_workspace_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id=None,
        workspace_preflight=None,
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_no_workspace"


# ===========================================================================
# 7. Non-file-access adapter without workspace_id passes
# ===========================================================================


def test_non_file_access_adapter_no_workspace_ok():
    result = SVC.check_automation_run(
        resolved_adapter_type="echo",
        requires_file_access=False,
        requires_cli_credential_profile=False,
        risk_level="low",
        has_credential_profile=False,
        workspace_id=None,
        workspace_preflight=None,
    )
    assert result.ok is True


# ===========================================================================
# 8. Workspace with no HEAD commit
# ===========================================================================


def test_workspace_without_head_commit_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id="ws-123",
        workspace_preflight=_no_commit_preflight(),
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_workspace_not_git_repo"


# ===========================================================================
# 9. Dirty workspace without allow flag
# ===========================================================================


def test_dirty_workspace_without_allow_fails():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id="ws-123",
        workspace_preflight=_dirty_preflight(),
        allow_dirty_workspace=False,
    )
    assert result.ok is False
    assert result.error_code == "automation_preflight_dirty_workspace"
    assert "src/main.py" in result.error_message


# ===========================================================================
# 10. Dirty workspace WITH allow_dirty_workspace=True → ok
# ===========================================================================


def test_dirty_workspace_with_allow_ok():
    result = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id="ws-123",
        workspace_preflight=_dirty_preflight(),
        allow_dirty_workspace=True,
    )
    assert result.ok is True


# ===========================================================================
# 11. Error messages contain actionable context
# ===========================================================================


def test_error_messages_contain_useful_context():
    r_no_adapter = SVC.check_automation_run(
        resolved_adapter_type=None,
        requires_file_access=False,
        requires_cli_credential_profile=False,
        risk_level="low",
        has_credential_profile=False,
        workspace_id=None,
        workspace_preflight=None,
    )
    assert "default_adapter_type" in r_no_adapter.error_message

    r_dirty = SVC.check_automation_run(
        resolved_adapter_type="codex_cli",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=True,
        workspace_id="ws-abc",
        workspace_preflight=_dirty_preflight(),
        allow_dirty_workspace=False,
    )
    assert "src/main.py" in r_dirty.error_message
    assert "allow_dirty_workspace" in r_dirty.error_message

    r_no_cred = SVC.check_automation_run(
        resolved_adapter_type="claude_code",
        requires_file_access=True,
        requires_cli_credential_profile=True,
        risk_level="high",
        has_credential_profile=False,
        workspace_id="ws-abc",
        workspace_preflight=_clean_preflight(),
    )
    assert "claude_code" in r_no_cred.error_message


# ===========================================================================
# 12–16. parse_allow_dirty_workspace strict validation
# ===========================================================================

from app.runs.runtime_policy import parse_allow_dirty_workspace


def test_allow_dirty_workspace_absent_returns_false():
    assert parse_allow_dirty_workspace(None) is False
    assert parse_allow_dirty_workspace({}) is False
    assert parse_allow_dirty_workspace({"risk_level": "high"}) is False


def test_allow_dirty_workspace_true_bool_returns_true():
    assert parse_allow_dirty_workspace({"allow_dirty_workspace": True}) is True


def test_allow_dirty_workspace_false_bool_returns_false():
    assert parse_allow_dirty_workspace({"allow_dirty_workspace": False}) is False


def test_allow_dirty_workspace_string_raises():
    with pytest.raises(ValueError, match="automation_preflight_invalid_runtime_policy"):
        parse_allow_dirty_workspace({"allow_dirty_workspace": "true"})
    with pytest.raises(ValueError, match="automation_preflight_invalid_runtime_policy"):
        parse_allow_dirty_workspace({"allow_dirty_workspace": "false"})
    with pytest.raises(ValueError, match="automation_preflight_invalid_runtime_policy"):
        parse_allow_dirty_workspace({"allow_dirty_workspace": 1})


def test_allow_dirty_workspace_misspelled_key_behaves_as_absent():
    result = parse_allow_dirty_workspace({"allow_dirty_workspce": True})
    assert result is False
