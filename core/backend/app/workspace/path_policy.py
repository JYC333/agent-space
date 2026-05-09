from __future__ import annotations
"""
PathPolicy — validates file system paths before any agent file access.

All workspace and sandbox file access must go through PathPolicy.validate()
before reading or writing. This prevents path traversal attacks and ensures
agents can only access their declared workspace or sandbox root.

Allowed roots come from settings.workspace_root and settings.sandbox_root,
which default to $AGENT_SPACE_HOME/workspaces and $AGENT_SPACE_HOME/sandboxes.
"""

from pathlib import Path
from typing import Optional

from ..config import settings


class PathPolicyError(PermissionError):
    """Raised when a path violates the access policy."""


# Always-forbidden path fragments regardless of allowed root
_FORBIDDEN_FRAGMENTS = {
    ".ssh", ".env", ".aws", ".gcp", ".azure",
    "instance/secrets", "credentials", ".git/config",
}

# Agents may not write these file types directly — must go through a patch proposal
_FORBIDDEN_WRITE_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".fish"}


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
    ) -> Path:
        """
        Validate that `path` is safe to access.

        Args:
            path         — path requested by the agent (may be relative)
            allowed_root — workspace or sandbox root for this run;
                           defaults to workspace_root
            mode         — "read" or "write"

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

        # Forbidden fragment check
        resolved_str = str(resolved)
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in resolved_str:
                raise PathPolicyError(f"Access to '{fragment}' is forbidden")

        # Write restrictions
        if mode == "write" and resolved.suffix in _FORBIDDEN_WRITE_SUFFIXES:
            raise PathPolicyError(
                f"Agents may not write '{resolved.suffix}' files directly — "
                "use a code_patch Proposal instead"
            )

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
