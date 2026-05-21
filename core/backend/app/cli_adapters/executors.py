from __future__ import annotations
"""
LocalExecutor, DockerExecutor, and EchoAgentAdapter — CLI subprocess infrastructure.

Non-execution support only:
  - LocalExecutor / DockerExecutor are injected into CLI adapter classes for
    sandbox (worktree + Docker) execution during workspace preparation.
  - EchoAgentAdapter is used for detection/health probes.

These classes are NOT part of the canonical runtime execution path.
Canonical executable adapters live in app.runtimes (BaseRuntimeAdapter).
"""

import os
import signal
import subprocess
from datetime import datetime, UTC
from pathlib import Path

from .adapter_base import AgentAdapter, RuntimeExecutionResult, Executor, ExecutionResult


# ---------------------------------------------------------------------------
# Docker passthrough env — only these keys are forwarded into sandbox containers.
# ---------------------------------------------------------------------------
# Env vars forwarded from the host into sandbox containers.
# Only keys explicitly listed here are passed — never the whole env.
_PASSTHROUGH_ENV = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "HOME",     # needed by some CLIs for config lookup
    "PATH",
}

# ---------------------------------------------------------------------------
# LocalExecutor subprocess env allowlist
# ---------------------------------------------------------------------------
# Keys forwarded verbatim from host env into CLI subprocesses.
# Never includes secret/credential env vars — those come via CredentialBroker
# grant.env (HOME + optional API key) injected as explicit extras.
#
# LANG is an exact key match, not a prefix. This prevents LANG_TOKEN,
# LANG_SECRET, or any other LANG_* name from leaking via a prefix match.
_LOCAL_ENV_ALLOWED_KEYS: frozenset[str] = frozenset({"PATH", "TERM", "SHELL", "LANG"})
# Only the LC_ prefix (locale category variables: LC_ALL, LC_CTYPE, …).
_LOCAL_ENV_ALLOWED_PREFIXES: tuple[str, ...] = ("LC_",)

# Explicit broker-injected keys permitted in the `extra` dict.
# Any other key supplied via `extra` is silently dropped so callers cannot
# accidentally inject arbitrary env vars.
_BROKER_INJECTED_EXTRA_KEYS: frozenset[str] = frozenset({
    "HOME",             # per-run temp HOME from CredentialBroker.grant_for_run()
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
})


def _build_subprocess_env(extra: dict | None) -> dict:
    """Build a subprocess env from an explicit allowlist plus broker-injected extras.

    Reads only LANG, LC_*, PATH, TERM, SHELL from the host os.environ.  All
    other host env vars — including any SECRET_*, TOKEN_*, API_KEY_*, HOME — are
    excluded.  Credential env vars (HOME, *_API_KEY) must arrive via ``extra``
    (from CredentialBroker grant.env); keys not in ``_BROKER_INJECTED_EXTRA_KEYS``
    are silently dropped from ``extra`` to prevent callers from injecting
    arbitrary variables.
    """
    safe: dict[str, str] = {}
    for key, val in os.environ.items():
        if key in _LOCAL_ENV_ALLOWED_KEYS or key.startswith(_LOCAL_ENV_ALLOWED_PREFIXES):
            safe[key] = val
    if extra:
        for key, val in extra.items():
            if key in _BROKER_INJECTED_EXTRA_KEYS:
                safe[key] = val
    return safe


class LocalExecutor(Executor):
    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
        run_id: str | None = None,
    ) -> ExecutionResult:
        # Build subprocess env from the allowlist; never inherit the full host env.
        # API keys and HOME arrive via `env` (CredentialBroker grant.env only).
        merged_env = _build_subprocess_env(env)

        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=merged_env,
                # New session puts the subprocess in its own process group so
                # SIGKILL can be sent to the whole group (children included).
                start_new_session=True,
            )
            if run_id is not None:
                from ..runs.process_registry import register as _reg_register
                _reg_register(run_id, proc.pid)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill the entire process group, not just the parent PID.
                # start_new_session=True makes the subprocess a process-group
                # leader, so os.killpg reaches all child processes it spawned.
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                stdout, stderr = proc.communicate()
                return ExecutionResult(
                    returncode=-1, stdout="", stderr="Command timed out.", timed_out=True
                )
            finally:
                if run_id is not None:
                    from ..runs.process_registry import deregister as _reg_deregister
                    _reg_deregister(run_id)
            return ExecutionResult(
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except Exception as e:
            if run_id is not None:
                from ..runs.process_registry import deregister as _reg_deregister
                _reg_deregister(run_id)
            return ExecutionResult(returncode=-1, stdout="", stderr=str(e))


class DockerExecutor(Executor):
    """
    Runs commands inside an agent-space-sandbox container as a sibling container
    spawned via the Docker socket mounted into the API container.

    Per-run isolation:
      - sandbox_dir mounted rw at /workspace (agent's working directory)
      - workspace_path mounted ro at /workspace/repo (the actual repo, optional)
      - network_mode controlled per adapter type (echo=none, claude_code=bridge)
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
    ) -> RuntimeExecutionResult:
        started = datetime.now(UTC)
        output = f"[ECHO AGENT]\nPrompt: {prompt}\n\nContext keys: {list(context.keys())}"
        return RuntimeExecutionResult(
            success=True,
            output=output,
            exit_code=0,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
