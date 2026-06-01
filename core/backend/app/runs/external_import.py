from __future__ import annotations
import uuid
"""ExternalRunImportService — minimal import path for externally executed runs.

Supports importing results from Codex CLI, Claude Code CLI, Cursor, OpenCode,
and manually pasted run summaries. External output is evidence, not internal
truth: long-term changes still go through proposals.

Import flow:
  Run (source=manual_import|remote_import)
  → ExternalRunRecord
  → Artifact (optional, per imported file)
  → RunReflection (created separately via ReflectionService)
  → Proposal candidates (created separately via ReflectionProposalBuilder)
"""

import logging
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from ..models import Run, ContextSnapshot, ExternalRunRecord, Artifact

log = logging.getLogger(__name__)

_VALID_VENDORS = frozenset({"openai", "anthropic", "cursor", "opencode", "manual", "other"})
_VALID_SOURCES = frozenset({"manual_import", "remote_import"})


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ImportedArtifact:
    """Lightweight descriptor for one artifact to attach to an imported run."""
    artifact_type: str        # e.g. "code_patch", "log", "summary_text"
    title: str
    content: str | None = None
    storage_ref: str | None = None
    mime_type: str | None = None
    trust_level: str = "unknown"


@dataclass
class ExternalRunImport:
    """Input for import_external_run()."""
    space_id: str
    agent_id: str
    agent_version_id: str
    vendor: str                               # openai|anthropic|cursor|opencode|manual|other
    source: str = "manual_import"             # manual_import|remote_import
    workspace_id: str | None = None
    vendor_run_id: str | None = None
    runtime_adapter_id: str | None = None
    execution_plane_id: str | None = None
    external_url: str | None = None
    observability_level: str = "black_box"    # imported runs are opaque by default
    data_exposure_level: str = "unknown"
    raw_summary: str | None = None
    raw_output_uri: str | None = None
    imported_diff_uri: str | None = None
    imported_logs_uri: str | None = None
    artifacts: list[ImportedArtifact] = field(default_factory=list)


@dataclass
class ExternalRunImportResult:
    run: Run
    external_record: ExternalRunRecord
    artifacts: list[Artifact]


class ExternalRunImportService:
    """Import an externally executed run as an evidence record.

    Does not execute code. Does not write to memory, policy, or workspace profile.
    Produces only Run + ExternalRunRecord + optional Artifacts.
    All FK inputs (workspace_id, runtime_adapter_id, execution_plane_id) are
    validated against space_id before any rows are created.
    """

    def __init__(self, db: Session):
        self.db = db

    def _validate_space_fks(self, imp: ExternalRunImport) -> None:
        """Validate that all optional FK references belong to imp.space_id."""
        if imp.workspace_id:
            from ..models import Workspace
            ws = self.db.query(Workspace).filter(
                Workspace.id == imp.workspace_id,
                Workspace.owner_space_id == imp.space_id,
            ).first()
            if not ws:
                raise ValueError(
                    f"Workspace '{imp.workspace_id}' not found in space '{imp.space_id}'"
                )

        if imp.runtime_adapter_id:
            from ..models import RuntimeAdapter
            adapter = self.db.query(RuntimeAdapter).filter(
                RuntimeAdapter.id == imp.runtime_adapter_id,
                RuntimeAdapter.space_id == imp.space_id,
            ).first()
            if not adapter:
                raise ValueError(
                    f"RuntimeAdapter '{imp.runtime_adapter_id}' not found in space '{imp.space_id}'"
                )

        if imp.execution_plane_id:
            from ..models import ExecutionPlane
            plane = self.db.query(ExecutionPlane).filter(
                ExecutionPlane.id == imp.execution_plane_id,
                ExecutionPlane.space_id == imp.space_id,
            ).first()
            if not plane:
                raise ValueError(
                    f"ExecutionPlane '{imp.execution_plane_id}' not found in space '{imp.space_id}'"
                )

    def import_external_run(self, imp: ExternalRunImport) -> ExternalRunImportResult:
        if imp.vendor not in _VALID_VENDORS:
            raise ValueError(f"Unknown vendor '{imp.vendor}'. Expected one of: {sorted(_VALID_VENDORS)}")
        if imp.source not in _VALID_SOURCES:
            raise ValueError(f"Invalid source '{imp.source}'. Expected one of: {sorted(_VALID_SOURCES)}")

        self._validate_space_fks(imp)

        externality_level = "manual" if imp.source == "manual_import" else "remote_external"

        snapshot = ContextSnapshot(
            id=_new_id(),
            space_id=imp.space_id,
            source_refs_json=[],
        )
        self.db.add(snapshot)
        self.db.flush()

        run = Run(
            id=_new_id(),
            space_id=imp.space_id,
            agent_id=imp.agent_id,
            agent_version_id=imp.agent_version_id,
            context_snapshot_id=snapshot.id,
            workspace_id=imp.workspace_id,
            run_type="agent",
            trigger_origin="manual",
            status="succeeded",
            mode="live",
            required_sandbox_level="none",
            source=imp.source,
            execution_plane_id=imp.execution_plane_id,
            runtime_adapter_id=imp.runtime_adapter_id,
            observability_level=imp.observability_level,
            data_exposure_level=imp.data_exposure_level,
            trust_level="unknown",
            externality_level=externality_level,
        )
        self.db.add(run)
        self.db.flush()

        record = ExternalRunRecord(
            id=_new_id(),
            space_id=imp.space_id,
            run_id=run.id,
            vendor=imp.vendor,
            vendor_run_id=imp.vendor_run_id,
            runtime_adapter_id=imp.runtime_adapter_id,
            execution_plane_id=imp.execution_plane_id,
            external_url=imp.external_url,
            observability_level=imp.observability_level,
            data_exposure_level=imp.data_exposure_level,
            trace_available=False,
            raw_summary=imp.raw_summary,
            raw_output_uri=imp.raw_output_uri,
            imported_diff_uri=imp.imported_diff_uri,
            imported_logs_uri=imp.imported_logs_uri,
            status="imported",
        )
        self.db.add(record)
        self.db.flush()

        artifact_rows: list[Artifact] = []
        for a in imp.artifacts:
            row = Artifact(
                id=_new_id(),
                space_id=imp.space_id,
                run_id=run.id,
                artifact_type=a.artifact_type,
                title=a.title,
                content=a.content,
                storage_ref=a.storage_ref,
                mime_type=a.mime_type,
                trust_level=a.trust_level,
                exportable=False,
                export_formats_json=[],
                preview=False,
                visibility="space_shared",
                source_execution_plane_id=imp.execution_plane_id,
            )
            self.db.add(row)
            artifact_rows.append(row)

        self.db.commit()
        self.db.refresh(run)
        self.db.refresh(record)
        return ExternalRunImportResult(run=run, external_record=record, artifacts=artifact_rows)
