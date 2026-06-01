from __future__ import annotations
"""
PathPolicy — validates file system paths before any agent file access.

All workspace and sandbox file access must go through PathPolicy.validate()
before reading or writing. This prevents path traversal attacks and ensures
agents can only access their declared workspace or sandbox root.

Allowed roots come from settings.workspace_root and settings.sandbox_root,
which default to $AGENT_SPACE_HOME/workspaces and $AGENT_SPACE_HOME/sandboxes.

System-core workspaces (workspace_type=system_core):
  - All writes must go through a git worktree sandbox — never direct to root_path
  - code_patch proposals required for all code changes
  - Explicit approval required before changes can be applied
"""

from pathlib import Path
from typing import Optional

from ..config import settings


class PathPolicyError(PermissionError):
    """Raised when a path violates the access policy."""


# Always-forbidden path patterns inside the allowed root.
_FORBIDDEN_DIR_NAMES = {".ssh", ".aws", ".gcp", ".azure", "credentials"}
_FORBIDDEN_DIR_SEQUENCES = {("instance", "secrets"), ("config", "secrets")}
_FORBIDDEN_FILE_NAMES = {".env", "id_rsa", "id_ed25519"}
_ALLOWED_ENV_TEMPLATE_NAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dev.example",
    ".env.test.example",
    ".env.prod.example",
}
_FORBIDDEN_FILE_SUFFIXES = {".pem", ".key"}

# Agents may not write these file types directly — must go through a patch proposal
_FORBIDDEN_WRITE_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".fish"}

# system_core workspaces additionally block read access to .git directly
_SYSTEM_CORE_FORBIDDEN_SUFFIXES = {".git"}


class PathPolicy:
    """
    Validates paths for agent file access.

    Usage:
        policy = PathPolicy()
        safe = policy.validate(user_path, allowed_root=workspace_path)
        # Returns resolved Path if safe; raises PathPolicyError if not.
    """

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        sandbox_root: Optional[Path] = None,
    ):
        self.workspace_root = (workspace_root or Path(settings.workspace_root)).resolve()
        self.sandbox_root = (sandbox_root or Path(settings.sandbox_root)).resolve()

    def validate(
        self,
        path: str | Path,
        allowed_root: str | Path | None = None,
        mode: str = "read",
        workspace_type: str = "project",
        *,
        for_trusted_code_patch_apply: bool = False,
    ) -> Path:
        """
        Validate that `path` is safe to access.

        Args:
            path         — path requested by the agent (may be relative)
            allowed_root — workspace or sandbox root for this run;
                           defaults to workspace_root
            mode         — "read" or "write"
            workspace_type — workspace type (project, system_core, etc.)
                           system_core enforces additional restrictions:
                             - all writes must go through worktree sandbox
                             - code_patch proposals required for code changes
            for_trusted_code_patch_apply — when True with mode="write", allows approved
                           ``code_patch`` apply to write otherwise-forbidden suffixes
                           (e.g. ``.py``) under ``allowed_root`` only.

        Returns the resolved absolute Path.
        Raises PathPolicyError on any violation.
        """
        resolved = Path(path).resolve()
        root = Path(allowed_root).resolve() if allowed_root else self.workspace_root

        # Must be under the allowed root (catches .. traversal)
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PathPolicyError(
                f"Path traversal denied: '{resolved}' is not under '{root}'"
            )

        # Sensitive path checks scoped to the resolved path inside allowed_root.
        rel_parts = resolved.relative_to(root).parts
        lower_parts = tuple(p.lower() for p in rel_parts)
        for part in lower_parts:
            if part in _FORBIDDEN_DIR_NAMES:
                raise PathPolicyError(f"Access to '{part}' is forbidden")
        for sequence in _FORBIDDEN_DIR_SEQUENCES:
            if any(lower_parts[i : i + len(sequence)] == sequence for i in range(0, len(lower_parts) - len(sequence) + 1)):
                raise PathPolicyError(f"Access to '{'/'.join(sequence)}' is forbidden")
        if len(lower_parts) >= 2 and lower_parts[-2:] == (".git", "config"):
            raise PathPolicyError("Access to '.git/config' is forbidden")
        filename = resolved.name.lower()
        if filename in _FORBIDDEN_FILE_NAMES:
            raise PathPolicyError(f"Access to '{filename}' is forbidden")
        if filename.startswith(".env.") and filename not in _ALLOWED_ENV_TEMPLATE_NAMES:
            raise PathPolicyError(f"Access to '{filename}' is forbidden")
        if resolved.suffix.lower() in _FORBIDDEN_FILE_SUFFIXES:
            raise PathPolicyError(f"Access to '{resolved.suffix.lower()}' files is forbidden")

        # Write restrictions — applies to all workspaces (bypass for user-approved patch apply)
        if (
            mode == "write"
            and not for_trusted_code_patch_apply
            and resolved.suffix in _FORBIDDEN_WRITE_SUFFIXES
        ):
            raise PathPolicyError(
                f"Agents may not write '{resolved.suffix}' files directly — "
                "use a code_patch Proposal instead"
            )

        # system_core additionally forbids direct .git access (must use worktree)
        if workspace_type == "system_core":
            resolved_str = str(resolved)
            if ".git" in resolved_str:
                raise PathPolicyError(
                    "system_core workspace: direct access to .git is forbidden — "
                    "use git worktree sandbox for all operations"
                )
            # system_core writes are only allowed through worktree sandbox
            # (callers must check workspace_type and route through sandbox_manager)

        return resolved

    def validate_workspace(
        self, path: str | Path, workspace_id: str, mode: str = "read"
    ) -> Path:
        """Validate a path within a specific registered workspace directory."""
        ws_path = self.workspace_root / workspace_id
        if not ws_path.exists():
            raise PathPolicyError(f"Workspace '{workspace_id}' is not registered")
        return self.validate(path, allowed_root=ws_path, mode=mode)

    def validate_sandbox(
        self, path: str | Path, sandbox_id: str, mode: str = "read"
    ) -> Path:
        """Validate a path within a specific registered sandbox directory."""
        sb_path = self.sandbox_root / sandbox_id
        if not sb_path.exists():
            raise PathPolicyError(f"Sandbox '{sandbox_id}' is not registered")
        return self.validate(path, allowed_root=sb_path, mode=mode)

    def is_safe(
        self,
        path: str | Path,
        allowed_root: str | Path | None = None,
        mode: str = "read",
    ) -> bool:
        """Non-raising version of validate(). Returns True if safe."""
        try:
            self.validate(path, allowed_root=allowed_root, mode=mode)
            return True
        except PathPolicyError:
            return False

    def is_system_core_workspace(self, workspace_id: str, db) -> bool:
        """
        Check if a workspace is system_core type.
        Used by callers to enforce system_core policy (worktree-only, no direct writes).
        """
        from ..models import Workspace
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        return ws is not None and ws.workspace_type == "system_core" and ws.system_managed
