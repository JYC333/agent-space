"""RunExecutionService — shared execution entrypoint.

Drives a queued Run to a terminal status via configured **real** runtime
adapters from ``app.runtimes.registry``. There is **no** automatic fallback when
a real adapter fails or is misconfigured.

Obsolete ``runtime`` query overrides are rejected: the HTTP execute route may
respond with **410 Gone**; this service returns ``error_code=runtime_removed``
**without** mutating the Run row when such an override is supplied (jobs should
reject the payload before execution).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..agents.base import RuntimeExecutionResult
from ..models import ActivityRecord, AgentVersion, MemoryEntry, Run
from ..runtimes.base import RuntimeAdapterResult, RuntimeExecutionContext
from ..runtimes.registry import instantiate_runtime_adapter
from .adapter_resolution import AdapterResolutionError, resolve_runtime_adapter
from .artifact_persistence import ArtifactPersistenceService
from .produced_artifact_path_ingestion import ingest_produced_artifact_paths
from .run_output_materialization import RunOutputMaterializer
from .runtime_policy import compute_runtime_policy_decision
from .sandbox_manager import execution_workspace
from .removed_runtime_token import is_obsolete_runtime_override_token
from .task_output_linkage import link_run_outputs_to_tasks


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_runtime(runtime: Optional[str]) -> Optional[str]:
    if runtime is None or runtime == "" or runtime == "auto":
        return None
    raise HTTPException(
        status_code=400,
        detail=(
            f"Unknown runtime {runtime!r}. Omit the parameter for normal adapter execution."
        ),
    )


def _assert_run_executable(run: Run) -> None:
    if run.status in ("succeeded", "failed", "degraded", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is already in terminal status '{run.status}'",
        )
    if run.status == "waiting_for_review":
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run.id}' is waiting for review and cannot be executed",
        )


def _append_run_execution_activity(
    db: Session,
    run: Run,
    *,
    activity_type: str,
    title: str,
    content: str,
) -> None:
    """Minimal durable audit trail for run execution (no HTTP / TestClient)."""
    from ulid import ULID

    now = _utcnow()
    db.add(
        ActivityRecord(
            id=str(ULID()),
            space_id=run.space_id,
            source_run_id=run.id,
            user_id=run.instructed_by_user_id,
            activity_type=activity_type,
            title=title,
            content=(content or "")[:8000],
            payload_json={},
            occurred_at=now,
            status="processed",
            updated_at=now,
        )
    )


class RunExecutionService:
    """Shared facade for executing a Run through a registered runtime."""

    def __init__(self, db: Session):
        self.db = db

    def execute_run(
        self,
        run_id: str,
        *,
        space_id: str,
        runtime: Optional[str] = None,
        mode: Optional[str] = None,
        prompt: Optional[str] = None,
        context_snapshot_id: Optional[str] = None,
        simulate_failure: bool = False,
    ) -> RuntimeExecutionResult:
        del mode, prompt, context_snapshot_id  # API parity; Run row is authoritative

        run = (
            self.db.query(Run)
            .filter(Run.id == run_id, Run.space_id == space_id)
            .first()
        )
        if not run:
            raise HTTPException(
                status_code=404,
                detail=f"Run '{run_id}' not found in this space",
            )

        version = (
            self.db.query(AgentVersion)
            .filter(AgentVersion.id == run.agent_version_id)
            .first()
        )
        if not version:
            raise HTTPException(
                status_code=400,
                detail="Run has no resolvable AgentVersion for policy checks",
            )

        _assert_run_executable(run)

        if is_obsolete_runtime_override_token(runtime):
            return RuntimeExecutionResult(
                success=False,
                output="",
                error=(
                    "Obsolete runtime override is not supported; omit the override or "
                    "use a configured adapter (see runtime_policy_json.default_adapter_type)."
                ),
                exit_code=1,
                artifacts=[],
                started_at=None,
                completed_at=None,
                stdout="",
                stderr="",
                error_code="runtime_removed",
            )

        policy_dict = dict(version.runtime_policy_json or {})
        decision = compute_runtime_policy_decision(run=run, version=version)
        run.required_sandbox_level = decision.required_sandbox_level
        self.db.add(run)
        self.db.flush()

        _normalize_runtime(runtime)

        return self._execute_real_adapter_path(
            run=run,
            version=version,
            policy_dict=policy_dict,
            decision=decision,
            simulate_failure=simulate_failure,
        )

    def _execute_real_adapter_path(
        self,
        *,
        run: Run,
        version: AgentVersion,
        policy_dict: dict,
        decision,
        simulate_failure: bool,
    ) -> RuntimeExecutionResult:
        if decision.required_sandbox_level == "one_shot_docker":
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                error_code="sandbox_one_shot_docker_not_implemented",
                error_text="required_sandbox_level=one_shot_docker is not implemented in this build",
                stdout="",
                stderr="",
            )

        try:
            resolved = resolve_runtime_adapter(
                self.db, run=run, version=version, policy=policy_dict
            )
        except AdapterResolutionError as exc:
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                error_code=exc.error_code,
                error_text=exc.message,
                stdout="",
                stderr="",
            )

        mem_before = (
            self.db.query(func.count(MemoryEntry.id))
            .filter(MemoryEntry.space_id == run.space_id, MemoryEntry.status == "active")
            .scalar()
        )

        started_wall = _utcnow()
        run.adapter_type = resolved.adapter_type
        run.status = "running"
        run.started_at = run.started_at or started_wall
        run.updated_at = started_wall
        self.db.add(run)
        self.db.flush()

        user_prompt = (run.prompt or "").strip() or "(empty prompt)"
        _append_run_execution_activity(
            self.db,
            run,
            activity_type="run.execution.started",
            title=f"Run execution started ({resolved.adapter_type})",
            content=user_prompt,
        )
        self.db.flush()

        adapter = instantiate_runtime_adapter(resolved.adapter_type)

        raw: RuntimeAdapterResult | None = None
        path_ingest_errors: list[str] = []
        try:
            with execution_workspace(
                space_id=run.space_id,
                run_id=run.id,
                required_sandbox_level=decision.required_sandbox_level,
            ) as workdir:
                if decision.required_sandbox_level == "worktree":
                    run.sandbox_path = workdir
                    self.db.add(run)
                    self.db.flush()

                ctx = RuntimeExecutionContext(
                    run_id=run.id,
                    space_id=run.space_id,
                    prompt=user_prompt,
                    mode=run.mode,
                    sandbox_cwd=workdir,
                    model_name=version.model_name,
                    system_prompt=version.system_prompt,
                    adapter_config=resolved.merged_config,
                    simulate_failure=simulate_failure,
                )
                raw = adapter.execute(ctx)
                if (
                    raw is not None
                    and raw.success
                    and getattr(raw, "produced_artifact_paths", None)
                ):
                    path_ingest_errors = ingest_produced_artifact_paths(
                        self.db,
                        run=run,
                        source_root=workdir,
                        entries=raw.produced_artifact_paths,
                    )
        except Exception as exc:  # noqa: BLE001
            run.sandbox_path = None
            self.db.add(run)
            self.db.flush()
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                error_code="adapter_runtime_error",
                error_text=str(exc)[:2000],
                stdout="",
                stderr=str(exc)[:4000],
            )

        run.sandbox_path = None
        self.db.add(run)
        self.db.flush()

        ended_wall = _utcnow()
        if raw.success:
            run.status = "succeeded"
            run.error_message = None
            run.error_json = None
            run.exit_code = raw.exit_code if raw.exit_code is not None else 0
            run.ended_at = ended_wall
            run.updated_at = ended_wall
            out = {
                "runtime": "real",
                "runtime_adapter_type": resolved.adapter_type,
                "stdout": raw.stdout,
                "stderr": raw.stderr,
                "output_text": raw.output_text,
                "output_json": raw.output_json,
                "adapter_log_json": raw.adapter_log_json,
                "adapter_metadata": raw.adapter_metadata,
                "runtime_policy_decision": decision.policy_snapshot,
                "required_sandbox_level": run.required_sandbox_level,
            }
            run.output_json = out
            self.db.flush()

            mat_errors = RunOutputMaterializer(self.db).materialize(
                run=run,
                adapter_output=raw.output_json,
                adapter_type=resolved.adapter_type,
            )
            merged_errors = [*path_ingest_errors, *mat_errors]
            if merged_errors:
                merged = dict(run.output_json or {})
                merged["materialization_errors"] = merged_errors
                run.output_json = merged
                self.db.flush()

            if raw.output_text:
                art = ArtifactPersistenceService(self.db).persist_text_file(
                    run=run,
                    text=raw.output_text,
                    title=f"Run output ({resolved.adapter_type})",
                    artifact_type="runtime_output",
                    preview=run.mode == "dry_run",
                )
                link_run_outputs_to_tasks(self.db, run=run, artifact=art, proposal=None)
                artifacts_out = [{"id": art.id, "title": art.title, "storage_path": art.storage_path}]
            else:
                artifacts_out = []

            _append_run_execution_activity(
                self.db,
                run,
                activity_type="run.execution.succeeded",
                title=f"Run execution succeeded ({resolved.adapter_type})",
                content=(raw.output_text or "")[:8000],
            )
            self.db.commit()
            self._assert_no_memory_writes(run.id, run.space_id, mem_before)

            return RuntimeExecutionResult(
                success=True,
                output=raw.output_text or "",
                error=None,
                exit_code=raw.exit_code,
                artifacts=artifacts_out,
                started_at=raw.started_at or run.started_at,
                completed_at=raw.completed_at or run.ended_at,
                stdout=raw.stdout,
                stderr=raw.stderr,
                error_code=None,
                adapter_log_json=raw.adapter_log_json,
            )

        run.status = "failed"
        run.error_message = (raw.error_text or "adapter failed")[:2000]
        run.error_json = {
            "error_code": raw.error_code or "adapter_failed",
            "error_text": raw.error_text,
            "runtime_adapter_type": resolved.adapter_type,
        }
        run.exit_code = raw.exit_code if raw.exit_code is not None else 1
        run.ended_at = ended_wall
        run.updated_at = ended_wall
        run.output_json = {
            "runtime": "real",
            "runtime_adapter_type": resolved.adapter_type,
            "stdout": raw.stdout,
            "stderr": raw.stderr,
            "adapter_log_json": raw.adapter_log_json,
            "runtime_policy_decision": decision.policy_snapshot,
            "required_sandbox_level": run.required_sandbox_level,
        }
        _append_run_execution_activity(
            self.db,
            run,
            activity_type="run.execution.failed",
            title=f"Run execution failed ({resolved.adapter_type})",
            content=run.error_message or "",
        )
        self.db.commit()
        self._assert_no_memory_writes(run.id, run.space_id, mem_before)

        return RuntimeExecutionResult(
            success=False,
            output=raw.output_text or "",
            error=run.error_message,
            exit_code=run.exit_code,
            started_at=raw.started_at or run.started_at,
            completed_at=raw.completed_at or run.ended_at,
            stdout=raw.stdout,
            stderr=raw.stderr,
            error_code=raw.error_code,
            adapter_log_json=raw.adapter_log_json,
        )

    def _fail_run_terminal(
        self,
        *,
        run: Run,
        decision,
        error_code: str,
        error_text: str,
        stdout: str,
        stderr: str,
    ) -> RuntimeExecutionResult:
        now = _utcnow()
        run.status = "failed"
        run.error_message = error_text[:2000]
        run.error_json = {"error_code": error_code, "error_text": error_text}
        run.exit_code = 1
        run.started_at = run.started_at or now
        run.ended_at = now
        run.updated_at = now
        run.output_json = {
            "runtime": "real",
            "stdout": stdout,
            "stderr": stderr,
            "runtime_policy_decision": decision.policy_snapshot,
            "required_sandbox_level": run.required_sandbox_level,
        }
        self.db.add(run)
        _append_run_execution_activity(
            self.db,
            run,
            activity_type="run.execution.failed",
            title="Run execution failed",
            content=f"{error_code}: {error_text}",
        )
        self.db.commit()
        return RuntimeExecutionResult(
            success=False,
            output="",
            error=error_text,
            exit_code=1,
            started_at=run.started_at,
            completed_at=run.ended_at,
            stdout=stdout,
            stderr=stderr,
            error_code=error_code,
        )

    def _assert_no_memory_writes(self, run_id: str, space_id: str, mem_before: int) -> None:
        mem_after = (
            self.db.query(func.count(MemoryEntry.id))
            .filter(MemoryEntry.space_id == space_id, MemoryEntry.status == "active")
            .scalar()
        )
        if mem_after != mem_before:
            raise RuntimeError(
                "Run execution invariant violated: active MemoryEntry count changed during "
                f"run {run_id}; adapters must not write active memory directly."
            )
