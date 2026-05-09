from __future__ import annotations
"""
LocalExecutor + DockerExecutor + EchoAgentAdapter.

Executors implement the Executor ABC and are injected into adapters.
- LocalExecutor  — subprocess on the host (used in dev / echo agent)
- DockerExecutor — runs commands inside an agent-space-sandbox container
                   (used when runtime_policy.risk_level = "high" (escalates sandbox level))
"""

import os
import subprocess
from datetime import datetime, UTC
from pathlib import Path

from .base import AgentAdapter, AgentRunResult, Executor, ExecutionResult


# Env vars forwarded from the host into sandbox containers.
# Only keys explicitly listed here are passed — never the whole env.
_PASSTHROUGH_ENV = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "HOME",     # needed by some CLIs for config lookup
    "PATH",
}


class LocalExecutor(Executor):
    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
    ) -> ExecutionResult:
        # If env is provided, merge it on top of the current process environment
        # so the subprocess still inherits PATH, LANG, etc.
        merged_env = None
        if env:
            merged_env = dict(os.environ)
            merged_env.update(env)

        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=merged_env,
            )
            return ExecutionResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(returncode=-1, stdout="", stderr="Command timed out.", timed_out=True)
        except Exception as e:
            return ExecutionResult(returncode=-1, stdout="", stderr=str(e))


class DockerExecutor(Executor):
    """
    Runs commands inside an agent-space-sandbox container as a sibling container
    spawned via the Docker socket mounted into the API container.

    Per-run isolation:
      - sandbox_dir mounted rw at /workspace (agent's working directory)
      - workspace_path mounted ro at /workspace/repo (the actual repo, optional)
      - network_mode controlled per adapter type (echo=none, claude_cli=bridge)
      - 1 GB RAM, 1 CPU hard limits
      - Container auto-removed after completion
    """

    def __init__(
        self,
        image: str,
        sandbox_dir: str,
        extra_volumes: dict | None = None,
        network_mode: str = "none",
        mem_limit: str = "1g",
        nano_cpus: int = 1_000_000_000,  # 1 CPU
        extra_env: dict | None = None,
        credential_volumes: dict | None = None,
    ):
        self.image = image
        self.sandbox_dir = str(Path(sandbox_dir).resolve())
        self.extra_volumes = extra_volumes or {}
        self.network_mode = network_mode
        self.mem_limit = mem_limit
        self.nano_cpus = nano_cpus
        self.extra_env = extra_env or {}
        # Additional volume mounts for CLI credential profiles.
        # Format: {host_path: {"bind": container_path, "mode": "ro"}}
        self.credential_volumes = credential_volumes or {}

        self._client = None
        self._init_error: str = ""
        try:
            import docker
            self._client = docker.from_env()
        except ImportError:
            self._init_error = "docker Python package not installed (pip install docker)"
        except Exception as e:
            self._init_error = str(e)

    @property
    def available(self) -> bool:
        """True if Docker daemon is reachable and the sandbox image exists."""
        if not self._client:
            return False
        try:
            self._client.images.get(self.image)
            return True
        except Exception:
            return False

    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
    ) -> ExecutionResult:
        if not self._client:
            return ExecutionResult(-1, "", f"DockerExecutor unavailable: {self._init_error}")

        # Build volume map: sandbox dir always rw; extras (repo, credentials) as configured
        volumes = {self.sandbox_dir: {"bind": "/workspace", "mode": "rw"}}
        volumes.update(self.extra_volumes)
        volumes.update(self.credential_volumes)

        # Safe env passthrough — never leak the full host env
        safe_env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
        safe_env.update(self.extra_env)
        if env:
            safe_env.update(env)

        container = None
        try:
            import docker
            container = self._client.containers.run(
                self.image,
                command=command,
                volumes=volumes,
                working_dir="/workspace",
                environment=safe_env,
                network_mode=self.network_mode,
                mem_limit=self.mem_limit,
                nano_cpus=self.nano_cpus,
                # /tmp writable even if image root is ro; sandbox_dir already rw via volume
                tmpfs={"/tmp": "size=256m"},
                detach=True,
                remove=False,  # we remove after log capture
            )
            try:
                result = container.wait(timeout=timeout)
                exit_code = result.get("StatusCode", -1)
                timed_out = False
            except Exception:
                container.kill()
                exit_code = -1
                timed_out = True

            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
            return ExecutionResult(
                returncode=exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )
        except Exception as e:
            return ExecutionResult(-1, "", str(e))
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass


class EchoAgentAdapter(AgentAdapter):
    """Development/test adapter — echoes the prompt back as output. Never sandboxed."""

    @property
    def adapter_type(self) -> str:
        return "echo"

    def is_available(self) -> bool:
        return True

    def run(
        self,
        prompt: str,
        context: dict,
        workspace_path: str | None = None,
        timeout: int = 300,
    ) -> AgentRunResult:
        started = datetime.now(UTC)
        output = f"[ECHO AGENT]\nPrompt: {prompt}\n\nContext keys: {list(context.keys())}"
        return AgentRunResult(
            success=True,
            output=output,
            exit_code=0,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
