"""Materialize structured runtime ``output_json`` into Artifact / Proposal rows.

Contract (adapter ``output_json`` after success):
- ``artifacts``: list of ``{artifact_type?, title?, content (required), ...}`` → ``Artifact`` rows.
- ``activities``: list of ``{activity_type?, title?, content?, payload_json?}`` → ``ActivityRecord`` rows.
- ``produced_artifact_paths``: handled by :mod:`app.runs.produced_artifact_path_ingestion` during
  execution (while the sandbox exists), not from ``output_json`` alone — see ``RuntimeAdapterResult``.
- ``proposed_changes``: list of durable-change requests. Supported ``proposal_type``:
  ``memory_update`` (requires ``payload`` with memory fields), ``code_patch`` (requires
  ``workspace_id`` + ``patch.operations`` with ``replace_file`` only). Invalid entries are
  skipped without aborting the run; failures are recorded in MaterializationResult.failed_items.

When grant-derived artifact or memory-proposal materialization is blocked by the egress guard,
a sanitized metadata-only egress_review proposal is created for the granting user. Direct
persistence remains blocked. The error message includes the proposal ID.
"""

from __future__ import annotations
import uuid

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..memory.proposals import build_memory_create_proposal
from ..models import ActivityRecord, Artifact, Proposal, Run, Workspace
from ..personal_memory_grants.egress_guard import (
    EgressDecision,
    PersonalMemoryEgressError,
    check_personal_memory_egress,
)
from ..personal_memory_grants.egress_review import create_egress_review_proposal
from .task_output_linkage import link_run_outputs_to_tasks


@dataclass
class MaterializationResult:
    """Structured result from RunOutputMaterializer.materialize().

    errors: human-readable strings for run.output_json["materialization_errors"] (debug).
    artifact_items: successfully created artifacts: {id, artifact_type, label}.
    proposal_items: successfully created proposals: {id, proposal_type, label}.
    failed_items: failures: {kind, label, error_code, error_message, artifact_type?, proposal_type?}.
    """
    errors: list[str] = field(default_factory=list)
    artifact_items: list[dict] = field(default_factory=list)
    proposal_items: list[dict] = field(default_factory=list)
    failed_items: list[dict] = field(default_factory=list)


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _reject_traversal(rel: str) -> None:
    from pathlib import Path

    p = Path(rel)
    if p.is_absolute():
        raise ValueError("absolute path in patch")
    if ".." in p.parts:
        raise ValueError("path traversal in patch")


def _preview_patch_paths(patch: dict) -> None:
    ops = patch.get("operations")
    if not isinstance(ops, list):
        raise ValueError("patch.operations must be a list")
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("patch operation must be an object")
        if op.get("op") != "replace_file":
            raise ValueError(f"unsupported op {op.get('op')!r}")
        rel = op.get("path")
        if not isinstance(rel, str) or not rel.strip():
            raise ValueError("replace_file.path required")
        _reject_traversal(rel.strip().replace("\\", "/"))


