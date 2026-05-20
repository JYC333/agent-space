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

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db_uow import UnitOfWork
from ..models import AgentVersion, MemoryEntry, Run
from .types import RuntimeExecutionResult
from ..runtimes.base import RuntimeAdapterResult, RuntimeExecutionContext
from ..runtimes.credentials import (
    CredentialResolutionError,
    resolve_runtime_credentials,
    sanitize_runtime_config,
)
from ..runtimes.registry import instantiate_runtime_adapter
from ..personal_memory_grants.egress_guard import PersonalMemoryEgressError
from .adapter_resolution import AdapterResolutionError, resolve_runtime_adapter
from .artifact_persistence import ArtifactPersistenceService
from .context_snapshot_populator import ContextSnapshotPopulator
from .produced_artifact_path_ingestion import ingest_produced_artifact_paths
from .redaction import (
    redact_adapter_error,
    redact_artifact_content,
    redact_error,
    redact_runtime_output,
    sanitize_runtime_metadata,
)
from .run_output_materialization import RunOutputMaterializer
from .runtime_policy import compute_runtime_policy_decision
from .sandbox_manager import execution_workspace
from .removed_runtime_token import is_obsolete_runtime_override_token
from .task_output_linkage import link_run_outputs_to_tasks

log = logging.getLogger(__name__)

_PERSONAL_CONTEXT_HEADER = "[Personal context granted for this run - reasoning only]"
_PERSONAL_CONTEXT_FOOTER = "[End personal context]"
_PERSONAL_CONTEXT_WARNING = (
    "This personal context is granted for reasoning only. "
    "Do not quote or persist it directly."
)


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


def _build_runtime_prompt(*, user_prompt: str, personal_context_block: str | None) -> str:
    """Render the adapter prompt. Personal context is runtime-only."""
    block = (personal_context_block or "").strip()
    if not block:
        return user_prompt
    return "\n\n".join([
        user_prompt,
        _PERSONAL_CONTEXT_HEADER,
        _PERSONAL_CONTEXT_WARNING,
        block,
        _PERSONAL_CONTEXT_FOOTER,
    ])


def _personal_context_output_metadata(run: Run) -> dict:
    if not getattr(run, "has_personal_grant_context", False):
        return {}
    grant_ctx = getattr(run, "personal_grant_context_json", None) or {}
    grant_id = grant_ctx.get("grant_id") if isinstance(grant_ctx, dict) else None
    grant_ids = [grant_id] if grant_id else []
    return {
        "derived_from_personal_memory": True,
        "personal_memory_grant_ids": grant_ids,
        "raw_private_memory_included": False,
        "personal_summary_persisted": False,
    }


