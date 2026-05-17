from __future__ import annotations
"""
SandboxManager — multi-level isolated execution environments for agent runs.

CLI ADAPTER RUNTIME PATH ONLY
==============================
This module (``app.workspace.sandbox_manager``) is the CLI adapter sandbox
manager.  It is used only by ``app.agents`` (the CLI adapter runtime path) and
Docker-based CLI adapter routes.

Do NOT use this module as the sandbox/path boundary for new runtime adapters.
The canonical sandbox and path policy for new runtime execution is:

  Canonical sandbox manager: ``app.runs.sandbox_manager`` (execution_workspace)
  Canonical worktree manager: ``app.runs.worktree_manager`` (isolated_run_workdir)
  Canonical path policy: ``app.workspace.path_policy.PathPolicy``

``RunExecutionService`` uses ``app.runs.sandbox_manager`` exclusively.
New runtime adapters in ``app.runtimes`` must not call this module directly.

---

SandboxManager sandbox levels (risk-based):
  Level 0  dry_run          — no execution; read-only context assembly only
  Level 1  worktree         — git worktree + local executor (DEFAULT)
  Level 2  one_shot_docker  — git worktree + one-shot Docker container (high-risk only)

Risk → level mapping:
  low      → dry_run
  medium   → worktree          ← default for all CLI adapters
  high     → one_shot_docker
  critical → one_shot_docker   (future: remote/microVM)

Design principles:
  - The default sandbox unit is a git worktree, not a Docker container.
  - Docker is an on-demand backend for high-risk tasks only; never the default.
  - Container pool and remote sandbox are out of current scope.
  - When workspace_path is a git repo, create a real git worktree (no full copy).
  - When workspace_path has no git repo, create a plain directory sandbox.
  - Docker containers are created per-run and removed immediately on completion.
  - Long-term records: diff, logs, artifacts. Not the sandbox directory itself.

Docker-in-Docker path translation:
  When the backend runs inside Docker, volume paths passed to child containers must be
  HOST paths. _resolve_host_path() reads /proc/self/mountinfo to translate them.
"""

import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

SANDBOX_IMAGE = "agent-space-sandbox:latest"

# Adapters that need internet access inside the container
_BRIDGE_NETWORK_ADAPTERS = {"claude_code", "claude_cli", "codex_cli"}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SandboxLevel(str, Enum):
    DRY_RUN         = "dry_run"
    WORKTREE        = "worktree"
    ONE_SHOT_DOCKER = "one_shot_docker"


class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


RISK_TO_SANDBOX_LEVEL: dict[RiskLevel, SandboxLevel] = {
    RiskLevel.LOW:      SandboxLevel.DRY_RUN,
    RiskLevel.MEDIUM:   SandboxLevel.WORKTREE,
    RiskLevel.HIGH:     SandboxLevel.ONE_SHOT_DOCKER,
    RiskLevel.CRITICAL: SandboxLevel.ONE_SHOT_DOCKER,  # future: remote/microVM
}


# ---------------------------------------------------------------------------
# Sandbox context
# ---------------------------------------------------------------------------

@dataclass
class SandboxContext:
    """Holds the state for one agent run's sandbox."""
    run_id: str
    level: SandboxLevel
    sandbox_dir: Path
    is_git_worktree: bool = False
    execution_mode: str = "local"

    def cleanup(self) -> bool:
        """Remove the sandbox directory. Call after artifact collection."""
        import shutil
        if not self.sandbox_dir.exists():
            return False
        if self.is_git_worktree:
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(self.sandbox_dir)],
                    capture_output=True, timeout=30,
                )
                return True
            except Exception as e:
                log.warning("git worktree remove failed for %s: %s — falling back to rmtree", self.sandbox_dir, e)
        shutil.rmtree(self.sandbox_dir, ignore_errors=True)
        return True


# ---------------------------------------------------------------------------
# Docker-in-Docker path translation
# ---------------------------------------------------------------------------

def _resolve_host_path(container_path: str) -> str:
    """
    Translate a path inside the backend container to the corresponding host path.
    Falls back to the original path when running outside Docker.
    """
    target = str(Path(container_path).resolve())
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                mount_point = parts[4]
                try:
                    sep = parts.index("-", 6)
                    source = parts[sep + 2]
                except (ValueError, IndexError):
                    continue
                mount_point = mount_point.rstrip("/")
                if target == mount_point or target.startswith(mount_point + "/"):
                    relative = target[len(mount_point):]
                    return source.rstrip("/") + relative
    except Exception:
        pass
    return container_path


