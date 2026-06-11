"""Model API runtime adapter — in-process, provider-agnostic, no tools.

Executes a Run by making a single LLM call through the shared invocation primitive
(`providers.invocation.complete_text`): system prompt + user prompt -> text. No
filesystem, no sandbox, no tool calling. The provider + model are selected from the
Run's resolved ModelProvider (any vendor, including Anthropic — ADR 0010).

Credential rule: the decrypted key arrives via ``ctx.resolved_credentials["api_key"]``
(resolved by the execution service through the canonical boundary, after the
``runtime.use_credential`` policy gate). It is passed to litellm as a parameter and
never written to ``os.environ`` — so it cannot leak into a CLI subprocess.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ...providers import (
    CredentialResolutionError,
    ProviderUnavailableError,
    UnsupportedProviderError,
    complete_text,
)
from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext


class ModelApiRuntimeAdapter(BaseRuntimeAdapter):
    adapter_type = "model_api"
    requires_credentials = True
    requires_file_access = False
    supports_sandboxed_execution = False
    uses_cli_credentials = False
    uses_model_config = True
    model_config_behavior = "uses_model"
    model_config_note = (
        "Calls the configured ModelProvider + model via the shared in-process "
        "invocation primitive. No tools, no filesystem."
    )

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = datetime.now(UTC)

        if not ctx.model_provider_id:
            return self._failure(
                started,
                "model_provider_required",
                "model_api adapter requires a resolved ModelProvider; none is configured for this run.",
            )
        if ctx.db is None:
            return self._failure(
                started,
                "model_provider_session_required",
                "model_api adapter requires a database session for provider invocation.",
            )
        api_key = ctx.resolved_credentials.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            return self._failure(
                started,
                "credentials_missing",
                "model_api adapter requires provider API credentials resolved through run execution.",
            )

        try:
            result = complete_text(
                ctx.db,
                provider_id=ctx.model_provider_id,
                model=ctx.model_name,
                system=ctx.system_prompt or "",
                user=ctx.prompt or "",
                api_key=api_key,
            )
        except (ProviderUnavailableError, UnsupportedProviderError) as exc:
            return self._failure(started, exc.error_code, str(exc))
        except CredentialResolutionError as exc:
            return self._failure(started, "credentials_missing", str(exc))
        except Exception as exc:  # noqa: BLE001 — surface provider/network failures as a failed run
            return self._failure(started, "model_api_call_failed", f"Model API call failed: {exc}")

        ended = datetime.now(UTC)
        return RuntimeAdapterResult(
            success=True,
            stdout=result.text,
            output_text=result.text,
            output_json={
                "adapter_type": self.adapter_type,
                "model": result.model,
                "usage": result.usage,
            },
            exit_code=0,
            started_at=started,
            completed_at=ended,
            adapter_metadata={"adapter_type": self.adapter_type, "model": result.model},
        )

    def _failure(self, started: datetime, error_code: str, message: str) -> RuntimeAdapterResult:
        return RuntimeAdapterResult(
            success=False,
            stdout="",
            stderr=message,
            output_text="",
            exit_code=1,
            error_text=message,
            error_code=error_code,
            started_at=started,
            completed_at=datetime.now(UTC),
            adapter_metadata={"adapter_type": self.adapter_type},
        )
