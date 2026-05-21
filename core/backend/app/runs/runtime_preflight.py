"""Automation-origin runtime preflight checks.

Answers whether a given agent version + runtime adapter + workspace combination
is safe to run unattended before any sandbox is created or any subprocess is
launched.  Human-triggered (manual) runs bypass these checks and rely solely on
the standard per-step execution guards.

Fail conditions evaluated here:
  - No runtime adapter could be resolved (disabled or not registered)
  - risk_level=critical requires one_shot_docker which is not implemented
  - CLI adapter has no explicit credential profile (automation must not fall
    back to container-default credentials)
  - File-access adapter is missing workspace_id for automation
  - Workspace is not a trusted git repository (no HEAD commit)
  - Workspace is dirty and the policy does not set allow_dirty_workspace=true
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace_worktree import WorkspacePreflight


@dataclass
class PreflightResult:
    """Result of a runtime preflight check."""

    ok: bool
    """True when the run is cleared to proceed unattended."""

    error_code: str | None = None
    """Machine-readable error code when ``ok=False``."""

    error_message: str | None = None
    """Human-readable explanation when ``ok=False``."""


class RuntimePreflightService:
    """Checks whether a run is safe to proceed unattended.

    Call :meth:`check_automation_run` for automation-origin runs only.
    All parameters must be resolved before calling — the service makes
    no DB queries and spawns no subprocesses.
    """

    def check_automation_run(
        self,
        *,
        resolved_adapter_type: str | None,
        requires_file_access: bool,
        requires_cli_credential_profile: bool,
        risk_level: str,
        has_credential_profile: bool,
        workspace_id: str | None,
        workspace_preflight: "WorkspacePreflight | None",
        allow_dirty_workspace: bool = False,
    ) -> PreflightResult:
        """Return a :class:`PreflightResult` describing whether the run can proceed.

        Parameters
        ----------
        resolved_adapter_type:
            Adapter type string resolved from the agent version + policy, or
            None when no adapter could be resolved.
        requires_file_access:
            True when the adapter class has ``requires_file_access=True``
            (e.g. claude_code, codex_cli).
        requires_cli_credential_profile:
            True when the adapter authenticates via ``CredentialBroker`` CLI
            login-state grants (i.e. ``uses_cli_credentials=True`` on the
            adapter class).  When False, the credential-profile check is skipped
            — non-CLI adapters (echo, capability) authenticate via API keys and
            have no login state to verify here.
        risk_level:
            Policy risk level for the run (low / medium / high / critical).
        has_credential_profile:
            True when ``CredentialBroker.get_default_profile(runtime)`` returns
            a non-None result for the selected runtime.  Only evaluated when
            ``requires_cli_credential_profile=True``.
        workspace_id:
            The ``Run.workspace_id`` value, or None.
        workspace_preflight:
            Result of :func:`~.workspace_worktree.run_workspace_preflight`,
            or None when no workspace is configured.
        allow_dirty_workspace:
            When True, dirty workspaces are permitted for automation runs.
            Typically sourced from ``version.runtime_policy_json["allow_dirty_workspace"]``.
        """
        # 1. Adapter must be resolved.
        if not resolved_adapter_type:
            return PreflightResult(
                ok=False,
                error_code="automation_preflight_no_adapter",
                error_message=(
                    "No runtime adapter resolved for automation-origin run. "
                    "Configure default_adapter_type in runtime_policy_json."
                ),
            )

        # 2. risk_level=critical requires one_shot_docker (not yet implemented).
        if risk_level == "critical":
            return PreflightResult(
                ok=False,
                error_code="automation_preflight_critical_risk",
                error_message=(
                    "risk_level=critical requires one_shot_docker sandbox isolation "
                    "which is not implemented. Use risk_level=high for automation runs."
                ),
            )

        # 3. CLI adapters must have an explicit credential profile for automation.
        #    Automation-origin runs must not rely on container-default credentials
        #    (Option A fallback) because there is no human operator to re-authenticate.
        #    API-key-based adapters (echo, capability) are exempt — they authenticate
        #    via resolved_credentials and have no CLI login state.
        if requires_cli_credential_profile and not has_credential_profile:
            return PreflightResult(
                ok=False,
                error_code="automation_preflight_no_credential_profile",
                error_message=(
                    "Automation-origin runs require an explicit CLI credential profile. "
                    f"No credential profile found for adapter '{resolved_adapter_type}'. "
                    "Register a profile under AGENT_SPACE_HOME/secrets/cli-credentials/."
                ),
            )

        # 4. File-access adapters need a workspace_id for automation.
        #    Without a workspace, the agent has no stable location to read from or
        #    write to, and the resulting code_patch proposal would have no target.
        if requires_file_access and not workspace_id:
            return PreflightResult(
                ok=False,
                error_code="automation_preflight_no_workspace",
                error_message=(
                    f"Adapter '{resolved_adapter_type}' requires file access but the "
                    "automation run has no workspace_id. Set workspace_id on the run."
                ),
            )

        # 5 & 6. Workspace git repo validity + dirty status.
        if workspace_preflight is not None:
            if not workspace_preflight.base_commit_sha:
                return PreflightResult(
                    ok=False,
                    error_code="automation_preflight_workspace_not_git_repo",
                    error_message=(
                        "Automation-origin runs require a trusted git repository workspace. "
                        "The workspace has no HEAD commit — initialise and commit first."
                    ),
                )
            if workspace_preflight.is_dirty and not allow_dirty_workspace:
                dirty_preview = ", ".join(workspace_preflight.dirty_files[:5])
                more = (
                    f" and {len(workspace_preflight.dirty_files) - 5} more"
                    if len(workspace_preflight.dirty_files) > 5
                    else ""
                )
                return PreflightResult(
                    ok=False,
                    error_code="automation_preflight_dirty_workspace",
                    error_message=(
                        f"Workspace has {len(workspace_preflight.dirty_files)} uncommitted "
                        f"change(s): {dirty_preview}{more}. "
                        "Set allow_dirty_workspace=true in runtime_policy_json to permit "
                        "automation on dirty workspaces."
                    ),
                )

        return PreflightResult(ok=True)
