"""Persist runtime outputs into canonical artifact storage."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from ulid import ULID

from ..config import settings
from ..models import Artifact, Run
from ..personal_memory_grants.egress_guard import (
    EgressDecision,
    PersonalMemoryEgressError,
    check_personal_memory_egress,
)
from ..policy.gateway import PolicyGateway, PolicyCheckRequest, PolicyDecisionRecordPersistError


def _new_id() -> str:
    return str(ULID())


def _ensure_under_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact path escapes artifact_storage_root") from exc


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
        # Policy gate: artifact.persist — before any write or egress check.
        # Never stores artifact content, file content, or personal_context_block.
        # Decision inputs (target_space_id, derived_from_personal_memory_grant,
        # raw_private_memory_included) go in context so HardInvariantGuard reads
        # them as authoritative.
        # Audit-only fields stay in metadata_json.
        try:
            _persist_decision = PolicyGateway(self.db).check_and_record(
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
                    metadata_json={
                        "artifact_type": artifact_type,
                        "target_space_id": run.space_id,
                        "target_workspace_id": str(run.workspace_id) if run.workspace_id else None,
                        "source_run_id": str(run.id),
                        "preview": preview,
                    },
                )
            )
        except PolicyDecisionRecordPersistError:
            raise PersonalMemoryEgressError(
                "policy_decision_record_persist_failed: policy audit record persistence "
                "failed for artifact.persist. No artifact written.",
                grant_id=None,
            )
        if _persist_decision.denied:
            raise PersonalMemoryEgressError(
                f"artifact.persist denied by policy: {_persist_decision.message}",
                grant_id=None,
            )
        if _persist_decision.requires_approval:
            raise PersonalMemoryEgressError(
                f"artifact.persist requires approval: {_persist_decision.message}",
                grant_id=None,
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
        # Policy gate: artifact.persist — before any write or egress check.
        # Decision inputs go in context; audit-only fields stay in metadata_json.
        try:
            _persist_decision = PolicyGateway(self.db).check_and_record(
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
                    metadata_json={
                        "artifact_type": artifact_type,
                        "target_space_id": run.space_id,
                        "target_workspace_id": str(run.workspace_id) if run.workspace_id else None,
                        "source_run_id": str(run.id),
                        "source_relative_path_hash": (
                            source_relative_path[:64] if source_relative_path else None
                        ),
                        "preview": preview,
                    },
                )
            )
        except PolicyDecisionRecordPersistError:
            raise PersonalMemoryEgressError(
                "policy_decision_record_persist_failed: policy audit record persistence "
                "failed for artifact.persist. No artifact written.",
                grant_id=None,
            )
        if _persist_decision.denied:
            raise PersonalMemoryEgressError(
                f"artifact.persist denied by policy: {_persist_decision.message}",
                grant_id=None,
            )
        if _persist_decision.requires_approval:
            raise PersonalMemoryEgressError(
                f"artifact.persist requires approval: {_persist_decision.message}",
                grant_id=None,
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
