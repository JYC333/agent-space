"""TS agent-host runtime adapter.

This adapter is the Python-owned runs seam for the control-plane runtime host.
It maps ``RuntimeExecutionContext`` to the internal runtime-host contract and
maps the returned normalized host result back to ``RuntimeAdapterResult``. It
does not read or forward decrypted provider API keys; credential release happens
inside control-plane after Python has completed the metadata-only policy gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
from ..runtime_host_client import (
    RuntimeHostClientError,
    execute_runtime_host_via_control_plane,
)


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


class TsAgentHostRuntimeAdapter(BaseRuntimeAdapter):
    adapter_type = "ts_agent_host"
    requires_credentials = False
    requires_file_access = False
    supports_sandboxed_execution = False
    uses_cli_credentials = False
    uses_model_config = True
    model_config_behavior = "uses_model"
    model_config_note = (
        "Invokes the control-plane TS runtime host through the internal API. "
        "Runs remain Python-owned; provider credentials are brokered inside "
        "control-plane, not passed through this adapter."
    )

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = datetime.now(UTC)
        if not ctx.model_provider_id:
            return self._failure(
                started,
                "model_provider_required",
                "ts_agent_host adapter requires a resolved ModelProvider; none is configured for this run.",
            )

        payload: dict[str, Any] = {
            "run_id": ctx.run_id,
            "space_id": ctx.space_id,
            "model_provider_id": ctx.model_provider_id,
            "model": ctx.model_name,
            "system_prompt": ctx.system_prompt,
            "prompt": ctx.prompt or "",
            "mode": ctx.mode,
            "instruction": ctx.instruction,
            "project_id": ctx.project_id,
            "workspace_id": ctx.workspace_id,
            "capability_id": ctx.capability_id,
            "context_snapshot_id": (ctx.context_package or {}).get(
                "context_snapshot_id"
            ),
            "tool_mode": "disabled",
            "tool_bindings": [],
        }
        max_tokens = _positive_int((ctx.adapter_config or {}).get("max_tokens"))
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = execute_runtime_host_via_control_plane(payload)
        except RuntimeHostClientError as exc:
            return self._failure(started, "runtime_host_unavailable", str(exc))

        return self._from_response(response, started)

    def _from_response(
        self,
        response: dict[str, Any],
        started_fallback: datetime,
    ) -> RuntimeAdapterResult:
        success = bool(response.get("success"))
        output_json = response.get("output_json")
        if not isinstance(output_json, dict):
            output_json = {
                "adapter_type": self.adapter_type,
                "model": response.get("model"),
                "usage": response.get("usage"),
            }
        output_json.setdefault("adapter_type", self.adapter_type)

        metadata = response.get("adapter_metadata")
        if not isinstance(metadata, dict):
            metadata = {"adapter_type": self.adapter_type}
        metadata.setdefault("adapter_type", self.adapter_type)

        adapter_log_json = response.get("adapter_log_json")
        if not isinstance(adapter_log_json, dict):
            adapter_log_json = {}
        events = response.get("events")
        if isinstance(events, list):
            adapter_log_json.setdefault("model_events", events)

        return RuntimeAdapterResult(
            success=success,
            stdout=str(response.get("stdout") or ""),
            stderr=str(response.get("stderr") or ""),
            output_text=str(response.get("output_text") or ""),
            output_json=output_json,
            exit_code=(
                response.get("exit_code")
                if isinstance(response.get("exit_code"), int)
                else None
            ),
            error_text=(
                response.get("error_text")
                if isinstance(response.get("error_text"), str)
                else None
            ),
            error_code=(
                response.get("error_code")
                if isinstance(response.get("error_code"), str)
                else None
            ),
            started_at=_parse_dt(response.get("started_at"), started_fallback),
            completed_at=_parse_dt(response.get("completed_at"), datetime.now(UTC)),
            adapter_metadata=metadata,
            adapter_log_json=adapter_log_json or None,
        )

    def _failure(
        self, started: datetime, error_code: str, message: str
    ) -> RuntimeAdapterResult:
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
