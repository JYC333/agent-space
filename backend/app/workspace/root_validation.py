"""Canonical validation of workspace execution roots.

Call :func:`validate_workspace_root_for_execution` before creating any sandbox
for a Run.  It enforces:

1. The workspace belongs to the run's space (cross-space isolation).
2. The resolved root path exists on disk.
3. The resolved root is a directory.
4. For worktree-level execution the root must be a git repository.
5. The resolved root is under ``settings.workspace_root`` unless the Workspace
   explicitly opts in via ``allow_external_root=True``.

Workspaces whose root resolves outside ``settings.workspace_root`` fail unless
``allow_external_root`` is set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class WorkspaceRootValidationError(Exception):
    """Raised when the workspace root fails a pre-execution check.

    The ``error_code`` attribute carries a machine-readable key for the run
    failure record.
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_workspace_root_for_execution(
    *,
    workspace_space_id: str,
    run_space_id: str,
    workspace_root: Path,
    allow_external_root: bool,
    sandbox_level: str,
) -> None:
    """Validate *workspace_root* before execution; raise :exc:`WorkspaceRootValidationError` on failure.

    Parameters
    ----------
    workspace_space_id:
        ``Workspace.space_id`` — must equal *run_space_id*.
    run_space_id:
        ``Run.space_id`` from the current execution context.
    workspace_root:
        Resolved absolute path for the workspace (from :func:`workspace_absolute_root`).
    allow_external_root:
        ``Workspace.allow_external_root`` — when ``False`` the root must be
        under ``settings.workspace_root``.
    sandbox_level:
        ``required_sandbox_level`` from the policy decision.  Worktree-level
        execution additionally requires the root to be a git repository.
    """
    from ..config import settings

    # 1. Cross-space isolation.
    if workspace_space_id != run_space_id:
        raise WorkspaceRootValidationError(
            "workspace_cross_space",
            f"Workspace belongs to space '{workspace_space_id}' but run is in space '{run_space_id}'",
        )

    # 2. Root must exist.
    if not workspace_root.exists():
        raise WorkspaceRootValidationError(
            "workspace_root_not_found",
            f"Workspace root does not exist on disk: {workspace_root}",
        )

    # 3. Root must be a directory.
    if not workspace_root.is_dir():
        raise WorkspaceRootValidationError(
            "workspace_root_not_directory",
            f"Workspace root is not a directory: {workspace_root}",
        )

    # 4. Root must be under settings.workspace_root unless opted-in.
    configured_root = Path(settings.workspace_root).resolve()
    try:
        workspace_root.relative_to(configured_root)
        _under_managed_root = True
    except ValueError:
        _under_managed_root = False

    if not _under_managed_root and not allow_external_root:
        raise WorkspaceRootValidationError(
            "workspace_root_untrusted_external",
            f"Workspace root '{workspace_root}' is outside the managed workspace root "
            f"'{configured_root}'. Set Workspace.allow_external_root=True to permit "
            "trusted external root access.",
        )

    # 5. Worktree sandbox requires a git repository.
    if sandbox_level == "worktree":
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            cwd=str(workspace_root),
            timeout=10,
        )
        if result.returncode != 0:
            raise WorkspaceRootValidationError(
                "workspace_root_not_git_repo",
                f"Workspace root '{workspace_root}' is not a git repository. "
                "Worktree execution requires a git repo.",
            )
