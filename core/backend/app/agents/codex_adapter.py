from __future__ import annotations
"""
Codex CLI adapter — wraps the `codex` CLI tool via subprocess.

Context injection mirrors ClaudeCLIAdapter:
  With sandbox_dir: ContextCompiler writes AGENTS.md into sandbox_dir.
  Without sandbox_dir: context embedded as JSON in the prompt.
"""

import json
import shutil
import subprocess
from datetime import datetime, UTC
from .base import AgentAdapter, AgentRunResult, CLIStatus, CLIAdapterCapabilities, CredentialSpec
from .cli_adapter import LocalExecutor


class CodexCLIAdapter(AgentAdapter):
    def __init__(self, executor=None, sandbox_dir: str | None = None, credential_grant=None):
        self.executor = executor or LocalExecutor()
        self.sandbox_dir = sandbox_dir
        self.credential_grant = credential_grant

    @property
    def adapter_type(self) -> str:
        return "codex_cli"

    def is_available(self) -> bool:
        from .cli_adapter import DockerExecutor
        if isinstance(self.executor, DockerExecutor):
            return self.executor.available
        return shutil.which("codex") is not None

    def detect(self) -> CLIStatus:
        exe = shutil.which("codex")
        if not exe:
            return CLIStatus(available=False, status_message="'codex' not found in PATH")
        version: str | None = None
        try:
            r = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=5)
            version = r.stdout.strip() or r.stderr.strip() or None
        except Exception:
            pass
        return CLIStatus(available=True, version=version, executable_path=exe)

    def get_capabilities(self) -> CLIAdapterCapabilities:
        return CLIAdapterCapabilities(
            supports_headless_run=True,
            supports_interactive_run=False,
            supports_streaming_logs=False,
            supports_model_override=False,
            supports_usage_output=False,
            supports_patch_output=True,
            context_file_type="AGENTS.md",
            usage_accuracy="unknown",
        )

    def get_credential_spec(self) -> CredentialSpec:
        return CredentialSpec(
            runtime="codex",
            required=False,
            default_target_path="/home/agent/.codex",
            supports_read_only=True,
            env_auth_var="OPENAI_API_KEY",  # Codex also supports env-var auth
        )

    def run(
        self,
        prompt: str,
        context: dict,
        workspace_path: str | None = None,
        timeout: int = 300,
        **_kwargs,
    ) -> AgentRunResult:
        if not self.is_available():
            return AgentRunResult(
                success=False, output="",
                error="codex CLI is not installed or not in PATH.",
                exit_code=-1,
            )

        if self.sandbox_dir is not None:
            from ..memory.context_compiler import ContextCompiler, TargetFormat
            ContextCompiler().compile(
                context=context,
                target=TargetFormat.codex,
                task_goal=prompt,
                sandbox_dir=self.sandbox_dir,
            )
            task_prompt = prompt
            cwd = self.sandbox_dir
        else:
            context_str = json.dumps(context, indent=2, default=str)
            task_prompt = f"[CONTEXT]\n{context_str}\n\n[TASK]\n{prompt}"
            cwd = workspace_path

        cred_env: dict | None = None
        if self.credential_grant and self.credential_grant.env:
            cred_env = self.credential_grant.env

        started = datetime.now(UTC)
        result = self.executor.run_command(
            command=["codex", task_prompt],
            cwd=cwd,
            timeout=timeout,
            env=cred_env,
        )
        completed = datetime.now(UTC)

        return AgentRunResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            exit_code=result.returncode,
            started_at=started,
            completed_at=completed,
        )
