"""Persist runtime outputs into canonical artifact storage."""

from __future__ import annotations
import uuid

import hashlib
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Artifact, Run
from ..personal_memory_grants.egress_guard import (
    EgressDecision,
    PersonalMemoryEgressError,
    check_personal_memory_egress,
)
from ..policy import write_blocked_gate_audit
from ..policy import PolicyAuditPersistError, PolicyGateBlocked
from ..policy import PolicyCheckRequest, get_policy_port


def _new_id() -> str:
    return str(uuid.uuid4())


def _ensure_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact path escapes artifact_storage_root") from exc


_ARTIFACT_AUDIT_FAILURE = (
    "policy_decision_record_persist_failed: policy audit record persistence "
    "failed for artifact.persist. No artifact written."
)


def _enforce_artifact_persist_policy(
    db: Session,
    *,
    run: Run,
    artifact_type: str,
    preview: bool,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Gate artifact persistence before egress checks, file writes, or DB rows."""
    metadata_json = {
        "artifact_type": artifact_type,
        "target_space_id": run.space_id,
        "target_workspace_id": str(run.workspace_id) if run.workspace_id else None,
        "source_run_id": str(run.id),
        "preview": preview,
    }
    if extra_metadata:
        metadata_json.update(extra_metadata)

    try:
        get_policy_port(db).enforce(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_type="run",
                actor_id=str(run.id),
                space_id=run.space_id,
                resource_type="artifact",
                run_id=str(run.id),
                context={
                    "target_space_id": run.space_id,
                    "derived_from_personal_memory_grant": bool(
                        getattr(run, "has_personal_grant_context", False)
                    ),
                    "raw_private_memory_included": False,
                },
                metadata_json=metadata_json,
            )
        )
    except PolicyGateBlocked as exc:
        try:
            write_blocked_gate_audit(exc)
        except Exception as audit_exc:
            raise PersonalMemoryEgressError(_ARTIFACT_AUDIT_FAILURE, grant_id=None) from audit_exc
        if exc.decision.requires_approval:
            raise PersonalMemoryEgressError(
                f"artifact.persist requires approval: {exc.decision.message}",
                grant_id=None,
            ) from exc
        raise PersonalMemoryEgressError(
            f"artifact.persist denied by policy: {exc.decision.message}",
            grant_id=None,
        ) from exc
    except PolicyAuditPersistError as exc:
        raise PersonalMemoryEgressError(_ARTIFACT_AUDIT_FAILURE, grant_id=None) from exc


class ArtifactPersistenceService:
    """Copy or write adapter outputs under ``artifact_storage_root``."""

    def __init__(self, db: Session):
        self.db = db

    def persist_text_file(
        self,
        *,
        run: Run,
        text: str,
        title: str,
        artifact_type: str = "runtime_output",
        preview: bool = False,
    ) -> Artifact:
        """Write UTF-8 text to persisted storage and create an ``Artifact`` row."""
        _enforce_artifact_persist_policy(
            self.db,
            run=run,
            artifact_type=artifact_type,
            preview=preview,
        )

        # Egress guard: block grant-derived artifacts targeting non-personal spaces.
        egress = check_personal_memory_egress(
            self.db,
            run=run,
            target_space_id=run.space_id,
            target_object_type="artifact",
            operation="persist_text_file",
        )
        if egress.decision == EgressDecision.BLOCK:
            raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)

        art_id = _new_id()
        rel = f"{run.space_id}/runs/{run.id}/{art_id}.txt"
        root = Path(settings.artifact_storage_root).resolve()
        dest = (root / rel).resolve()
        _ensure_under_root(dest, root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

        artifact = Artifact(
            id=art_id,
            space_id=run.space_id,
            run_id=run.id,
            project_id=run.project_id,
            artifact_type=artifact_type,
            title=title,
            content=None,
            mime_type="text/plain",
            exportable=True,
            preview=preview,
            storage_path=rel.replace("\\", "/"),
            storage_ref=None,
            owner_user_id=run.instructed_by_user_id,
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact

    def persist_copied_file(
        self,
        *,
        run: Run,
        source_file: Path,
        source_relative_path: str,
        title: str,
        artifact_type: str = "runtime_file",
        mime_type: str | None = None,
        preview: bool = False,
        metadata_json: dict[str, Any] | None = None,
    ) -> Artifact:
        """Copy a regular file from an adapter sandbox into persisted storage."""
        _enforce_artifact_persist_policy(
            self.db,
            run=run,
            artifact_type=artifact_type,
            preview=preview,
            extra_metadata={
                "source_relative_path_hash": (
                    source_relative_path[:64] if source_relative_path else None
                ),
            },
        )

        # Egress guard: block grant-derived artifacts targeting non-personal spaces.
        egress = check_personal_memory_egress(
            self.db,
            run=run,
            target_space_id=run.space_id,
            target_object_type="artifact",
            operation="persist_copied_file",
        )
        if egress.decision == EgressDecision.BLOCK:
            raise PersonalMemoryEgressError(egress.reason, grant_id=egress.grant_id)

        src = source_file.resolve()
        if not src.is_file():
            raise ValueError("source must be an existing regular file")
        art_id = _new_id()
        suffix = src.suffix if src.suffix else ""
        rel = f"{run.space_id}/runs/{run.id}/{art_id}{suffix}"
        root = Path(settings.artifact_storage_root).resolve()
        dest = (root / rel).resolve()
        _ensure_under_root(dest, root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        body = dest.read_bytes()
        meta = dict(metadata_json or {})
        meta.setdefault("ingestion_source", "produced_artifact_paths")
        meta.setdefault("source_relative_path", source_relative_path.replace("\\", "/"))
        meta["size_bytes"] = len(body)
        meta["checksum_sha256"] = hashlib.sha256(body).hexdigest()

        artifact = Artifact(
            id=art_id,
            space_id=run.space_id,
            run_id=run.id,
            project_id=run.project_id,
            artifact_type=artifact_type,
            title=title,
            content=None,
            mime_type=(mime_type or "application/octet-stream")[:256],
            exportable=True,
            preview=preview,
            storage_path=rel.replace("\\", "/"),
            storage_ref=None,
            metadata_json=meta,
            owner_user_id=run.instructed_by_user_id,
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact
