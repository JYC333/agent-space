from __future__ import annotations
"""
Agent adapter interface — runtime execution backends only.

AgentAdapter decouples the agent kernel from execution backends. The kernel
(AgentService) is the single source of truth for agent identity, memory policy,
delegation rules, and run logging. Adapters are thin execution wrappers: they
receive a prompt + context snapshot and return a result. They own nothing.

Adapter types built in:
  "echo"       — deterministic test adapter; no external deps
  "claude_cli" — Claude Code CLI subprocess
  "codex_cli"  — OpenAI Codex CLI subprocess

External frameworks (OpenAI Agents SDK, LangGraph, CrewAI, Letta, etc.) can
be wired in as additional adapters without touching the kernel. An agent's
`runtime_policy_json.allowed_adapter_types` controls which backends it may use.

RuntimeExecutionResult is defined in app.runs.types (canonical location).
Re-exported here for stable CLI adapter imports.
New code should import from app.runs.types directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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
    """Abstract base for all agent adapters."""

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
