"""Minimal worktree validation — runs configured test commands inside the worktree sandbox.

Runs after successful CLI execution and before the code_patch proposal is created.
Evidence is attached to the proposal payload so reviewers can see whether basic
checks passed before deciding to apply the patch.

Rules:
- Commands run ONLY in worktree_path (the sandbox copy), never in the real workspace.
- Commands run inside a sanitized environment: only safe variables (PATH, HOME, SHELL,
  LANG, etc.) are passed.  Any env var whose name matches a sensitive pattern
  (*_API_KEY, *TOKEN*, *SECRET*, *PASSWORD*, *CREDENTIAL*, AUTH*) is stripped before
  the subprocess is launched.
- stdout/stderr snippets are bounded at MAX_SNIPPET_BYTES AND redacted with the shared
  redact_string helper before being stored in ValidationEvidence.  This catches any
  key=value secret patterns that appear in command output even if the env stripping
  failed to prevent them.
- The sanitized environment is never logged or stored in the proposal payload.
- Validation failure does NOT block proposal creation — the proposal gets
  validation.status="failed" and is still reviewable (visibly degraded/risky).
- No secrets are recorded: commands are taken from WorkspaceProfile.test_commands_json
  which must contain only safe CLI commands (pytest, npm test, cargo test, etc.).
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MAX_SNIPPET_BYTES = 4096  # per-command stdout+stderr snippet cap
MAX_COMMANDS = 10         # guard against pathological profiles
COMMAND_TIMEOUT = 120     # seconds per validation command

# ---------------------------------------------------------------------------
# Safe subprocess environment
# ---------------------------------------------------------------------------

# Variables allowed to pass through to validation subprocesses.
_SAFE_ENV_ALLOWLIST: frozenset[str] = frozenset({
    "PATH", "HOME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TERM", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME",
    # Python environments
    "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "CONDA_PREFIX",
    "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
    # Node.js
    "NODE_PATH", "NODE_ENV",
    # Rust
    "CARGO_HOME", "RUSTUP_HOME",
    # Go
    "GOPATH", "GOROOT",
    # Java
    "JAVA_HOME",
    # Git identity (needed by some test frameworks that commit)
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
})

# Glob patterns (uppercase) that mark a variable as sensitive.
# Applied as a second-pass safety net even for allowlisted names.
_SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "*_API_KEY", "*TOKEN*", "*SECRET*", "*PASSWORD*", "*CREDENTIAL*", "AUTH*",
)


def _build_safe_env() -> dict[str, str]:
    """Return a sanitized copy of os.environ for use by validation subprocesses.

    Only variables in ``_SAFE_ENV_ALLOWLIST`` are kept, then a second pass
    removes any that match ``_SENSITIVE_KEY_PATTERNS`` (e.g. a custom env
    var named ``HOME_TOKEN`` would slip through the allowlist but is caught
    by the pattern check).
    """
    env: dict[str, str] = {}
    for key, val in os.environ.items():
        if key not in _SAFE_ENV_ALLOWLIST:
            continue
        upper = key.upper()
        if any(fnmatch.fnmatch(upper, pat) for pat in _SENSITIVE_KEY_PATTERNS):
            continue
        env[key] = val
    return env


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout_snippet: str
    stderr_snippet: str
    started_at: str
    completed_at: str
    status: str  # "passed" | "failed"


@dataclass
class ValidationEvidence:
    """Outcome of running worktree validation commands."""

    status: str  # "passed" | "failed" | "skipped"
    skip_reason: str | None = None
    command_count: int = 0
    failed_command: str | None = None
    commands: list[CommandResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "skip_reason": self.skip_reason,
            "command_count": self.command_count,
            "failed_command": self.failed_command,
            "commands": [
                {
                    "command": c.command,
                    "exit_code": c.exit_code,
                    "stdout_snippet": c.stdout_snippet,
                    "stderr_snippet": c.stderr_snippet,
                    "started_at": c.started_at,
                    "completed_at": c.completed_at,
                    "status": c.status,
                }
                for c in self.commands
            ],
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(text: str, max_bytes: int = MAX_SNIPPET_BYTES) -> str:
    """Truncate output to max_bytes, adding a marker if truncated."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n...[truncated]"


