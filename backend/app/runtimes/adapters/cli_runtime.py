"""Spec-driven local CLI runtime adapter."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...memory import ContextCompiler, TargetFormat
from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
from ..command_renderer import CommandRenderError, render_command
from ..local_executor import LocalExecutor
from ..output_parsers import get_output_parser
from ..ports import RuntimeEvent
from ..specs import RuntimeAdapterSpec

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(
    error_code: str,
    error_text: str,
    *,
    started: datetime,
    adapter_type: str,
    extra_metadata: dict | None = None,
) -> RuntimeAdapterResult:
    metadata = {"adapter_type": adapter_type, "runtime_kind": "local_cli"}
    if extra_metadata:
        metadata.update(extra_metadata)
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
        adapter_metadata=metadata,
    )


class GenericCliRuntimeAdapter(BaseRuntimeAdapter):
    """Executes a local CLI from RuntimeAdapterSpec without shell=True."""

    def __init__(self, spec: RuntimeAdapterSpec, executor: LocalExecutor | None = None):
        if spec.runtime_kind != "local_cli":
            raise ValueError(f"GenericCliRuntimeAdapter requires local_cli spec, got {spec.runtime_kind}")
        self.spec = spec
        self.adapter_type = spec.adapter_type
        self.executor = executor or LocalExecutor()
        self.requires_credentials = spec.credentials.credential_mode == "model_provider_api_key"
        self.requires_file_access = spec.sandbox.requires_file_access
        self.supports_sandboxed_execution = spec.sandbox.supports_worktree
        self.uses_cli_credentials = spec.credentials.credential_mode == "cli_profile"
        self.uses_model_config = spec.model.supports_model_override
        self.model_config_behavior = spec.model.model_config_behavior
        self.model_config_note = "Model override is rendered only when RuntimeAdapterSpec allows it."

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = _now()
        credential_grant = None
        cred_meta = self._credential_metadata(ctx)
        permission_requested = bool(ctx.adapter_config.get("permission_bypass"))
        permission_allowed = False
        if permission_requested:
            allowed_error = self._permission_bypass_error(ctx)
            if allowed_error:
                return _fail(
                    "permission_bypass_not_allowed",
                    allowed_error,
                    started=started,
                    adapter_type=self.adapter_type,
                    extra_metadata={
                        "permission_bypass_requested": True,
                        "permission_bypass_allowed": False,
                        "permission_bypass_used": False,
                    },
                )
            permission_allowed = True

        if self.uses_cli_credentials:
            try:
                credential_grant = self._resolve_credential_grant(ctx)
            except Exception:
                log.warning("CredentialBroker grant failed run=%s adapter=%s", ctx.run_id, self.adapter_type, exc_info=True)
                cred_meta.update({"broker_error": True, "fallback_used": True, "fallback_reason": "broker_error"})
            if credential_grant is None:
                if not cred_meta.get("fallback_reason"):
                    cred_meta["fallback_reason"] = "no_profile_configured"
                cred_meta["fallback_used"] = True
                self._record_credential_audit(ctx, cred_meta, action="grant_denied")
                return _fail(
                    "runtime_credential_profile_required",
                    f"Runtime adapter '{self.adapter_type}' requires an explicit credential profile.",
                    started=started,
                    adapter_type=self.adapter_type,
                    extra_metadata={
                        **cred_meta,
                        "permission_bypass_requested": permission_requested,
                        "permission_bypass_allowed": permission_allowed,
                        "permission_bypass_used": False,
                    },
                )
            cred_meta.update({
                "credential_source": "profile",
                "credential_profile_id": getattr(credential_grant, "profile_id", None),
                "profile_id": getattr(credential_grant, "profile_id", None),
                "temp_home_created": bool(getattr(credential_grant, "temp_home", None)),
                "cleanup_status": "pending" if getattr(credential_grant, "temp_home", None) else "not_needed",
            })

        compiled_context = self._render_context(ctx)
        if compiled_context is not None:
            self._record_context_render_event(ctx, compiled_context)

        try:
            rendered = render_command(
                spec=self.spec,
                prompt=ctx.prompt,
                mode=ctx.mode,
                model=ctx.model_name if self.spec.model.supports_model_override else None,
                permission_bypass=permission_requested,
                executable_path=ctx.adapter_config.get("executable_path"),
            )
        except CommandRenderError as exc:
            return _fail(
                exc.error_code,
                exc.message,
                started=started,
                adapter_type=self.adapter_type,
                extra_metadata={
                    "permission_bypass_requested": permission_requested,
                    "permission_bypass_allowed": permission_allowed,
                    "permission_bypass_used": False,
                },
            )

        timeout = int(ctx.adapter_config.get("timeout") or self.spec.limits.default_timeout_seconds)
        timeout = min(timeout, self.spec.limits.max_timeout_seconds)
        try:
            result = self.executor.run_command(
                command=rendered.argv,
                cwd=ctx.sandbox_cwd,
                timeout=timeout,
                env=getattr(credential_grant, "env", None) if credential_grant else None,
                run_id=ctx.run_id,
                stdin=rendered.stdin,
                process_registry=ctx.process_registry,
            )
        finally:
            if credential_grant is not None and getattr(credential_grant, "temp_home", None):
                try:
                    from ...credentials.broker import CredentialBroker
                    CredentialBroker().cleanup_temp_home(ctx.run_id)
                    cred_meta["cleanup_status"] = "ok"
                except Exception:
                    cred_meta["cleanup_status"] = "failed"
                    self._record_credential_audit(ctx, cred_meta, action="cleanup_failed")

        self._record_credential_audit(ctx, cred_meta, action="grant" if result.returncode == 0 else "grant_failed")
        parser = get_output_parser(self.spec.output.output_parser_type)
        parsed = parser.parse(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)
        completed = _now()
        success = result.returncode == 0 and not result.timed_out
        error_code = "cli_adapter_timeout" if result.timed_out else parsed.error_code
        permission_used = bool(rendered.permission_bypass_used)
        return RuntimeAdapterResult(
            success=success,
            stdout=parsed.redacted_stdout,
            stderr=parsed.redacted_stderr,
            output_text=parsed.output_text,
            output_json=parsed.output_json,
            exit_code=result.returncode,
            error_code=None if success else (error_code or "cli_adapter_failed"),
            error_text=None if success else (parsed.error_text or result.stderr),
            started_at=started,
            completed_at=completed,
            produced_artifact_paths=parsed.produced_artifact_paths,
            adapter_metadata={
                "adapter_type": self.adapter_type,
                "runtime_kind": "local_cli",
                "permission_bypass_requested": permission_requested,
                "permission_bypass_allowed": permission_allowed,
                "permission_bypass_used": permission_used,
                "context_file_type": self.spec.context.context_file_type,
                "rendered_in_sandbox": bool(compiled_context),
                **cred_meta,
            },
            adapter_log_json={
                "adapter_type": self.adapter_type,
                "command": rendered.redacted_argv,
                "exit_code": result.returncode,
                "timeout_seconds": timeout,
            },
        )

    def _render_context(self, ctx: RuntimeExecutionContext):
        if not self.spec.context.writes_vendor_context_file:
            return None
        if not ctx.sandbox_cwd:
            raise RuntimeError("CLI context rendering requires a sandbox/worktree directory")
        target = TargetFormat(self.spec.context.context_target_format)
        return ContextCompiler().compile(
            context=ctx.context_package,
            target=target,
            task_goal=ctx.prompt,
            sandbox_dir=ctx.sandbox_cwd,
        )

    def _permission_bypass_error(self, ctx: RuntimeExecutionContext) -> str | None:
        if not self.spec.permissions.supports_permission_bypass:
            return f"Runtime adapter '{self.adapter_type}' does not support permission bypass."
        policy = ctx.adapter_config.get("runtime_policy_json") or {}
        policy_key = self.spec.permissions.permission_bypass_policy_key or "allow_permission_bypass"
        if not isinstance(policy, dict) or policy.get(policy_key) is not True:
            return f"runtime_policy_json.{policy_key}=true is required for permission bypass."
        if ctx.risk_level not in {"high", "critical"}:
            return "Permission bypass requires risk_level high or critical."
        if ctx.executor_mode != "worktree" or not ctx.workspace_id or not ctx.sandbox_cwd:
            return "Permission bypass requires an existing worktree workspace."
        return None

    def _resolve_credential_grant(self, ctx: RuntimeExecutionContext):
        from ...credentials.broker import CredentialBroker
        broker = CredentialBroker()
        profile_id = ctx.adapter_config.get("credential_profile_id")
        return broker.grant_for_run(
            run_id=ctx.run_id,
            runtime=self.spec.credentials.credential_runtime_name or self.adapter_type,
            risk_level=ctx.risk_level,
            executor_mode=ctx.executor_mode,
            profile_id=profile_id,
        )

    def _credential_metadata(self, ctx: RuntimeExecutionContext) -> dict[str, Any]:
        return {
            "credential_checked": self.uses_cli_credentials,
            "credential_broker_used": self.uses_cli_credentials,
            "credential_source": "none",
            "credential_profile_id": ctx.adapter_config.get("credential_profile_id"),
            "temp_home_created": False,
            "fallback_used": False,
            "fallback_reason": None,
            "broker_error": False,
            "cleanup_status": "not_needed",
            "trigger_origin": ctx.trigger_origin,
        }

    def _record_context_render_event(self, ctx: RuntimeExecutionContext, compiled: Any) -> None:
        if ctx.event_sink is None:
            return
        try:
            ctx.event_sink.emit(RuntimeEvent(
                event_type="runtime_context_rendered",
                status="succeeded",
                workspace_id=ctx.workspace_id,
                metadata={
                    "context_snapshot_id": ctx.adapter_config.get("context_snapshot_id"),
                    "adapter_type": self.adapter_type,
                    "context_file_type": self.spec.context.context_file_type,
                    "context_target_format": self.spec.context.context_target_format,
                    "rendered_in_sandbox": True,
                    "instruction_file_path": getattr(compiled, "instruction_file_path", None),
                },
                log_context="runtime_context_rendered",
            ))
        except Exception:
            log.warning("context render event failed run=%s", ctx.run_id, exc_info=True)

    def _record_credential_audit(self, ctx: RuntimeExecutionContext, cred_meta: dict, *, action: str) -> None:
        if not self.uses_cli_credentials or ctx.db is None:
            return
        try:
            from ...credentials.broker import CredentialBroker, CredentialGrant
            grant = None
            profile_id = cred_meta.get("credential_profile_id") or cred_meta.get("profile_id")
            if cred_meta.get("credential_source") == "profile" and profile_id:
                grant = CredentialGrant(
                    profile_id=profile_id,
                    runtime=self.spec.credentials.credential_runtime_name or self.adapter_type,
                    executor_mode=ctx.executor_mode,
                    readonly=False,
                )
            CredentialBroker().record_usage(
                ctx.db,
                ctx.run_id,
                ctx.space_id,
                grant,
                runtime_adapter_type=self.adapter_type,
                trigger_origin=ctx.trigger_origin,
                fallback_used=bool(cred_meta.get("fallback_used")),
                fallback_reason=cred_meta.get("fallback_reason"),
                broker_error=bool(cred_meta.get("broker_error")),
                cleanup_status=cred_meta.get("cleanup_status", "not_needed"),
                action=action,
            )
        except Exception:
            log.warning("credential audit write failed run=%s", ctx.run_id, exc_info=True)
