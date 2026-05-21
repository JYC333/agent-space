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
    extra_metadata: dict | None = None,
) -> RuntimeAdapterResult:
    meta: dict = {"adapter_type": adapter_type, "cli_bridge": True}
    if extra_metadata:
        meta.update(extra_metadata)
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
        adapter_metadata=meta,
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

    requires_credentials = False    # broker-based, not ModelProvider API key
    requires_file_access = True     # CLI reads/writes workspace files
    supports_sandboxed_execution = True
    uses_cli_credentials = True     # authenticates via CredentialBroker login-state
    uses_model_config = False
    model_config_behavior = "not_applicable"
    model_config_note = (
        "CLI adapter uses the tool's own model selection. "
        "Model config is passed as --model flag if the tool supports it."
    )

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = _now()

        # Non-sensitive credential source metadata recorded for audit.
        # No keys, paths, session tokens, HOME paths, or raw profile paths captured here.
        cred_meta: dict[str, Any] = {
            "credential_checked": True,   # durable marker that broker check ran
            "credential_broker_used": True,
            "credential_source": "none",
            "temp_home_created": False,
            "fallback_used": False,
            "fallback_reason": None,
            "broker_error": False,        # True when broker raised, not just no-profile
            "cleanup_status": "not_needed",
            "trigger_origin": ctx.trigger_origin,
        }

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
            cred_meta["broker_error"] = True
            cred_meta["fallback_used"] = True
            cred_meta["fallback_reason"] = "broker_error"

        if credential_grant is None:
            cred_meta["credential_source"] = "container_default"
            cred_meta["fallback_used"] = True
            if cred_meta["fallback_reason"] is None:
                cred_meta["fallback_reason"] = "no_profile_configured"
        else:
            cred_meta["credential_source"] = "profile"
            cred_meta["profile_id"] = getattr(credential_grant, "profile_id", None)
            cred_meta["temp_home_created"] = bool(
                getattr(credential_grant, "temp_home", None)
            )
            if cred_meta["temp_home_created"]:
                cred_meta["cleanup_status"] = "pending"

        # Automation-origin runs must use an explicit credential profile.
        # Container-default fallback is not allowed for unattended execution —
        # it could silently pick up stale or shared auth state.
        # broker_error and no_profile_configured are exposed separately in
        # failure metadata so callers can distinguish configuration problems
        # from runtime broker failures.
        if ctx.trigger_origin == "automation" and credential_grant is None:
            failure_reason = cred_meta["fallback_reason"] or "no_profile_configured"
            self._record_credential_audit(ctx, cred_meta, action="automation_denied")
            return _fail(
                "runtime_credential_profile_required",
                (
                    "Automation-origin CLI runs require an explicit credential profile. "
                    f"No credential profile is configured for adapter_type='{self.adapter_type}'. "
                    "Configure a CredentialBroker profile before scheduling automation runs."
                ),
                started=started,
                adapter_type=self.adapter_type,
                extra_metadata={
                    "broker_error": cred_meta["broker_error"],
                    "no_profile_configured": not cred_meta["broker_error"],
                    "failure_reason": failure_reason,
                    "credential_checked": True,
                    "trigger_origin": ctx.trigger_origin,
                },
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
                run_id=ctx.run_id,
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
                    cred_meta["cleanup_status"] = "ok"
                except Exception:
                    log.warning(
                        "CredentialBroker.cleanup_temp_home failed run=%s", ctx.run_id
                    )
                    cred_meta["cleanup_status"] = "failed"
                    self._record_credential_audit(ctx, cred_meta, action="cleanup_failed")

        # Record durable credential usage audit event.
        action = "grant_failed" if not result.success else "grant"
        self._record_credential_audit(ctx, cred_meta, action=action)

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
            adapter_metadata={
                "adapter_type": self.adapter_type,
                "cli_bridge": True,
                **cred_meta,
            },
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
            risk_level=ctx.risk_level,
            executor_mode=ctx.executor_mode,
        )

    def _record_credential_audit(
        self,
        ctx: RuntimeExecutionContext,
        cred_meta: dict,
        *,
        action: str,
    ) -> None:
        """Write a CliCredentialEvent row when ctx.db is available (best-effort)."""
        if ctx.db is None:
            return
        try:
            from ...credentials.broker import CredentialBroker
            # Reconstruct a minimal grant object for record_usage only when source=profile.
            # We pass None for grant when fallback was used — broker.record_usage handles it.
            grant = None
            if cred_meta.get("credential_source") == "profile":
                # Build a minimal object so record_usage can read profile_id.
                from ...credentials.broker import CredentialGrant
                grant = CredentialGrant(
                    profile_id=cred_meta.get("profile_id", "unknown"),
                    runtime=self.adapter_type,
                    executor_mode=ctx.executor_mode,
                    readonly=False,
                )
            CredentialBroker().record_usage(
                ctx.db,
                ctx.run_id,
                ctx.space_id,
                grant,
                runtime_adapter_type=self.adapter_type,
                runtime_adapter_id=ctx.runtime_adapter_id,
                trigger_origin=ctx.trigger_origin,
                fallback_used=bool(cred_meta.get("fallback_used")),
                fallback_reason=cred_meta.get("fallback_reason"),
                broker_error=bool(cred_meta.get("broker_error")),
                cleanup_status=cred_meta.get("cleanup_status", "not_needed"),
                action=action,
            )
        except Exception:
            log.warning(
                "credential audit write failed (best-effort) run=%s", ctx.run_id, exc_info=True
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
    if adapter_type == "claude_code":
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
