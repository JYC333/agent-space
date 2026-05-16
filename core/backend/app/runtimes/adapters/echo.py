"""Echo runtime adapter — minimal in-process execution (tests / zero-deps)."""

from __future__ import annotations

from datetime import UTC, datetime

from ..base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext


class EchoRuntimeAdapter(BaseRuntimeAdapter):
    adapter_type = "echo"
    requires_credentials = False
    requires_file_access = False
    supports_sandboxed_execution = False

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        started = datetime.now(UTC)
        if ctx.simulate_failure:
            ended = datetime.now(UTC)
            return RuntimeAdapterResult(
                success=False,
                stdout="",
                stderr="simulated failure",
                output_text="",
                exit_code=1,
                error_text="EchoRuntimeAdapter: simulated failure",
                error_code="simulated_failure",
                started_at=started,
                completed_at=ended,
                adapter_metadata={"adapter_type": self.adapter_type},
            )
        text = ctx.prompt or ""
        body = f"echo:{text[:8000]}"
        ended = datetime.now(UTC)
        return RuntimeAdapterResult(
            success=True,
            stdout=body,
            stderr="",
            output_text=body,
            output_json={"adapter_type": self.adapter_type, "echo_length": len(text)},
            exit_code=0,
            started_at=started,
            completed_at=ended,
            adapter_metadata={"adapter_type": self.adapter_type},
        )