class RunOutputMaterializer:
    """Persist adapter-declared artifacts and durable-change proposals (never auto-apply)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def materialize(
        self,
        *,
        run: Run,
        adapter_output: dict[str, Any] | None,
        adapter_type: str,
    ) -> MaterializationResult:
        """
        Create rows from ``adapter_output`` keys ``artifacts`` and ``proposed_changes``.

        Returns a MaterializationResult with successes, failures, and human-readable
        error strings.  Durable mutations are skipped for failed entries only.
        """
        result = MaterializationResult()
        data = dict(adapter_output or {})

        for i, spec in enumerate(data.get("artifacts") or []):
            label = f"artifacts[{i}]"
            artifact_type = str(spec.get("artifact_type") or "report")[:64] if isinstance(spec, dict) else None
            try:
                art = self._artifact_from_spec(run, spec, adapter_type, label)
                result.artifact_items.append({
                    "id": art.id,
                    "artifact_type": art.artifact_type,
                    "label": label,
                })
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:256]
                result.errors.append(f"{label}: {msg}")
                result.failed_items.append({
                    "kind": "artifact",
                    "label": label,
                    "error_code": "output_artifact_materialization_error",
                    "error_message": msg,
                    "artifact_type": artifact_type,
                })

        for i, spec in enumerate(data.get("activities") or []):
            label = f"activities[{i}]"
            try:
                self._activity_from_spec(run, spec, label)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:256]
                result.errors.append(f"{label}: {msg}")
                result.failed_items.append({
                    "kind": "activity",
                    "label": label,
                    "error_code": "output_activity_materialization_error",
                    "error_message": msg,
                })

        for i, spec in enumerate(data.get("proposed_changes") or []):
            label = f"proposed_changes[{i}]"
            ptype = spec.get("proposal_type") if isinstance(spec, dict) else None
            try:
                prop = self._proposal_from_spec(run, spec)
                result.proposal_items.append({
                    "id": prop.id,
                    "proposal_type": ptype or "unknown",
                    "label": label,
                })
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:256]
                result.errors.append(f"{label}: {msg}")
                result.failed_items.append({
                    "kind": "proposal",
                    "label": label,
                    "error_code": "output_proposal_materialization_error",
                    "error_message": msg,
                    "proposal_type": ptype,
                })

        self.db.flush()
        return result

    def _artifact_from_spec(self, run: Run, spec: Any, adapter_type: str, label: str) -> Artifact:
        if not isinstance(spec, dict):
            raise TypeError("artifact spec must be an object")

        # Egress guard: block grant-derived artifacts targeting non-personal spaces.
        # When blocked with requires_proposal=True, create a sanitized egress_review
        # proposal so the granting user can review the blocked output.
        egress = check_personal_memory_egress(
            self.db,
            run=run,
            target_space_id=run.space_id,
            target_object_type="artifact",
            operation="artifact_materialization",
        )
        if egress.decision == EgressDecision.BLOCK:
            if egress.requires_proposal:
                review_proposal = create_egress_review_proposal(
                    self.db,
                    source_run=run,
                    target_space_id=run.space_id,
                    target_object_type="artifact",
                    operation="artifact_materialization",
                    egress_result=egress,
                    materialization_kind="adapter_artifact",
                )
                proposal_id = review_proposal.id if review_proposal is not None else None
                suffix = f"; egress_review_proposal_id={proposal_id}" if proposal_id else ""
                raise PersonalMemoryEgressError(
                    f"egress_review_required: direct artifact persistence blocked{suffix}",
                    grant_id=egress.grant_id,
                )
            raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)

        artifact_type = str(spec.get("artifact_type") or "report")[:64]
        title = str(spec.get("title") or f"Run artifact ({artifact_type})")[:512]
        content = spec.get("content")
        if content is None:
            raise ValueError("content is required")
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        preview = bool(spec.get("preview", False))
        mime = str(spec.get("mime_type") or "text/plain")[:256]
        metadata_json = spec.get("metadata_json")
        if metadata_json is not None and not isinstance(metadata_json, dict):
            raise TypeError("metadata_json must be an object")
        art = Artifact(
            id=_new_id(),
            space_id=run.space_id,
            run_id=run.id,
            project_id=run.project_id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            mime_type=mime,
            exportable=True,
            preview=preview,
            metadata_json=metadata_json,
            owner_user_id=run.instructed_by_user_id,
        )
        self.db.add(art)
        link_run_outputs_to_tasks(self.db, run=run, artifact=art, proposal=None)
        return art

    def _activity_from_spec(self, run: Run, spec: Any, label: str) -> None:
        if not isinstance(spec, dict):
            raise TypeError("activity spec must be an object")
        del label

        payload = spec.get("payload_json")
        if payload is None:
            payload = spec.get("metadata_json")
        if payload is not None and not isinstance(payload, dict):
            raise TypeError("payload_json must be an object")

        source_kind = str(spec.get("source_kind") or "run_event")
        if source_kind not in {
            "user_capture",
            "chat_message",
            "external_chat",
            "file_import",
            "web_capture",
            "run_event",
            "workspace_event",
            "system_event",
            "external_source",
        }:
            raise ValueError("source_kind is invalid")

        source_trust = str(spec.get("source_trust") or "internal_system")
        if source_trust not in {
            "user_confirmed",
            "internal_system",
            "trusted_external",
            "untrusted_external",
            "agent_inferred",
        }:
            raise ValueError("source_trust is invalid")

        content = spec.get("content")
        if content is not None and not isinstance(content, str):
            raise TypeError("content must be a string")

        source_url = spec.get("source_url")
        if source_url is not None and not isinstance(source_url, str):
            raise TypeError("source_url must be a string")

        activity = ActivityRecord(
            id=_new_id(),
            space_id=run.space_id,
            source_run_id=run.id,
            session_id=run.session_id,
            user_id=run.instructed_by_user_id,
            workspace_id=run.workspace_id,
            agent_id=run.agent_id,
            project_id=run.project_id,
            source_url=source_url,
            activity_type=str(spec.get("activity_type") or "capability_event")[:64],
            source_kind=source_kind,
            source_trust=source_trust,
            title=str(spec.get("title") or "Capability event")[:512],
            content=content,
            payload_json=payload or {},
            status="raw",
            consolidation_status="pending",
            owner_user_id=run.instructed_by_user_id,
        )
        self.db.add(activity)

    def _proposal_from_spec(self, run: Run, spec: Any) -> Proposal:
        if not isinstance(spec, dict):
            raise TypeError("proposed_change must be an object")
        uid = run.instructed_by_user_id
        if not uid:
            raise ValueError("run has no instructed_by_user_id; cannot attribute proposal")

        ptype = spec.get("proposal_type")
        if ptype == "memory_update":
            return self._memory_update_proposal(run, spec, uid)
        elif ptype == "code_patch":
            return self._code_patch_proposal(run, spec, uid)
        else:
            raise ValueError(f"unsupported proposal_type {ptype!r}")

    def _memory_update_proposal(self, run: Run, spec: dict[str, Any], user_id: str) -> Proposal:
        payload = spec.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("memory_update requires payload object")

        # Egress guard: block grant-derived memory proposals targeting non-personal spaces.
        # When blocked with requires_proposal=True, create a sanitized egress_review
        # proposal so the granting user can review the blocked output.
        egress = check_personal_memory_egress(
            self.db,
            run=run,
            target_space_id=run.space_id,
            target_object_type="memory_proposal",
            operation="memory_proposal_create",
        )
        if egress.decision == EgressDecision.BLOCK:
            if egress.requires_proposal:
                review_proposal = create_egress_review_proposal(
                    self.db,
                    source_run=run,
                    target_space_id=run.space_id,
                    target_object_type="memory_proposal",
                    operation="memory_proposal_create",
                    egress_result=egress,
                    materialization_kind="adapter_memory_proposal",
                )
                proposal_id = review_proposal.id if review_proposal is not None else None
                suffix = f"; egress_review_proposal_id={proposal_id}" if proposal_id else ""
                raise PersonalMemoryEgressError(
                    f"egress_review_required: direct memory proposal creation blocked{suffix}",
                    grant_id=egress.grant_id,
                )
            raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)
        title = str(spec.get("summary") or payload.get("proposed_title") or "Memory update")[:512]
        proposed_content = payload.get("proposed_content")
        memory_type = payload.get("memory_type")
        target_scope = payload.get("target_scope")
        target_namespace = payload.get("target_namespace")
        if not proposed_content or not memory_type or not target_scope or not target_namespace:
            raise ValueError("payload must include proposed_content, memory_type, target_scope, target_namespace")
        rationale = str(spec.get("summary") or payload.get("rationale") or "Proposed from run output")[:8000]
        now = _utcnow()
        prop = build_memory_create_proposal(
            _new_id(),
            run.space_id,
            user_id,
            workspace_id=run.workspace_id,
            proposed_title=title,
            proposed_content=str(proposed_content),
            rationale=rationale,
            memory_type=str(memory_type),
            target_scope=str(target_scope),
            target_namespace=str(target_namespace),
            source_run_id=run.id,
            target_visibility=str(payload.get("target_visibility") or "space_shared"),
            risk_level=str(payload.get("risk_level") or spec.get("risk_level") or "low"),
            owner_user_id=payload.get("owner_user_id"),
            subject_user_id=payload.get("subject_user_id"),
            sensitivity_level=str(payload.get("sensitivity_level") or "normal"),
            selected_user_ids=payload.get("selected_user_ids"),
            review_deadline=now + timedelta(hours=48),
            expires_at=now + timedelta(days=14),
            created_by_run_id=run.id,
        )
        self.db.add(prop)
        link_run_outputs_to_tasks(self.db, run=run, artifact=None, proposal=prop, proposal_role="memory_create")
        return prop

    def _code_patch_proposal(self, run: Run, spec: dict[str, Any], user_id: str) -> Proposal:
        ws_id = spec.get("workspace_id")
        if not isinstance(ws_id, str) or not ws_id.strip():
            raise ValueError("code_patch requires workspace_id")
        ws = (
            self.db.query(Workspace)
            .filter(Workspace.id == ws_id.strip(), Workspace.space_id == run.space_id)
            .first()
        )
        if not ws:
            raise ValueError("workspace_id not found in run space")
        patch = spec.get("patch")
        if not isinstance(patch, dict):
            raise ValueError("code_patch requires patch object")
        _preview_patch_paths(patch)
        title = str(spec.get("summary") or "Code patch")[:512]
        rationale = str(spec.get("summary") or "Proposed workspace changes from run output")[:8000]
        now = _utcnow()

        patch_payload: dict[str, Any] = {
            "patch": patch,
            "source_run_id": run.id,
            "materialized_from_adapter": True,
        }
        risk_level = "low"

        # Code patch proposals from grant-derived runs carry explicit risk metadata.
        # They are not blocked (human approval is required regardless), but they must be
        # visibly marked so reviewers understand the personal-context provenance.
        if getattr(run, "has_personal_grant_context", False):
            grant_ctx = getattr(run, "personal_grant_context_json", None) or {}
            risk_level = "high"
            patch_payload["personal_context_derived"] = True
            patch_payload["egress_guard_required"] = True
            patch_payload["requires_extra_review"] = True
            patch_payload["raw_private_memory_included"] = False
            patch_payload["personal_summary_persisted"] = False
            if grant_ctx.get("grant_id"):
                patch_payload["grant_id"] = grant_ctx["grant_id"]
            if grant_ctx.get("granting_user_id"):
                patch_payload["granting_user_id"] = grant_ctx["granting_user_id"]

        prop = Proposal(
            id=_new_id(),
            space_id=run.space_id,
            proposal_type="code_patch",
            status="pending",
            title=title,
            summary=str(spec.get("summary") or "")[:8000] or None,
            payload_json=patch_payload,
            rationale=rationale,
            workspace_id=ws.id,
            created_by_user_id=user_id,
            created_by_run_id=run.id,
            risk_level=risk_level,
            urgency="normal",
            review_deadline=now + timedelta(hours=48),
            expires_at=now + timedelta(days=14),
        )
        self.db.add(prop)
        link_run_outputs_to_tasks(self.db, run=run, artifact=None, proposal=prop, proposal_role="code_patch")
        return prop