def _is_git_repo(path: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path, capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Concurrency limiter (Docker runs only)
# ---------------------------------------------------------------------------

_docker_semaphore: threading.BoundedSemaphore | None = None
_semaphore_lock = threading.Lock()


def get_docker_semaphore() -> threading.BoundedSemaphore:
    """Process-wide semaphore limiting concurrent Docker container runs."""
    global _docker_semaphore
    if _docker_semaphore is None:
        with _semaphore_lock:
            if _docker_semaphore is None:
                _docker_semaphore = threading.BoundedSemaphore(
                    settings.max_concurrent_docker_runs
                )
    return _docker_semaphore


# ---------------------------------------------------------------------------
# SandboxManager
# ---------------------------------------------------------------------------

class SandboxUnavailableError(RuntimeError):
    """Raised when a required sandbox backend is unavailable."""


class SandboxManager:
    """
    Creates isolated sandbox environments for agent runs.

    Default usage (medium risk / worktree):
        mgr = SandboxManager()
        ctx = mgr.create_worktree(run_id, workspace_path)
        adapter = ClaudeCLIAdapter(executor=LocalExecutor(), sandbox_dir=str(ctx.sandbox_dir))

    High-risk Docker usage:
        mgr = SandboxManager()
        if not mgr.is_docker_available():
            # decide: raise or fall back to worktree
        adapter = mgr.get_docker_adapter(adapter_type, run_id, workspace_path)
    """

    def __init__(self, sandbox_root: str | None = None, image: str = SANDBOX_IMAGE):
        self.sandbox_root = Path(sandbox_root or settings.sandbox_root)
        self.image = image

    def resolve_level(self, risk_level: str) -> SandboxLevel:
        try:
            return RISK_TO_SANDBOX_LEVEL[RiskLevel(risk_level)]
        except (ValueError, KeyError):
            return SandboxLevel.WORKTREE

    def create_worktree(
        self,
        run_id: str,
        workspace_path: str | None = None,
    ) -> SandboxContext:
        """
        Create a Level 1 sandbox: git worktree or plain directory + local executor.

        If workspace_path is a git repo, creates a detached git worktree so the agent
        can read the full history and produce a clean diff. Falls back to a plain
        directory when git is unavailable or the workspace is not a repo.
        """
        sandbox_dir = self.sandbox_root / run_id
        is_worktree = False

        if workspace_path and Path(workspace_path).exists() and _is_git_repo(workspace_path):
            if not sandbox_dir.exists():
                try:
                    subprocess.run(
                        ["git", "worktree", "add", "--detach", str(sandbox_dir)],
                        cwd=workspace_path,
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    is_worktree = True
                    log.debug("created git worktree at %s", sandbox_dir)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    log.warning("git worktree add failed: %s — using plain directory", e)

        if not is_worktree:
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            log.debug("created plain sandbox dir at %s", sandbox_dir)

        return SandboxContext(
            run_id=run_id,
            level=SandboxLevel.WORKTREE,
            sandbox_dir=sandbox_dir,
            is_git_worktree=is_worktree,
            execution_mode="local",
        )

    def is_docker_available(self) -> bool:
        """True if Docker daemon is reachable and the sandbox image exists."""
        try:
            import docker
            client = docker.from_env()
            client.images.get(self.image)
            return True
        except Exception:
            return False

    def get_docker_adapter(
        self,
        adapter_type: str,
        run_id: str,
        workspace_path: str | None = None,
        credential_grant=None,
    ):
        """
        Build a Level 2 sandboxed adapter: one-shot Docker container.

        Creates a worktree (or plain dir) as the container's writable volume,
        translates paths for DinD, then wires a DockerExecutor.

        credential_grant — optional CredentialGrant from CredentialBroker; if provided
        and executor_mode=="docker", its host_source_path/target_path are added as a
        volume mount into the container.
        """
        from ..agents.cli_adapter import DockerExecutor
        from ..agents.claude_adapter import ClaudeCLIAdapter
        from ..agents.codex_adapter import CodexCLIAdapter

        sandbox_dir = self.sandbox_root / run_id
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        host_sandbox_dir = _resolve_host_path(str(sandbox_dir))

        extra_volumes: dict = {}
        if workspace_path and Path(workspace_path).exists():
            host_workspace = _resolve_host_path(str(Path(workspace_path).resolve()))
            extra_volumes[host_workspace] = {"bind": "/workspace/repo", "mode": "ro"}

        extra_env = {
            k: os.environ[k]
            for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
            if k in os.environ
        }

        # Credential volume: only the selected profile dir is mounted, read-only by default
        credential_volumes: dict = {}
        if (
            credential_grant
            and credential_grant.executor_mode == "docker"
            and credential_grant.host_source_path
            and credential_grant.target_path
        ):
            mode = "ro" if credential_grant.readonly else "rw"
            credential_volumes[credential_grant.host_source_path] = {
                "bind": credential_grant.target_path,
                "mode": mode,
            }
            log.debug(
                "Docker credential mount: %s → %s (%s)",
                credential_grant.host_source_path, credential_grant.target_path, mode,
            )

        network_mode = "bridge" if adapter_type in _BRIDGE_NETWORK_ADAPTERS else "none"

        executor = DockerExecutor(
            image=self.image,
            sandbox_dir=host_sandbox_dir,
            extra_volumes=extra_volumes,
            network_mode=network_mode,
            extra_env=extra_env,
            credential_volumes=credential_volumes,
        )
        # In Docker mode, sandbox_dir inside the container is always /workspace
        docker_sandbox_dir = "/workspace"

        if adapter_type in ("claude_code", "claude_cli"):
            return ClaudeCLIAdapter(executor=executor, sandbox_dir=docker_sandbox_dir)
        elif adapter_type == "codex_cli":
            return CodexCLIAdapter(executor=executor, sandbox_dir=docker_sandbox_dir)
        else:
            raise ValueError(f"Adapter '{adapter_type}' does not support Docker sandbox execution.")

    def sandbox_path(self, run_id: str) -> Path:
        return self.sandbox_root / run_id

    def cleanup(self, run_id: str, is_git_worktree: bool = False) -> bool:
        """Remove a run's sandbox. Prefer SandboxContext.cleanup() when available."""
        ctx = SandboxContext(
            run_id=run_id,
            level=SandboxLevel.WORKTREE,
            sandbox_dir=self.sandbox_root / run_id,
            is_git_worktree=is_git_worktree,
        )
        return ctx.cleanup()
