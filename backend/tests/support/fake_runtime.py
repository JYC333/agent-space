"""In-process fake runtime adapter for tests (no network, FS, Docker, or LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext


def _reject_unsafe_sandbox_rel(rel: str) -> None:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"invalid sandbox_seed_files key {rel!r}")


@dataclass
class FakeRuntimeConfig:
    """Deterministic behaviour for :class:`ConfigurableFakeRuntimeAdapter`."""

    success: bool = True
    output_text: str = "fake-runtime-output"
    output_json: dict[str, Any] | None = field(default_factory=lambda: {"fake": True})
    stdout: str | None = None
    stderr: str = ""
    exit_code: int = 0
    error_text: str | None = None
    error_code: str | None = None
    produced_artifact_paths: list[Any] = field(default_factory=list)
    """Relative paths under ``ctx.sandbox_cwd`` created before adapter output (tests only)."""
    sandbox_seed_files: dict[str, str] = field(default_factory=dict)
    proposed_change: dict[str, Any] | None = None
    fixed_clock: datetime | None = None

    def resolved_started_at(self) -> datetime:
        return self.fixed_clock or datetime.now(UTC)

    def resolved_completed_at(self) -> datetime:
        return self.fixed_clock or datetime.now(UTC)


class ConfigurableFakeRuntimeAdapter(BaseRuntimeAdapter):
    """Returns configurable :class:`RuntimeAdapterResult` for execution tests."""

    adapter_type = "fake_test_runtime"

    def __init__(self, config: FakeRuntimeConfig | None = None) -> None:
        self.config = config or FakeRuntimeConfig()

    def _seed_sandbox(self, cwd: str | None) -> None:
        if not cwd or not self.config.sandbox_seed_files:
            return
        base = Path(cwd).resolve()
        for rel, body in self.config.sandbox_seed_files.items():
            _reject_unsafe_sandbox_rel(rel)
            target = (base / rel).resolve()
            target.relative_to(base)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        cfg = self.config
        started = cfg.resolved_started_at()
        completed = cfg.resolved_completed_at()
        self._seed_sandbox(ctx.sandbox_cwd)

        if ctx.simulate_failure:
            return RuntimeAdapterResult(
                success=False,
                stdout="",
                stderr="simulated failure",
                output_text="",
                output_json={"adapter_type": self.adapter_type, "simulate_failure": True},
                exit_code=1,
                error_text="ConfigurableFakeRuntimeAdapter: simulated failure",
                error_code="simulated_failure",
                started_at=started,
                completed_at=completed,
                produced_artifact_paths=list(cfg.produced_artifact_paths),
                adapter_metadata={"adapter_type": self.adapter_type},
            )

        if not cfg.success:
            return RuntimeAdapterResult(
                success=False,
                stdout=cfg.stdout or "",
                stderr=cfg.stderr,
                output_text="",
                output_json=cfg.output_json,
                exit_code=cfg.exit_code or 1,
                error_text=cfg.error_text or "fake runtime error",
                error_code=cfg.error_code or "fake_error",
                started_at=started,
                completed_at=completed,
                produced_artifact_paths=list(cfg.produced_artifact_paths),
                adapter_metadata={"adapter_type": self.adapter_type},
            )

        out_json = dict(cfg.output_json or {})
        out_json.setdefault("adapter_type", self.adapter_type)
        out_json["echo_prompt_len"] = len(ctx.prompt or "")
        if cfg.proposed_change is not None:
            out_json["proposed_change"] = cfg.proposed_change

        return RuntimeAdapterResult(
            success=True,
            stdout=cfg.stdout if cfg.stdout is not None else cfg.output_text,
            stderr=cfg.stderr,
            output_text=cfg.output_text,
            output_json=out_json,
            exit_code=cfg.exit_code,
            error_text=None,
            error_code=None,
            started_at=started,
            completed_at=completed,
            produced_artifact_paths=list(cfg.produced_artifact_paths),
            adapter_metadata={"adapter_type": self.adapter_type},
        )
