"""Internal Python-owned context ports for TS run orchestration.

These routes are service-to-service boundaries only. They let the TypeScript
control-plane runs module call Python-owned contexts during Stage 4 without
making TS a backdoor writer for policy, memory/context, proposals, artifacts,
workspace/sandbox, or finalization hooks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..memory import ContextCompiler, TargetFormat
from ..models import AgentVersion, Run, Workspace
from ..policy import (
    PolicyAuditPersistError,
    PolicyCheckRequest,
    PolicyGateBlocked,
    get_policy_port,
    write_blocked_gate_audit,
)
from ..personal_memory_grants.egress_guard import PersonalMemoryEgressError
from ..runtimes.credentials import sanitize_runtime_config
from ..runtimes.requirements import (
    UnknownRuntimeRequirementsError,
    get_runtime_requirements,
)
from ..workspace.disk_path import workspace_absolute_root
from ..workspace.root_validation import (
    WorkspaceRootValidationError,
    validate_workspace_root_for_execution,
)
from .adapter_resolution import AdapterResolutionError, resolve_runtime_adapter
from .artifact_persistence import ArtifactPersistenceService
from .context_snapshot_populator import ContextSnapshotPopulator
from .events import safe_append_run_event
from .policy_inputs import (
    CredentialPolicyMetadataError,
    automation_credential_preauthorized,
    build_runtime_execute_policy_request,
    build_runtime_use_credential_policy_request,
    resolve_runtime_credential_policy_metadata,
)
from .produced_artifact_path_ingestion import ingest_produced_artifact_paths
from .redaction import redact_artifact_content
from .run_output_materialization import RunOutputMaterializer
from .runtime_policy import compute_runtime_policy_decision
from .task_output_linkage import link_run_outputs_to_tasks
from .finalization import (
    NonTerminalRunError,
    PostRunFinalizationService,
    RunNotFoundError,
)
from .worktree_manager import (
    cleanup_isolated_run_workdir,
    prepare_isolated_run_workdir,
)
from .workspace_worktree import (
    WorkspaceNotGitRepoError,
    cleanup_workspace_git_worktree,
    create_workspace_git_worktree,
    run_workspace_preflight,
)


router = APIRouter(prefix="/internal/runs-context", tags=["internal-runs-context"])

_INTERNAL_TOKEN_HEADER = "x-agent-space-internal-token"

RunPortOperation = Literal[
    "policy.enforce",
    "context.prepare",
    "artifact.persist",
    "proposal.create",
    "workspace.prepare",
    "workspace.cleanup",
    "finalization.finalize",
]
RunPortOwner = Literal[
    "policy",
    "memory_context",
    "artifacts",
    "proposals",
    "workspace_sandbox",
    "runs_finalization",
]
RunPortErrorCode = Literal[
    "unauthorized_internal_port",
    "run_context_port_not_implemented",
    "python_context_port_unavailable",
    "python_context_port_invalid_response",
    "policy_denied",
    "policy_requires_approval",
    "policy_audit_persist_failed",
    "runtime_resolution_failed",
    "context_prepare_failed",
    "artifact_persist_failed",
    "proposal_create_failed",
    "workspace_prepare_failed",
    "workspace_cleanup_failed",
    "run_not_found",
    "run_not_terminal",
    "finalization_failed",
]


class RunContextPortDescriptor(BaseModel):
    operation: RunPortOperation
    owner: RunPortOwner
    implemented: bool
    auth: Literal["internal_service_token"] = "internal_service_token"
    error_codes: list[RunPortErrorCode]
    writes: list[str] = Field(default_factory=list)
    notes: str | None = None


class RunContextPortsManifest(BaseModel):
    service: Literal["python_runs_context_ports"] = "python_runs_context_ports"
    ports: list[RunContextPortDescriptor]
    generated_at: datetime


class RunContextPortRequest(BaseModel):
    operation: RunPortOperation
    run_id: str | None = None
    space_id: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)


class RunContextPortResponse(BaseModel):
    operation: RunPortOperation
    owner: RunPortOwner
    status: Literal["succeeded", "failed", "not_implemented"]
    error_code: RunPortErrorCode | None = None
    message: str | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)


_PORTS: tuple[RunContextPortDescriptor, ...] = (
    RunContextPortDescriptor(
        operation="policy.enforce",
        owner="policy",
        implemented=True,
        error_codes=[
            "policy_denied",
            "policy_requires_approval",
            "policy_audit_persist_failed",
            "runtime_resolution_failed",
        ],
        writes=["policy_decision_records"],
        notes=(
            "PolicyPort resolves the active policy authority. Enforces runtime.execute and "
            "runtime.use_credential for the run and returns the resolved "
            "adapter execution parameters (sanitized merged config, risk and "
            "sandbox levels) so TS never trusts caller-supplied adapter config."
        ),
    ),
    RunContextPortDescriptor(
        operation="context.prepare",
        owner="memory_context",
        implemented=True,
        error_codes=[
            "context_prepare_failed",
            "policy_denied",
            "policy_requires_approval",
            "policy_audit_persist_failed",
        ],
        writes=["context_snapshots", "memory_access_logs", "policy_decision_records"],
        notes="ContextSnapshotPopulator/ContextBuilder remain Python-owned; TS runs call this port before adapter invocation.",
    ),
    RunContextPortDescriptor(
        operation="artifact.persist",
        owner="artifacts",
        implemented=True,
        error_codes=[
            "artifact_persist_failed",
            "policy_denied",
            "policy_requires_approval",
            "policy_audit_persist_failed",
        ],
        writes=["artifacts", "policy_decision_records"],
        notes=(
            "Artifact storage and egress guard remain artifact-context owned; "
            "supports runtime_output text, adapter output_json artifact specs, "
            "and produced_artifact_paths entries."
        ),
    ),
    RunContextPortDescriptor(
        operation="proposal.create",
        owner="proposals",
        implemented=True,
        error_codes=["proposal_create_failed"],
        writes=["proposals"],
        notes=(
            "Runs may request proposals, never apply them. Reuses "
            "RunOutputMaterializer proposed_changes validation (memory_update, "
            "code_patch) including egress guard behavior."
        ),
    ),
    RunContextPortDescriptor(
        operation="workspace.prepare",
        owner="workspace_sandbox",
        implemented=True,
        error_codes=["workspace_prepare_failed", "run_context_port_not_implemented"],
        writes=["runs.sandbox_path"],
        notes="Workspace root validation and sandbox/worktree preparation remain Python-owned and are exposed through this port.",
    ),
    RunContextPortDescriptor(
        operation="workspace.cleanup",
        owner="workspace_sandbox",
        implemented=True,
        error_codes=["workspace_cleanup_failed", "run_context_port_not_implemented"],
        writes=["runs.sandbox_path"],
        notes="Sandbox cleanup remains owned by workspace/sandbox boundaries and is called after TS adapter execution.",
    ),
    RunContextPortDescriptor(
        operation="finalization.finalize",
        owner="runs_finalization",
        implemented=True,
        error_codes=["run_not_found", "run_not_terminal", "finalization_failed"],
        writes=["run_evaluations", "run_finalizations", "run_events", "task_evaluations"],
        notes="Public finalization remains Python-owned; TS orchestration may call this explicit port.",
    ),
)


def _descriptor(operation: RunPortOperation) -> RunContextPortDescriptor:
    for port in _PORTS:
        if port.operation == operation:
            return port
    raise HTTPException(status_code=400, detail="Unknown run context port operation")


def _require_internal_token(
    token: str | None = Header(default=None, alias=_INTERNAL_TOKEN_HEADER),
) -> None:
    configured = (settings.control_plane_internal_token or "").strip()
    presented = (token or "").strip()
    if not configured or not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not compare_digest(presented, configured):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/ports", response_model=RunContextPortsManifest)
def describe_run_context_ports(
    _: None = Depends(_require_internal_token),
) -> RunContextPortsManifest:
    return RunContextPortsManifest(
        ports=list(_PORTS),
        generated_at=datetime.now(UTC),
    )


@router.post("/operations", response_model=RunContextPortResponse)
def run_context_port_operation(
    body: RunContextPortRequest,
    _: None = Depends(_require_internal_token),
    db: Session = Depends(get_db),
) -> RunContextPortResponse:
    port = _descriptor(body.operation)
    if body.operation == "policy.enforce":
        return _policy_enforce(body, db, port)
    if body.operation == "context.prepare":
        return _context_prepare(body, db, port)
    if body.operation == "artifact.persist":
        return _artifact_persist(body, db, port)
    if body.operation == "proposal.create":
        return _proposal_create(body, db, port)
    if body.operation == "workspace.prepare":
        return _workspace_prepare(body, db, port)
    if body.operation == "workspace.cleanup":
        return _workspace_cleanup(body, db, port)
    if body.operation == "finalization.finalize":
        return _finalize(body, db, port)

    raise HTTPException(
        status_code=501,
        detail={
            "error": "run_context_port_not_implemented",
            "operation": body.operation,
            "owner": port.owner,
            "message": (
                f"Run context port {body.operation!r} is declared but not yet wired "
                "for concrete execution."
            ),
        },
    )


_PERSONAL_CONTEXT_HEADER = "[Personal context granted for this run - reasoning only]"
_PERSONAL_CONTEXT_FOOTER = "[End personal context]"
_PERSONAL_CONTEXT_WARNING = (
    "This personal context is granted for reasoning only. "
    "Do not quote or persist it directly."
)


def _load_run(db: Session, run_id: str | None, space_id: str | None) -> Run:
    if not run_id or not space_id:
        raise HTTPException(status_code=422, detail="run_id and space_id are required")
    run = db.query(Run).filter(Run.id == run_id, Run.space_id == space_id).one_or_none()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": "Run not found in this space.",
            },
        )
    return run


def _load_version(db: Session, run: Run) -> AgentVersion:
    version = (
        db.query(AgentVersion)
        .filter(AgentVersion.id == run.agent_version_id, AgentVersion.space_id == run.space_id)
        .one_or_none()
    )
    if version is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "context_prepare_failed",
                "message": "Run agent version snapshot was not found.",
            },
        )
    return version


def _runtime_prompt(user_prompt: str, personal_context_block: str | None) -> str:
    block = (personal_context_block or "").strip()
    if not block:
        return user_prompt
    return "\n\n".join(
        [
            user_prompt,
            _PERSONAL_CONTEXT_HEADER,
            _PERSONAL_CONTEXT_WARNING,
            block,
            _PERSONAL_CONTEXT_FOOTER,
        ]
    )


def _context_prepare(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    run = _load_run(db, body.run_id, body.space_id)
    version = _load_version(db, run)
    payload = body.payload_json or {}
    adapter_type = _string(payload.get("adapter_type")) or run.adapter_type
    sandbox_cwd = _string(payload.get("sandbox_cwd"))
    target_format = _target_format(_string(payload.get("target_format")))
    workspace_path = _string(payload.get("workspace_path"))

    try:
        context_pkg = ContextSnapshotPopulator(db).populate(run, version)
        _enforce_context_render_policy(db, run, adapter_type)
        prompt = _runtime_prompt(
            run.prompt or "",
            getattr(context_pkg, "personal_context_block", None),
        )
        result_json: dict[str, Any] = {
            "runtime_prompt": prompt,
            "context_snapshot_id": str(run.context_snapshot_id) if run.context_snapshot_id else None,
            "context_rendered": False,
        }
        if sandbox_cwd and target_format is not None:
            compiled = ContextCompiler().compile(
                context=context_pkg.model_dump(),
                target=target_format,
                task_goal=prompt,
                sandbox_dir=sandbox_cwd,
                workspace_path=workspace_path,
            )
            result_json.update(
                {
                    "context_rendered": True,
                    "target_format": target_format.value,
                    "instruction_file_path": compiled.instruction_file_path,
                    "total_chars": compiled.total_chars,
                    "budget_chars": compiled.budget_chars,
                    "dropped_sections": list(compiled.dropped_sections or []),
                }
            )
        db.commit()
        return RunContextPortResponse(
            operation=body.operation,
            owner=port.owner,
            status="succeeded",
            result_json=result_json,
        )
    except PolicyGateBlocked as exc:
        try:
            write_blocked_gate_audit(exc)
        except Exception:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "policy_audit_persist_failed",
                    "message": "Policy audit record persistence failed.",
                },
            ) from exc
        db.rollback()
        decision = exc.decision
        raise HTTPException(
            status_code=403,
            detail={
                "error": "policy_denied" if decision.denied else "policy_requires_approval",
                "message": decision.message,
            },
        ) from exc
    except PolicyAuditPersistError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "policy_audit_persist_failed",
                "message": "Policy audit record persistence failed.",
            },
        ) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "context_prepare_failed",
                "message": f"Context preparation failed: {exc}"[:1000],
            },
        ) from exc


def _enforce_context_render_policy(
    db: Session,
    run: Run,
    adapter_type: str | None,
) -> None:
    get_policy_port(db).enforce(
        PolicyCheckRequest(
            action="context.render_for_runtime",
            actor_type="run",
            actor_id=str(run.id),
            space_id=run.space_id,
            resource_type="context",
            resource_id=str(run.context_snapshot_id) if run.context_snapshot_id else None,
            run_id=str(run.id),
            context={
                "has_personal_grant_context": bool(
                    getattr(run, "has_personal_grant_context", False)
                ),
            },
            metadata_json={
                "context_snapshot_id": (
                    str(run.context_snapshot_id) if run.context_snapshot_id else None
                ),
                "adapter_type": adapter_type,
                "data_exposure_level": run.data_exposure_level,
                "trust_level": run.trust_level,
            },
        )
    )


def _policy_failure(
    body: RunContextPortRequest,
    port: RunContextPortDescriptor,
    error_code: RunPortErrorCode,
    message: str,
    result_json: dict[str, Any] | None = None,
) -> RunContextPortResponse:
    return RunContextPortResponse(
        operation=body.operation,
        owner=port.owner,
        status="failed",
        error_code=error_code,
        message=message[:1000],
        result_json=result_json or {},
    )


def _policy_enforce(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    """Enforce runtime.execute / runtime.use_credential and return the resolved
    adapter execution parameters.

    This is the Stage 4 pre-invocation gate for TS-owned run execution. The
    response's ``adapter_config`` is the only adapter config TS may use —
    callers of the public execute command never supply executable paths,
    permission bypass, or runtime policy.
    """
    run = _load_run(db, body.run_id, body.space_id)
    version = _load_version(db, run)

    policy_dict = dict(version.runtime_policy_json or {})
    decision = compute_runtime_policy_decision(run=run, version=version)

    if decision.required_sandbox_level == "one_shot_docker":
        return _policy_failure(
            body,
            port,
            "runtime_resolution_failed",
            "risk_level=critical requires one_shot_docker sandbox isolation, "
            "which is not implemented in this build.",
        )

    try:
        resolved = resolve_runtime_adapter(db, run=run, version=version, policy=policy_dict)
    except AdapterResolutionError as exc:
        db.rollback()
        return _policy_failure(
            body, port, "runtime_resolution_failed", f"{exc.error_code}: {exc.message}"
        )

    try:
        runtime_requirements = get_runtime_requirements(resolved.adapter_type)
    except UnknownRuntimeRequirementsError as exc:
        db.rollback()
        return _policy_failure(
            body, port, "runtime_resolution_failed", f"runtime_requirements_missing: {exc}"
        )

    agent_status: str | None = None
    try:
        agent_status = version.agent.status if version.agent else None
    except Exception:
        agent_status = None

    exec_req = build_runtime_execute_policy_request(
        run, version, resolved, decision, agent_status
    )
    try:
        exec_decision = get_policy_port(db).enforce(exec_req)
    except PolicyGateBlocked as exc:
        try:
            write_blocked_gate_audit(exc)
        except Exception:
            db.rollback()
            return _policy_failure(
                body,
                port,
                "policy_audit_persist_failed",
                "Policy audit record persistence failed for runtime.execute.",
            )
        exec_decision = exc.decision
    except PolicyAuditPersistError:
        db.rollback()
        return _policy_failure(
            body,
            port,
            "policy_audit_persist_failed",
            "Policy audit record persistence failed for runtime.execute.",
        )
    if exec_decision.denied or exec_decision.requires_approval:
        try:
            safe_append_run_event(
                db,
                run_id=run.id,
                space_id=run.space_id,
                event_type="policy_checked",
                status="failed",
                workspace_id=run.workspace_id,
                metadata_json={
                    "action": "runtime.execute",
                    "decision": exec_decision.decision.value,
                    "risk_level": exec_decision.risk_level.value,
                    "policy_rule_id": exec_decision.policy_rule_id,
                    "audit_code": exec_decision.audit_code,
                },
                log_context="policy_checked.runtime_execute",
            )
        except Exception:
            pass
        db.commit()
        return _policy_failure(
            body,
            port,
            "policy_denied" if exec_decision.denied else "policy_requires_approval",
            (
                f"Runtime execution denied by policy: {exec_decision.message}"
                if exec_decision.denied
                else f"Runtime execution requires approval: {exec_decision.message}"
            ),
            result_json={"action": "runtime.execute"},
        )

    try:
        credential_subject = resolve_runtime_credential_policy_metadata(
            db, run, version, resolved, runtime_requirements
        )
    except CredentialPolicyMetadataError as exc:
        db.rollback()
        return _policy_failure(
            body, port, "runtime_resolution_failed", f"{exc.error_code}: {exc.message}"
        )

    if credential_subject is not None:
        cred_req = build_runtime_use_credential_policy_request(
            run,
            credential_subject,
            decision,
            resolved.adapter_type,
            automation_pre_authorized=automation_credential_preauthorized(db, run),
        )
        try:
            cred_decision = get_policy_port(db).enforce(cred_req)
        except PolicyGateBlocked as exc:
            try:
                write_blocked_gate_audit(exc)
            except Exception:
                db.rollback()
                return _policy_failure(
                    body,
                    port,
                    "policy_audit_persist_failed",
                    "Policy audit record persistence failed for runtime.use_credential.",
                )
            cred_decision = exc.decision
        except PolicyAuditPersistError:
            db.rollback()
            return _policy_failure(
                body,
                port,
                "policy_audit_persist_failed",
                "Policy audit record persistence failed for runtime.use_credential.",
            )
        if cred_decision.denied or cred_decision.requires_approval:
            db.commit()
            return _policy_failure(
                body,
                port,
                "policy_denied" if cred_decision.denied else "policy_requires_approval",
                (
                    f"Credential use denied by policy: {cred_decision.message}"
                    if cred_decision.denied
                    else f"Credential use requires approval: {cred_decision.message}"
                ),
                result_json={"action": "runtime.use_credential"},
            )

    safe_config = sanitize_runtime_config(dict(resolved.merged_config or {}))
    safe_config["runtime_policy_json"] = policy_dict
    try:
        safe_append_run_event(
            db,
            run_id=run.id,
            space_id=run.space_id,
            event_type="policy_checked",
            status="succeeded",
            workspace_id=run.workspace_id,
            metadata_json={
                "action": "runtime.execute",
                "decision": exec_decision.decision.value,
                "risk_level": exec_decision.risk_level.value,
                "policy_rule_id": exec_decision.policy_rule_id,
                "audit_code": exec_decision.audit_code,
            },
            log_context="policy_checked.runtime_execute",
        )
    except Exception:
        pass
    db.commit()
    return RunContextPortResponse(
        operation=body.operation,
        owner=port.owner,
        status="succeeded",
        result_json={
            "decision": "allowed",
            "risk_level": decision.risk_level,
            "required_sandbox_level": decision.required_sandbox_level,
            "adapter_type": resolved.adapter_type,
            "adapter_config": safe_config,
        },
    )


def _artifact_persist(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    run = _load_run(db, body.run_id, body.space_id)
    payload = body.payload_json or {}

    try:
        if _string(payload.get("artifact_type")) == "runtime_output" or (
            payload.get("text") is not None and payload.get("source") is None
        ):
            text = payload.get("text")
            if not isinstance(text, str):
                return _policy_failure(
                    body, port, "artifact_persist_failed", "runtime_output requires text"
                )
            safe_text = redact_artifact_content(text) or ""
            art = ArtifactPersistenceService(db).persist_text_file(
                run=run,
                text=safe_text,
                title=_string(payload.get("title")) or "Run output",
                artifact_type="runtime_output",
                preview=bool(payload.get("preview", False)),
            )
            link_run_outputs_to_tasks(db, run=run, artifact=art, proposal=None)
            db.commit()
            return RunContextPortResponse(
                operation=body.operation,
                owner=port.owner,
                status="succeeded",
                result_json={
                    "artifact_id": art.id,
                    "artifact_type": art.artifact_type,
                    "title": art.title,
                },
            )

        if _string(payload.get("source")) == "produced_artifact_paths":
            sandbox_cwd = _string(payload.get("sandbox_cwd"))
            entry = payload.get("entry")
            errors = ingest_produced_artifact_paths(
                db,
                run=run,
                source_root=sandbox_cwd,
                entries=[entry],
            )
            if errors:
                db.rollback()
                return _policy_failure(
                    body, port, "artifact_persist_failed", "; ".join(errors)
                )
            db.commit()
            return RunContextPortResponse(
                operation=body.operation,
                owner=port.owner,
                status="succeeded",
                result_json={"ingested": True},
            )

        if _string(payload.get("source")) == "adapter_output":
            spec = payload.get("spec")
            result = RunOutputMaterializer(db).materialize(
                run=run,
                adapter_output={"artifacts": [spec]},
                adapter_type=_string(payload.get("adapter_type")) or run.adapter_type or "unknown",
            )
            if result.failed_items or not result.artifact_items:
                db.rollback()
                failure = result.failed_items[0] if result.failed_items else {}
                return _policy_failure(
                    body,
                    port,
                    "artifact_persist_failed",
                    str(failure.get("error_message") or "artifact spec rejected"),
                )
            db.commit()
            item = result.artifact_items[0]
            return RunContextPortResponse(
                operation=body.operation,
                owner=port.owner,
                status="succeeded",
                result_json={
                    "artifact_id": item["id"],
                    "artifact_type": item.get("artifact_type"),
                },
            )

        return _policy_failure(
            body, port, "artifact_persist_failed", "Unsupported artifact.persist payload"
        )
    except PersonalMemoryEgressError as exc:
        db.rollback()
        return _policy_failure(body, port, "artifact_persist_failed", str(exc))
    except PolicyGateBlocked as exc:
        try:
            write_blocked_gate_audit(exc)
        except Exception:
            db.rollback()
            return _policy_failure(
                body,
                port,
                "policy_audit_persist_failed",
                "Policy audit record persistence failed for artifact.persist.",
            )
        db.rollback()
        return _policy_failure(
            body,
            port,
            "policy_denied" if exc.decision.denied else "policy_requires_approval",
            str(exc.decision.message or "artifact.persist blocked by policy"),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        return _policy_failure(
            body, port, "artifact_persist_failed", f"Artifact persistence failed: {exc}"
        )


def _proposal_create(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    run = _load_run(db, body.run_id, body.space_id)
    payload = body.payload_json or {}
    spec = payload.get("spec")

    try:
        result = RunOutputMaterializer(db).materialize(
            run=run,
            adapter_output={"proposed_changes": [spec]},
            adapter_type=_string(payload.get("adapter_type")) or run.adapter_type or "unknown",
        )
        if result.failed_items or not result.proposal_items:
            db.rollback()
            failure = result.failed_items[0] if result.failed_items else {}
            return _policy_failure(
                body,
                port,
                "proposal_create_failed",
                str(failure.get("error_message") or "proposal spec rejected"),
            )
        db.commit()
        item = result.proposal_items[0]
        return RunContextPortResponse(
            operation=body.operation,
            owner=port.owner,
            status="succeeded",
            result_json={
                "proposal_id": item["id"],
                "proposal_type": item.get("proposal_type"),
            },
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        return _policy_failure(
            body, port, "proposal_create_failed", f"Proposal creation failed: {exc}"
        )


def _workspace_prepare(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    run = _load_run(db, body.run_id, body.space_id)
    payload = body.payload_json or {}
    required_sandbox_level = _string(payload.get("required_sandbox_level")) or (
        run.required_sandbox_level or "none"
    )

    if required_sandbox_level in {"none", "dry_run"}:
        return RunContextPortResponse(
            operation=body.operation,
            owner=port.owner,
            status="succeeded",
            result_json={
                "sandbox_cwd": None,
                "cleanup_kind": "none",
                "required_sandbox_level": required_sandbox_level,
            },
        )
    if required_sandbox_level in {"one_shot_docker", "docker"}:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "workspace_prepare_failed",
                "message": "one_shot_docker sandbox execution is not implemented.",
            },
        )
    if required_sandbox_level != "worktree":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "workspace_prepare_failed",
                "message": f"Unsupported sandbox level: {required_sandbox_level}",
            },
        )

    try:
        if run.workspace_id:
            result_json = _prepare_workspace_git_worktree(db, run)
        else:
            workdir = prepare_isolated_run_workdir(run.space_id, run.id)
            result_json = {
                "sandbox_cwd": str(workdir),
                "cleanup_kind": "plain_workdir",
                "required_sandbox_level": required_sandbox_level,
                "sandbox_kind": "worktree",
            }
        run.sandbox_path = result_json["sandbox_cwd"]
        db.add(run)
        db.commit()
        return RunContextPortResponse(
            operation=body.operation,
            owner=port.owner,
            status="succeeded",
            result_json=result_json,
        )
    except HTTPException:
        db.rollback()
        raise
    except (WorkspaceRootValidationError, WorkspaceNotGitRepoError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "error": "workspace_prepare_failed",
                "message": getattr(exc, "message", str(exc)),
            },
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "workspace_prepare_failed",
                "message": f"Workspace preparation failed: {exc}"[:1000],
            },
        ) from exc


def _prepare_workspace_git_worktree(db: Session, run: Run) -> dict[str, Any]:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.id == run.workspace_id, Workspace.space_id == run.space_id)
        .one_or_none()
    )
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "workspace_prepare_failed",
                "message": "workspace not found in this space",
            },
        )
    workspace_root = workspace_absolute_root(workspace)
    validate_workspace_root_for_execution(
        workspace_space_id=workspace.space_id,
        run_space_id=run.space_id,
        workspace_root=workspace_root,
        allow_external_root=getattr(workspace, "allow_external_root", False),
        sandbox_level="worktree",
    )
    preflight = run_workspace_preflight(workspace_root)
    worktree = create_workspace_git_worktree(
        space_id=run.space_id,
        run_id=run.id,
        workspace_root=workspace_root,
    )
    return {
        "sandbox_cwd": str(worktree),
        "cleanup_kind": "git_worktree",
        "required_sandbox_level": "worktree",
        "sandbox_kind": "worktree",
        "workspace_root": str(workspace_root),
        "base_commit_sha": preflight.base_commit_sha,
        "workspace_is_dirty": preflight.is_dirty,
    }


def _workspace_cleanup(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    run = _load_run(db, body.run_id, body.space_id)
    payload = body.payload_json or {}
    cleanup_kind = _string(payload.get("cleanup_kind")) or "none"
    sandbox_cwd = _string(payload.get("sandbox_cwd"))
    workspace_root = _string(payload.get("workspace_root"))

    try:
        if cleanup_kind == "git_worktree" and workspace_root:
            cleanup_workspace_git_worktree(
                space_id=run.space_id,
                run_id=run.id,
                workspace_root=Path(workspace_root).resolve(),
                worktree_path=Path(sandbox_cwd).resolve() if sandbox_cwd else None,
            )
        elif cleanup_kind == "plain_workdir":
            cleanup_isolated_run_workdir(run.space_id, run.id)
        elif cleanup_kind != "none":
            raise ValueError(f"Unsupported cleanup kind: {cleanup_kind}")
        run.sandbox_path = None
        db.add(run)
        db.commit()
        return RunContextPortResponse(
            operation=body.operation,
            owner=port.owner,
            status="succeeded",
            result_json={"cleanup_kind": cleanup_kind},
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "workspace_cleanup_failed",
                "message": f"Workspace cleanup failed: {exc}"[:1000],
            },
        ) from exc


def _target_format(value: str | None) -> TargetFormat | None:
    if not value:
        return None
    try:
        return TargetFormat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "context_prepare_failed",
                "message": f"Unsupported context target_format: {value}",
            },
        ) from exc


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _finalize(
    body: RunContextPortRequest,
    db: Session,
    port: RunContextPortDescriptor,
) -> RunContextPortResponse:
    if not body.run_id or not body.space_id:
        raise HTTPException(
            status_code=422,
            detail="finalization.finalize requires run_id and space_id",
        )
    try:
        row = PostRunFinalizationService(db).finalize(body.run_id, space_id=body.space_id)
        db.commit()
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": str(exc),
            },
        ) from exc
    except NonTerminalRunError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "run_not_terminal",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "error": "finalization_failed",
                "message": "Run finalization failed",
            },
        ) from exc

    return RunContextPortResponse(
        operation=body.operation,
        owner=port.owner,
        status="succeeded",
        result_json={
            "run_finalization_id": row.id,
            "status": row.status,
            "run_evaluation_id": row.run_evaluation_id,
            "task_evaluation_id": row.task_evaluation_id,
            "outcome_status": row.outcome_status,
            "failure_layer": row.failure_layer,
            "failure_reason_code": row.failure_reason_code,
            "trajectory_status": row.trajectory_status,
            "finalized_at": row.finalized_at.isoformat() if row.finalized_at else None,
        },
    )