def _redact_personal_context_block(value: Any, personal_context_block: str | None) -> Any:
    block = (personal_context_block or "").strip()
    if not block:
        return value
    if isinstance(value, str):
        return value.replace(block, "[REDACTED_PERSONAL_CONTEXT_BLOCK]")
    if isinstance(value, list):
        return [_redact_personal_context_block(item, block) for item in value]
    if isinstance(value, tuple):
        return [_redact_personal_context_block(item, block) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _redact_personal_context_block(item, block)
            for key, item in value.items()
        }
    return value


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
        from .steps import (
            complete_step,
            create_step,
            fail_step,
            record_artifact_step,
            resolve_run_actor,
        )

        try:
            actor = resolve_run_actor(self.db, run)
            actor_id: str | None = actor.id
        except Exception:
            log.warning("resolve_run_actor failed for run %s; RunStep emission skipped", run.id)
            actor_id = None

        def _emit(step_type: str, status: str, **kwargs) -> None:
            if actor_id is None:
                return
            try:
                with UnitOfWork(self.db).savepoint():
                    create_step(
                        self.db, run=run, actor_id=actor_id,
                        step_type=step_type, status=status, **kwargs,
                    )
            except Exception:
                log.warning(
                    "RunStep write failed (best-effort) run=%s step=%s",
                    run.id, step_type, exc_info=True,
                )

        _emit("queued", "succeeded", title="Run picked up for execution")

        if decision.required_sandbox_level == "one_shot_docker":
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                actor_id=actor_id,
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
                actor_id=actor_id,
                error_code=exc.error_code,
                error_text=exc.message,
                stdout="",
                stderr="",
            )

        # Resolve credentials through the canonical boundary before execution.
        # If the adapter requires credentials and none are configured, fail early
        # with a sanitized error — never fall back to env vars.
        try:
            resolved_credentials = resolve_runtime_credentials(
                self.db,
                runtime_adapter_row=resolved.runtime_adapter_row,
                version=version,
                run_model_provider_id=run.model_provider_id,
            )
        except CredentialResolutionError as exc:
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                actor_id=actor_id,
                error_code="credentials_missing",
                error_text=str(exc),
                stdout="",
                stderr="",
            )

        _emit(
            "runtime_selected", "succeeded",
            title=f"Runtime adapter selected: {resolved.adapter_type}",
            runtime_adapter_id=(
                resolved.runtime_adapter_row.id if resolved.runtime_adapter_row else None
            ),
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

        # Populate ContextSnapshot before execution.  Every executed Run must
        # have an auditable snapshot; failure here is a hard pre-execution guard
        # that blocks the adapter and marks the run failed.
        try:
            context_pkg = ContextSnapshotPopulator(self.db).populate(run, version)
        except Exception as exc:  # noqa: BLE001
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                actor_id=actor_id,
                error_code="context_snapshot_population_failed",
                error_text=f"ContextSnapshot population failed: {exc}"[:2000],
                stdout="",
                stderr=str(exc)[:4000],
            )

        _emit("context_prepared", "succeeded", title="Execution context prepared")

        adapter = instantiate_runtime_adapter(resolved.adapter_type)

        adapter_step = None
        if actor_id is not None:
            try:
                with UnitOfWork(self.db).savepoint():
                    adapter_step = create_step(
                        self.db, run=run, actor_id=actor_id,
                        step_type="adapter_started", status="running",
                        title=f"Adapter executing: {resolved.adapter_type}",
                        started_at=started_wall,
                        runtime_adapter_id=(
                            resolved.runtime_adapter_row.id if resolved.runtime_adapter_row else None
                        ),
                    )
            except Exception:
                log.warning(
                    "RunStep write failed (best-effort) run=%s step=adapter_started",
                    run.id, exc_info=True,
                )

        raw: RuntimeAdapterResult | None = None
        path_ingest_errors: list[str] = []
        run_id = run.id
        run_space_id = run.space_id
        run_mode = run.mode
        try:
            self.db.commit()
            with execution_workspace(
                space_id=run_space_id,
                run_id=run_id,
                required_sandbox_level=decision.required_sandbox_level,
            ) as workdir:
                if decision.required_sandbox_level == "worktree":
                    run.sandbox_path = workdir
                    self.db.add(run)
                    self.db.commit()

                # Sanitize merged_config: strip raw secret fields so adapter_config
                # is safe to log and inspect.  Credentials flow via resolved_credentials.
                safe_config = sanitize_runtime_config(resolved.merged_config)
                runtime_prompt = _build_runtime_prompt(
                    user_prompt=user_prompt,
                    personal_context_block=context_pkg.personal_context_block,
                )
                resolved_model_name = version.model_name
                if run.model_override_json and run.model_override_json.get("model"):
                    resolved_model_name = run.model_override_json["model"]
                ctx = RuntimeExecutionContext(
                    run_id=run_id,
                    space_id=run_space_id,
                    prompt=runtime_prompt,
                    mode=run_mode,
                    sandbox_cwd=workdir,
                    model_name=resolved_model_name,
                    system_prompt=version.system_prompt,
                    adapter_config=safe_config,
                    instruction=run.instruction,
                    project_id=run.project_id,
                    workspace_id=run.workspace_id,
                    capability_id=run.capability_id,
                    simulate_failure=simulate_failure,
                    resolved_credentials=resolved_credentials,
                )
                self.db.commit()
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
            safe_exc = redact_adapter_error(str(exc)[:2000]) or ""
            safe_exc_long = redact_adapter_error(str(exc)[:4000]) or ""
            if adapter_step is not None:
                try:
                    with UnitOfWork(self.db).savepoint():
                        fail_step(
                            self.db, adapter_step,
                            error_type="adapter_runtime_error",
                            error_message=safe_exc,
                            ended_at=_utcnow(),
                        )
                except Exception:
                    log.warning("RunStep fail_step failed (best-effort)", exc_info=True)
            return self._fail_run_terminal(
                run=run,
                decision=decision,
                actor_id=actor_id,
                error_code="adapter_runtime_error",
                error_text=safe_exc,
                stdout="",
                stderr=safe_exc_long,
            )

        run.sandbox_path = None
        self.db.add(run)
        self.db.flush()

        ended_wall = _utcnow()
        if raw.success:
            output_provenance = _personal_context_output_metadata(run)
            safe_adapter_output = _redact_personal_context_block(
                raw.output_json,
                context_pkg.personal_context_block,
            )
            safe_stdout = _redact_personal_context_block(
                raw.stdout,
                context_pkg.personal_context_block,
            )
            safe_stderr = _redact_personal_context_block(
                raw.stderr,
                context_pkg.personal_context_block,
            )
            safe_output_text_for_run = _redact_personal_context_block(
                raw.output_text,
                context_pkg.personal_context_block,
            )
            safe_adapter_log = _redact_personal_context_block(
                raw.adapter_log_json,
                context_pkg.personal_context_block,
            )
            safe_adapter_metadata = _redact_personal_context_block(
                raw.adapter_metadata,
                context_pkg.personal_context_block,
            )
            run.status = "succeeded"
            run.error_message = None
            run.error_json = None
            run.exit_code = raw.exit_code if raw.exit_code is not None else 0
            run.ended_at = ended_wall
            run.updated_at = ended_wall
            out = {
                "runtime": "real",
                "runtime_adapter_type": resolved.adapter_type,
                "stdout": safe_stdout,
                "stderr": safe_stderr,
                "output_text": safe_output_text_for_run,
                "output_json": safe_adapter_output,
                "adapter_log_json": safe_adapter_log,
                "adapter_metadata": safe_adapter_metadata,
                "runtime_policy_decision": decision.policy_snapshot,
                "required_sandbox_level": run.required_sandbox_level,
            }
            if output_provenance:
                out["output_provenance"] = output_provenance
            # Redact before persistence — catches any accidental secret exposure
            # in adapter output, stderr, or log fields.
            run.output_json = redact_runtime_output(out)
            self.db.flush()

            if adapter_step is not None:
                try:
                    with UnitOfWork(self.db).savepoint():
                        complete_step(
                            self.db, adapter_step,
                            ended_at=ended_wall,
                            output_summary=(safe_output_text_for_run or "")[:4000] or None,
                        )
                except Exception:
                    log.warning("RunStep complete_step failed (best-effort)", exc_info=True)

            mat_errors = RunOutputMaterializer(self.db).materialize(
                run=run,
                adapter_output=safe_adapter_output,
                adapter_type=resolved.adapter_type,
            )
            merged_errors = [*path_ingest_errors, *mat_errors]
            if merged_errors:
                merged = dict(run.output_json or {})
                merged["materialization_errors"] = merged_errors
                # Re-apply redaction: materialization_errors strings are internal
                # but output_json must always be fully sanitized before persistence.
                run.output_json = redact_runtime_output(merged)
                self.db.flush()

            if raw.output_text:
                # Redact artifact content before persistence — adapter output text
                # must not carry raw credentials into artifact storage.
                safe_output_text = redact_artifact_content(safe_output_text_for_run) or ""
                try:
                    art = ArtifactPersistenceService(self.db).persist_text_file(
                        run=run,
                        text=safe_output_text,
                        title=f"Run output ({resolved.adapter_type})",
                        artifact_type="runtime_output",
                        preview=run.mode == "dry_run",
                    )
                except PersonalMemoryEgressError as exc:
                    merged = dict(run.output_json or {})
                    existing_errors = list(merged.get("materialization_errors") or [])
                    existing_errors.append(f"runtime_output_artifact: {exc}")
                    merged["materialization_errors"] = existing_errors
                    run.output_json = redact_runtime_output(merged)
                    self.db.flush()
                    artifacts_out = []
                else:
                    link_run_outputs_to_tasks(self.db, run=run, artifact=art, proposal=None)
                    artifacts_out = [{"id": art.id, "title": art.title, "storage_path": art.storage_path}]
                    if actor_id is not None:
                        try:
                            with UnitOfWork(self.db).savepoint():
                                record_artifact_step(
                                    self.db, run=run, actor_id=actor_id,
                                    artifact_id=art.id, title=art.title,
                                )
                        except Exception:
                            log.warning("RunStep record_artifact_step failed (best-effort)", exc_info=True)
            else:
                artifacts_out = []

            _emit("completed", "succeeded", title="Run completed successfully")
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

        safe_error_text = redact_adapter_error(raw.error_text or "adapter failed") or "adapter failed"
        if adapter_step is not None:
            try:
                with UnitOfWork(self.db).savepoint():
                    fail_step(
                        self.db, adapter_step,
                        error_type=raw.error_code,
                        error_message=safe_error_text,
                        ended_at=ended_wall,
                    )
            except Exception:
                log.warning("RunStep fail_step failed (best-effort)", exc_info=True)

        run.status = "failed"
        run.error_message = safe_error_text[:2000]
        run.error_json = redact_runtime_output({
            "error_code": raw.error_code or "adapter_failed",
            "error_text": safe_error_text,
            "runtime_adapter_type": resolved.adapter_type,
        })
        run.exit_code = raw.exit_code if raw.exit_code is not None else 1
        run.ended_at = ended_wall
        run.updated_at = ended_wall
        run.output_json = redact_runtime_output({
            "runtime": "real",
            "runtime_adapter_type": resolved.adapter_type,
            "stdout": raw.stdout,
            "stderr": raw.stderr,
            "adapter_log_json": raw.adapter_log_json,
            "runtime_policy_decision": decision.policy_snapshot,
            "required_sandbox_level": run.required_sandbox_level,
        })
        _emit(
            "failed", "failed",
            title=f"Run failed ({resolved.adapter_type})",
            error_type=raw.error_code,
            error_message=run.error_message,
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
        actor_id: str | None = None,
        error_code: str,
        error_text: str,
        stdout: str,
        stderr: str,
    ) -> RuntimeExecutionResult:
        from .steps import create_step

        now = _utcnow()
        # Redact before all persistence — error_text may carry adapter exception
        # messages that include raw credentials.
        safe_error_text = redact_error(error_text) or error_text
        run.status = "failed"
        run.error_message = safe_error_text[:2000]
        run.error_json = redact_runtime_output(
            {"error_code": error_code, "error_text": safe_error_text}
        )
        run.exit_code = 1
        run.started_at = run.started_at or now
        run.ended_at = now
        run.updated_at = now
        run.output_json = redact_runtime_output({
            "runtime": "real",
            "stdout": stdout,
            "stderr": stderr,
            "runtime_policy_decision": decision.policy_snapshot,
            "required_sandbox_level": run.required_sandbox_level,
        })
        self.db.add(run)
        if actor_id is not None:
            try:
                with UnitOfWork(self.db).savepoint():
                    create_step(
                        self.db, run=run, actor_id=actor_id,
                        step_type="failed", status="failed",
                        title="Run failed",
                        error_type=error_code,
                        error_message=safe_error_text[:2000],
                    )
            except Exception:
                log.warning(
                    "RunStep write failed (best-effort) run=%s step=failed",
                    run.id, exc_info=True,
                )
        self.db.commit()
        return RuntimeExecutionResult(
            success=False,
            output="",
            error=safe_error_text,
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
