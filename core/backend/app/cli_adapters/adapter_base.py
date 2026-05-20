from __future__ import annotations
"""
CLI adapter base classes — non-execution support only.

This module provides abstract base classes and data types for CLI adapter
implementations used for:
  - CLI tool detection and health probes (app.cli_adapters)
  - Sandbox/worktree preparation (app.workspace.sandbox_manager)

These classes are NOT part of the canonical runtime execution path.
Canonical executable adapters live in app.runtimes (BaseRuntimeAdapter).
Do not add new product runtime adapters here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Canonical definition lives in app.runs.types — re-exported here for
# stable CLI adapter imports.
from ..runs.types import RuntimeExecutionResult  # noqa: F401


@dataclass
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class CLIStatus:
    """Detection result for a single CLI tool installation."""
    available: bool
    version: str | None = None
    executable_path: str | None = None
    login_detected: bool | None = None
    status_message: str | None = None


@dataclass
class CLIAdapterCapabilities:
    """Static capability flags for a CLI adapter."""
    supports_headless_run: bool = True
    supports_interactive_run: bool = False
    supports_streaming_logs: bool = False
    supports_model_override: bool = False
    supports_usage_output: bool = False
    supports_patch_output: bool = False
    # CLAUDE.md | AGENTS.md | prompt.md | custom
    context_file_type: str = "prompt.md"
    # precise | estimated | unknown
    usage_accuracy: str = "unknown"


@dataclass
class CredentialSpec:
    """Declares the CLI login-state requirements of an adapter."""
    # matches keys in cli-credentials.yaml and CredentialBroker runtimes
    runtime: str
    # if True, the broker logs a warning when no profile is found; run still proceeds
    required: bool = False
    # where the CLI looks for its login state (relative to HOME or absolute)
    default_target_path: str = ""
    # whether the credential dir can be mounted read-only in Docker mode
    supports_read_only: bool = False
    # env var the CLI accepts as an auth token alternative (None if not supported)
    env_auth_var: str | None = None


class AgentAdapter(ABC):
    """Abstract base for CLI adapter implementations (detection + sandbox only)."""

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the underlying tool is installed and configured."""
        ...

    @abstractmethod
    def run(
        self,
        prompt: str,
        context: dict,
        workspace_path: str | None = None,
        timeout: int = 300,
    ) -> RuntimeExecutionResult:
        ...

    def detect(self) -> CLIStatus:
        """Probe the CLI tool and return its detection status."""
        return CLIStatus(available=self.is_available())

    def get_capabilities(self) -> CLIAdapterCapabilities:
        """Return static capability flags for this adapter."""
        return CLIAdapterCapabilities()

    def get_credential_spec(self) -> CredentialSpec | None:
        """
        Declare this adapter's CLI login-state requirements.
        Return None if the adapter needs no credentials (e.g. echo).
        """
        return None


class Executor(ABC):
    """Abstract command executor. Concrete implementations: local, docker."""

    @abstractmethod
    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int = 60,
        env: dict | None = None,
    ) -> ExecutionResult:
        ...