def _redact_and_truncate(text: str) -> str:
    """Apply secret-pattern redaction then truncate to MAX_SNIPPET_BYTES.

    Redaction runs first so the truncation marker is never lost inside a
    replaced secret value.
    """
    from .redaction import redact_string
    return _truncate(redact_string(text))


def run_validation_in_worktree(
    *,
    worktree_path: Path,
    commands: list[str],
) -> ValidationEvidence:
    """Execute each command inside worktree_path and collect evidence.

    Commands run with cwd=worktree_path to ensure they operate only on the
    worktree copy, never on the real workspace.

    Returns ValidationEvidence with status="passed" | "failed" | "skipped".
    """
    if not commands:
        return ValidationEvidence(
            status="skipped",
            skip_reason="no_validation_commands",
            command_count=0,
        )

    commands = commands[:MAX_COMMANDS]
    results: list[CommandResult] = []
    overall_status = "passed"
    failed_command: str | None = None

    safe_env = _build_safe_env()

    # Replace HOME with a fresh temporary directory so validation subprocesses
    # cannot read user or container config (e.g. ~/.npmrc, ~/.gitconfig).
    # PWD is set to worktree_path so any shell that reads PWD directly (rather
    # than relying on the cwd passed to subprocess.run) sees the correct path.
    # On failure to create the temp dir, skip validation rather than leaking real HOME.
    tmp_home: Path | None = None
    try:
        tmp_home = Path(tempfile.mkdtemp())
        safe_env["HOME"] = str(tmp_home)
        safe_env["PWD"] = str(worktree_path)
    except Exception:
        return ValidationEvidence(
            status="skipped",
            skip_reason="isolated_home_unavailable",
            command_count=0,
        )

    try:
        for cmd in commands:
            if not isinstance(cmd, str) or not cmd.strip():
                continue
            started = _now_iso()
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(worktree_path),
                    capture_output=True,
                    text=True,
                    timeout=COMMAND_TIMEOUT,
                    env=safe_env,
                )
                exit_code = proc.returncode
                stdout_raw = proc.stdout or ""
                stderr_raw = proc.stderr or ""
            except subprocess.TimeoutExpired:
                exit_code = -1
                stdout_raw = ""
                stderr_raw = f"Command timed out after {COMMAND_TIMEOUT}s"
            except Exception as exc:
                exit_code = -1
                stdout_raw = ""
                stderr_raw = f"Command execution error: {str(exc)[:200]}"

            completed = _now_iso()
            cmd_status = "passed" if exit_code == 0 else "failed"
            results.append(CommandResult(
                command=cmd,
                exit_code=exit_code,
                stdout_snippet=_redact_and_truncate(stdout_raw),
                stderr_snippet=_redact_and_truncate(stderr_raw),
                started_at=started,
                completed_at=completed,
                status=cmd_status,
            ))

            if cmd_status == "failed" and overall_status == "passed":
                overall_status = "failed"
                failed_command = cmd

        return ValidationEvidence(
            status=overall_status,
            skip_reason=None,
            command_count=len(results),
            failed_command=failed_command,
            commands=results,
        )
    finally:
        if tmp_home is not None:
            shutil.rmtree(str(tmp_home), ignore_errors=True)


def get_workspace_validation_commands(
    db: "Session",
    *,
    workspace_id: str,
    space_id: str,
) -> list[str]:
    """Fetch test_commands_json from WorkspaceProfile for this workspace.

    Returns an empty list when no profile exists or no test commands are configured.
    """
    from ..models import WorkspaceProfile
    try:
        profile = (
            db.query(WorkspaceProfile)
            .filter(
                WorkspaceProfile.workspace_id == workspace_id,
                WorkspaceProfile.space_id == space_id,
            )
            .first()
        )
        if profile is None:
            return []
        cmds = profile.test_commands_json or []
        if not isinstance(cmds, list):
            return []
        return [str(c) for c in cmds if c and isinstance(c, str)]
    except Exception:
        log.warning(
            "Failed to load WorkspaceProfile test_commands for workspace=%s", workspace_id,
            exc_info=True,
        )
        return []
