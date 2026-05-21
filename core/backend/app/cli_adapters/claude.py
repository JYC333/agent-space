from __future__ import annotations
"""
ClaudeCLIAdapter — wraps the `claude` CLI tool via subprocess.

Execution via canonical path only. Used for:
  - CLI tool detection (is `claude` installed and reachable?)
  - Sandbox preparation (writing CLAUDE.md context file into worktree)

This adapter is executed canonically through app.runtimes.adapters.cli_runtime
(ClaudeCodeRuntimeAdapter → CliRuntimeAdapter.execute). It is not directly
registered in app.runtimes.registry.

Context injection:
  With sandbox_dir set: ContextCompiler writes CLAUDE.md into sandbox_dir.
  Claude CLI reads it automatically from its CWD. The prompt is the task goal only.

  Without sandbox_dir (no sandbox): context is embedded as JSON in the prompt.
  Used only for echo/test paths; CLI adapters always receive a sandbox_dir in production.
"""

import json
import shutil
import subprocess
from datetime import datetime, UTC
from .adapter_base import AgentAdapter, RuntimeExecutionResult, CLIStatus, CLIAdapterCapabilities, CredentialSpec
from .executors import LocalExecutor


class ClaudeCLIAdapter(AgentAdapter):
    """Runs prompts via the Claude Code CLI (`claude` command)."""

    def __init__(
        self,
        executor=None,
        sandbox_dir: str | None = None,
        credential_grant=None,
        model: str | None = None,
    ):
        self.executor = executor or LocalExecutor()
        self.sandbox_dir = sandbox_dir  # where CLAUDE.md is written and claude runs
        # CredentialGrant from CredentialBroker (worktree: has .env; docker: broker wired into executor)
        self.credential_grant = credential_grant
        self.model = model  # optional model override passed as --model flag

    @property
    def adapter_type(self) -> str:
        return "claude_code"

    def is_available(self) -> bool:
        from .executors import DockerExecutor
        if isinstance(self.executor, DockerExecutor):
            return self.executor.available
        return shutil.which("claude") is not None

    def detect(self) -> CLIStatus:
        exe = shutil.which("claude")
        if not exe:
            return CLIStatus(available=False, status_message="'claude' not found in PATH")
        version: str | None = None
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
            version = r.stdout.strip() or r.stderr.strip() or None
        except Exception:
            pass
        return CLIStatus(available=True, version=version, executable_path=exe)

    def get_capabilities(self) -> CLIAdapterCapabilities:
        return CLIAdapterCapabilities(
            supports_headless_run=True,
            supports_interactive_run=True,
            supports_streaming_logs=False,
            supports_model_override=True,
            supports_usage_output=False,
            supports_patch_output=True,
            context_file_type="CLAUDE.md",
            usage_accuracy="unknown",
        )

    def get_credential_spec(self) -> CredentialSpec:
        return CredentialSpec(
            runtime="claude_code",
            required=False,
            default_target_path="/home/agent/.claude",
            supports_read_only=False,
            env_auth_var="ANTHROPIC_API_KEY",
        )

    def run(
        self,
        prompt: str,
        context: dict,
        workspace_path: str | None = None,
        timeout: int = 300,
        continue_conversation: bool = False,
        run_id: str | None = None,
        **_kwargs,
    ) -> RuntimeExecutionResult:
        """
        Run a prompt via the Claude Code CLI.

        continue_conversation: when True, passes --continue so Claude resumes
        its most recent conversation rather than starting a fresh session.
        """
        if not self.is_available():
            return RuntimeExecutionResult(
                success=False, output="",
                error="claude CLI is not installed or not in PATH.",
                exit_code=-1,
            )

        if self.sandbox_dir is not None:
            from ..memory.context_compiler import ContextCompiler, TargetFormat
            ContextCompiler().compile(
                context=context,
                target=TargetFormat.claude,
                task_goal=prompt,
                sandbox_dir=self.sandbox_dir,
            )
            task_prompt = prompt
            cwd = self.sandbox_dir
        else:
            context_str = json.dumps(context, indent=2, default=str)
            task_prompt = f"[SYSTEM CONTEXT]\n{context_str}\n\n[USER PROMPT]\n{prompt}"
            cwd = workspace_path

        # Inject credential HOME env if a worktree grant is active
        cred_env: dict | None = None
        if self.credential_grant and self.credential_grant.env:
            cred_env = self.credential_grant.env

        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
        if self.model:
            cmd += ["--model", self.model]
        if continue_conversation:
            cmd.append("--continue")
        cmd.append(task_prompt)

        started = datetime.now(UTC)
        result = self.executor.run_command(
            command=cmd,
            cwd=cwd,
            timeout=timeout,
            env=cred_env,
            run_id=run_id,
        )
        completed = datetime.now(UTC)

        return RuntimeExecutionResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            exit_code=result.returncode,
            started_at=started,
            completed_at=completed,
        )
