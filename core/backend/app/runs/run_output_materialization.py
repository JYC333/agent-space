"""Materialize structured runtime ``output_json`` into Artifact / Proposal rows.

Contract (adapter ``output_json`` after success):
- ``artifacts``: list of ``{artifact_type?, title?, content (required), ...}`` → ``Artifact`` rows.
- ``produced_artifact_paths``: handled by :mod:`app.runs.produced_artifact_path_ingestion` during
  execution (while the sandbox exists), not from ``output_json`` alone — see ``RuntimeAdapterResult``.
- ``proposed_changes``: list of durable-change requests. Supported ``proposal_type``:
  ``memory_update`` (requires ``payload`` with memory fields), ``code_patch`` (requires
  ``workspace_id`` + ``patch.operations`` with ``replace_file`` only). Invalid entries are
  recorded on ``run.output_json["materialization_errors"]`` and skipped without aborting
  the run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session
from ulid import ULID

from ..memory.proposals import build_memory_update_proposal
from ..models import Artifact, Proposal, Run, Workspace
from .task_output_linkage import link_run_outputs_to_tasks


def _new_id() -> str:
    return str(ULID())


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
    ) -> list[str]:
        """
        Create rows from ``adapter_output`` keys ``artifacts`` and ``proposed_changes``.

        Returns a list of human-readable error strings; durable mutations are skipped
        for those entries only.
        """
        errors: list[str] = []
        data = dict(adapter_output or {})

        for i, spec in enumerate(data.get("artifacts") or []):
            label = f"artifacts[{i}]"
            try:
                self._artifact_from_spec(run, spec, adapter_type, label)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")

        for i, spec in enumerate(data.get("proposed_changes") or []):
            label = f"proposed_changes[{i}]"
            try:
                self._proposal_from_spec(run, spec)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")

        self.db.flush()
        return errors

    def _artifact_from_spec(self, run: Run, spec: Any, adapter_type: str, label: str) -> None:
        if not isinstance(spec, dict):
            raise TypeError("artifact spec must be an object")
        artifact_type = str(spec.get("artifact_type") or "report")[:64]
        title = str(spec.get("title") or f"Run artifact ({artifact_type})")[:512]
        content = spec.get("content")
        if content is None:
            raise ValueError("content is required")
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        preview = bool(spec.get("preview", False))
        mime = str(spec.get("mime_type") or "text/plain")[:256]
        art = Artifact(
            id=_new_id(),
            space_id=run.space_id,
            run_id=run.id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            mime_type=mime,
            exportable=True,
            preview=preview,
        )
        self.db.add(art)
        link_run_outputs_to_tasks(self.db, run=run, artifact=art, proposal=None)

    def _proposal_from_spec(self, run: Run, spec: Any) -> None:
        if not isinstance(spec, dict):
            raise TypeError("proposed_change must be an object")
        uid = run.instructed_by_user_id
        if not uid:
            raise ValueError("run has no instructed_by_user_id; cannot attribute proposal")

        ptype = spec.get("proposal_type")
        if ptype == "memory_update":
            self._memory_update_proposal(run, spec, uid)
        elif ptype == "code_patch":
            self._code_patch_proposal(run, spec, uid)
        else:
            raise ValueError(f"unsupported proposal_type {ptype!r}")

    def _memory_update_proposal(self, run: Run, spec: dict[str, Any], user_id: str) -> None:
        payload = spec.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("memory_update requires payload object")
        title = str(spec.get("summary") or payload.get("proposed_title") or "Memory update")[:512]
        proposed_content = payload.get("proposed_content")
        memory_type = payload.get("memory_type")
        target_scope = payload.get("target_scope")
        target_namespace = payload.get("target_namespace")
        if not proposed_content or not memory_type or not target_scope or not target_namespace:
            raise ValueError("payload must include proposed_content, memory_type, target_scope, target_namespace")
        rationale = str(spec.get("summary") or payload.get("rationale") or "Proposed from run output")[:8000]
        now = _utcnow()
        prop = build_memory_update_proposal(
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
            target_visibility=str(payload.get("target_visibility") or "private"),
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
        link_run_outputs_to_tasks(self.db, run=run, artifact=None, proposal=prop, proposal_role="memory_update")

    def _code_patch_proposal(self, run: Run, spec: dict[str, Any], user_id: str) -> None:
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
        prop = Proposal(
            id=_new_id(),
            space_id=run.space_id,
            proposal_type="code_patch",
            status="pending",
            title=title,
            summary=str(spec.get("summary") or "")[:8000] or None,
            payload_json={
                "patch": patch,
                "source_run_id": run.id,
                "materialized_from_adapter": True,
            },
            rationale=rationale,
            workspace_id=ws.id,
            created_by_user_id=user_id,
            created_by_run_id=run.id,
            risk_level="low",
            urgency="normal",
            review_deadline=now + timedelta(hours=48),
            expires_at=now + timedelta(days=14),
        )
        self.db.add(prop)
        link_run_outputs_to_tasks(self.db, run=run, artifact=None, proposal=prop, proposal_role="code_patch")
