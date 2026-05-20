"""CLI runtime bridge — delegates execution to app.cli_adapters implementations.

This module provides the canonical runtime path for CLI-based adapter types
(claude_code, codex_cli) through BaseRuntimeAdapter and RunExecutionService.

Architecture
------------
RunExecutionService
    → instantiate_runtime_adapter("claude_code")
    → ClaudeCodeRuntimeAdapter(CliRuntimeAdapter).execute(ctx)
    → _resolve_cli_adapter("claude_code", ...)    # this module, only import point
    → ClaudeCLIAdapter.run(...)                   # subprocess via LocalExecutor
    → convert RuntimeExecutionResult → RuntimeAdapterResult

This is the ONLY place in app.runtimes that imports ClaudeCLIAdapter /
CodexCLIAdapter. RunExecutionService and the registry never import them directly.

Credential flow
---------------
CLI adapters authenticate via CredentialBroker (login-state grants), not via
ModelProvider / Credential.secret_ref API keys. ctx.resolved_credentials is
ignored here; the broker injects subprocess env vars from credential profile
directories. This is consistent with ADR 0009 (Anthropic CLI-only policy).

Context compilation
-------------------
ctx.context_package carries the serialised ContextPackage dict assembled by
ContextSnapshotPopulator in RunExecutionService. CLI adapters pass it to
ContextCompiler inside their run() method, which writes CLAUDE.md / AGENTS.md
into the sandbox directory before the CLI subprocess starts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(
    error_code: str,
    error_text: str,
    *,
    started: datetime,
    adapter_type: str = "",
) -> RuntimeAdapterResult:
    return RuntimeAdapterResult(
        success=False,
        stdout="",
        stderr=error_text,
        output_text="",
        exit_code=1,
        error_code=error_code,
        error_text=error_text,
        started_at=started,
        completed_at=_now(),
        adapter_metadata={"adapter_type": adapter_type, "cli_bridge": True},
    )


class CliRuntimeAdapter(BaseRuntimeAdapter):
    """Generic bridge: executes a CLI adapter and normalises the result.

    Subclasses set ``adapter_type`` to the CLI adapter_type string.
    All execution logic lives here; subclasses carry zero additional code.

    Credential note:
        CLI adapters use CredentialBroker (login-state grants), not
        ModelProvider / Credential.secret_ref. ctx.resolved_credentials is
        ignored; the broker handles subprocess env injection.
    """

    adapter_type: str  # set by subclass

    requires_credentials = False   # broker-based, not ModelProvider API key
    requires_file_access = True    # CLI reads/writes workspace files
    supports_sandboxed_execution = True
    uses_model_config = False
    model_config_behavior = "not_applicable"
    model_config_note = (
        "CLI adapter uses the tool's own model selection. "
        "Model config is passed as --model flag if the tool supports it."
    )

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = _now()

        # Resolve credential grant via CredentialBroker.
        # Returns None if no profile is configured — adapter falls back to
        # whatever CLI auth state exists in the execution environment.
        credential_grant = None
        try:
            credential_grant = self._resolve_credential_grant(ctx)
        except Exception:
            log.warning(
                "CredentialBroker.grant_for_run failed run=%s adapter=%s; proceeding without grant",
                ctx.run_id,
                self.adapter_type,
                exc_info=True,
            )

        # Instantiate the CLI adapter via the internal factory.
        try:
            cli_adapter = _resolve_cli_adapter(
                adapter_type=self.adapter_type,
                sandbox_dir=ctx.sandbox_cwd,
                credential_grant=credential_grant,
                model=ctx.model_name or ctx.adapter_config.get("model"),
            )
        except KeyError:
            return _fail(
                "cli_adapter_not_registered",
                f"No CLI adapter factory is registered for adapter_type='{self.adapter_type}'",
                started=started,
                adapter_type=self.adapter_type,
            )

        if not cli_adapter.is_available():
            return _fail(
                "cli_adapter_not_available",
                (
                    f"CLI tool for '{self.adapter_type}' is not installed or not reachable. "
                    "Install the tool and ensure it is in PATH."
                ),
                started=started,
                adapter_type=self.adapter_type,
            )

        timeout = int(ctx.adapter_config.get("timeout", 300))
        try:
            result = cli_adapter.run(
                prompt=ctx.prompt,
                context=ctx.context_package,
                workspace_path=ctx.sandbox_cwd,
                timeout=timeout,
            )
        except Exception as exc:
            log.exception(
                "CLI adapter raised an exception run=%s adapter=%s",
                ctx.run_id,
                self.adapter_type,
            )
            return _fail(
                "cli_adapter_exception",
                str(exc)[:2000],
                started=started,
                adapter_type=self.adapter_type,
            )
        finally:
            # Clean up the per-run temp HOME the broker may have created.
            if credential_grant is not None and getattr(credential_grant, "temp_home", None):
                try:
                    from ...credentials.broker import CredentialBroker
                    CredentialBroker().cleanup_temp_home(ctx.run_id)
                except Exception:
                    log.warning(
                        "CredentialBroker.cleanup_temp_home failed run=%s", ctx.run_id
                    )

        completed = result.completed_at or _now()
        return RuntimeAdapterResult(
            success=result.success,
            stdout=result.output or "",
            stderr=result.error or "",
            output_text=result.output or "",
            exit_code=result.exit_code,
            error_text=result.error if not result.success else None,
            error_code="cli_adapter_failed" if not result.success else None,
            started_at=result.started_at or started,
            completed_at=completed,
            adapter_metadata={"adapter_type": self.adapter_type, "cli_bridge": True},
            adapter_log_json={
                "cli_adapter_type": self.adapter_type,
                "sandbox_cwd": ctx.sandbox_cwd,
                "exit_code": result.exit_code,
            },
        )

    def _resolve_credential_grant(self, ctx: RuntimeExecutionContext):
        from ...credentials.broker import CredentialBroker
        broker = CredentialBroker()
        return broker.grant_for_run(
            run_id=ctx.run_id,
            runtime=self.adapter_type,
            risk_level="low",
            executor_mode="worktree",
        )


# ---------------------------------------------------------------------------
# Concrete subclasses — one per CLI adapter type, adapter_type only
# ---------------------------------------------------------------------------

class ClaudeCodeRuntimeAdapter(CliRuntimeAdapter):
    """Canonical runtime bridge for the claude_code CLI adapter."""
    adapter_type = "claude_code"


class CodexCliRuntimeAdapter(CliRuntimeAdapter):
    """Canonical runtime bridge for the codex_cli adapter."""
    adapter_type = "codex_cli"


# ---------------------------------------------------------------------------
# Internal CLI adapter factory
# The ONLY place in app.runtimes that imports CLI adapter implementations.
# RunExecutionService and the registry never import them directly.
# ---------------------------------------------------------------------------

def _resolve_cli_adapter(
    *,
    adapter_type: str,
    sandbox_dir: str | None,
    credential_grant: Any,
    model: str | None,
):
    """Return an instantiated AgentAdapter for the given adapter_type.

    Raises KeyError if the adapter_type is not registered here.
    """
    if adapter_type in ("claude_code", "claude_cli"):
        from ...cli_adapters.claude import ClaudeCLIAdapter
        return ClaudeCLIAdapter(
            sandbox_dir=sandbox_dir,
            credential_grant=credential_grant,
            model=model,
        )
    if adapter_type == "codex_cli":
        from ...cli_adapters.codex import CodexCLIAdapter
        return CodexCLIAdapter(
            sandbox_dir=sandbox_dir,
            credential_grant=credential_grant,
        )
    raise KeyError(adapter_type)
