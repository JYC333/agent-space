"""Anthropic Messages API runtime adapter (non-interactive, no PTY).

Credential rule (M4):
  API key is read from ``ctx.resolved_credentials["api_key"]``.
  Direct reads from ``ctx.adapter_config["api_key"]`` or the
  ``ANTHROPIC_API_KEY`` environment variable are not performed.
  Configure a ModelProvider row linked to the RuntimeAdapter or AgentVersion
  to supply credentials through the canonical boundary.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext

log = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Convert SDK model objects to JSON-column-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    return str(value)


class AnthropicMessagesRuntimeAdapter(BaseRuntimeAdapter):
    adapter_type = "anthropic_messages"
    requires_credentials = True
    requires_file_access = False
    supports_sandboxed_execution = False

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = datetime.now(UTC)
        if ctx.simulate_failure:
            ended = datetime.now(UTC)
            return RuntimeAdapterResult(
                success=False,
                stderr="simulated failure",
                error_text="AnthropicMessagesRuntimeAdapter: simulated failure",
                error_code="simulated_failure",
                started_at=started,
                completed_at=ended,
                exit_code=1,
                adapter_metadata={"adapter_type": self.adapter_type},
            )

        # Credentials come from ctx.resolved_credentials — never from adapter_config
        # or environment variables.  The execution service calls the credential
        # resolver before building this context.
        api_key = (ctx.resolved_credentials.get("api_key") or "").strip()
        if not api_key:
            ended = datetime.now(UTC)
            return RuntimeAdapterResult(
                success=False,
                error_text=(
                    "Anthropic API key is not configured. "
                    "Link a ModelProvider with an encrypted API key to the RuntimeAdapter "
                    "or AgentVersion row to supply credentials through the canonical boundary."
                ),
                error_code="credentials_missing",
                started_at=started,
                completed_at=ended,
                exit_code=2,
                adapter_metadata={"adapter_type": self.adapter_type},
            )

        # adapter_config holds non-secret settings (model, max_tokens, etc.).
        # api_key is intentionally not present here after M4 sanitization.
        cfg = dict(ctx.adapter_config or {})
        model = (
            (cfg.get("model") or "").strip()
            or (ctx.model_name or "").strip()
            or "claude-haiku-4-5-20251001"
        )
        max_tokens = int(cfg.get("max_tokens") or 256)
        user_prompt = ctx.prompt or "Say OK."
        sys_prompt = (ctx.system_prompt or cfg.get("system_prompt") or "").strip() or None

        adapter_log: dict[str, Any] = {
            "adapter_type": self.adapter_type,
            "model": model,
            "max_tokens": max_tokens,
        }

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if sys_prompt:
                kwargs["system"] = sys_prompt
            msg = client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — surface as run failure
            log.exception("anthropic_messages adapter failed")
            ended = datetime.now(UTC)
            return RuntimeAdapterResult(
                success=False,
                stderr=str(exc)[:4000],
                error_text=f"Anthropic request failed: {exc!s}"[:2000],
                error_code="adapter_runtime_error",
                started_at=started,
                completed_at=ended,
                exit_code=3,
                adapter_log_json=adapter_log,
                adapter_metadata={"adapter_type": self.adapter_type},
            )

        parts: list[str] = []
        for block in getattr(msg, "content", []) or []:
            txt = getattr(block, "text", None)
            if txt:
                parts.append(txt)
        output_text = "\n".join(parts).strip()
        ended = datetime.now(UTC)
        adapter_log["usage"] = _json_safe(getattr(msg, "usage", None))
        adapter_log["stop_reason"] = _json_safe(getattr(msg, "stop_reason", None))
        return RuntimeAdapterResult(
            success=True,
            stdout=output_text,
            stderr="",
            output_text=output_text,
            output_json={"adapter_type": self.adapter_type, "model": model},
            exit_code=0,
            started_at=started,
            completed_at=ended,
            adapter_log_json=adapter_log,
            adapter_metadata={"adapter_type": self.adapter_type, "model": model},
        )
