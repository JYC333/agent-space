"""Ingest ``RuntimeAdapterResult.produced_artifact_paths`` into managed artifact storage."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy.orm import Session

from ..models import Run
from ..workspace.path_policy import PathPolicy, PathPolicyError
from .artifact_persistence import ArtifactPersistenceService
from .task_output_linkage import link_run_outputs_to_tasks


def assert_safe_produced_relative_path(rel: str) -> None:
    """Reject absolute paths and ``..`` traversal in adapter-declared relative paths."""
    p = Path(rel)
    if p.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if ".." in p.parts:
        raise ValueError("path traversal is not allowed")


def parse_produced_artifact_entry(raw: Any) -> tuple[str, dict[str, Any]]:
    """Normalize one ``produced_artifact_paths`` entry to ``(relative_posix_path, extra_fields)``."""
    if isinstance(raw, str):
        s = raw.strip().replace("\\", "/")
        if not s:
            raise ValueError("empty path")
        return s, {}
    if isinstance(raw, dict):
        p = raw.get("path")
        if not isinstance(p, str) or not p.strip():
            raise ValueError("path is required")
        extra: dict[str, Any] = {}
        for k in ("artifact_type", "title", "mime_type"):
            v = raw.get(k)
            if v is not None:
                extra[k] = v
        return p.strip().replace("\\", "/"), extra
    raise TypeError("entry must be a string or an object")


def ingest_produced_artifact_paths(
    db: Session,
    *,
    run: Run,
    source_root: str | None,
    entries: Sequence[Any] | None,
) -> list[str]:
    """Validate, copy, and register file artifacts. Returns one error string per failed entry."""
    if not entries:
        return []
    errors: list[str] = []
    root = Path(source_root).resolve() if source_root else None
    policy = PathPolicy()
    persist = ArtifactPersistenceService(db)

    for i, raw in enumerate(entries):
        label = f"produced_artifact_paths[{i}]"
        try:
            rel_norm, meta = parse_produced_artifact_entry(raw)
            assert_safe_produced_relative_path(rel_norm)
            if root is None:
                raise ValueError(
                    "produced paths require an isolated sandbox (worktree); "
                    "this run did not use a sandbox directory"
                )
            candidate = (root / rel_norm).resolve()
            try:
                policy.validate(candidate, allowed_root=root, mode="read", workspace_type="project")
            except PathPolicyError as exc:
                raise ValueError("path is not allowed under the run sandbox") from exc
            if not candidate.is_file():
                if candidate.exists():
                    raise ValueError("not a regular file")
                raise ValueError("source file missing")
            art_type = str(meta.get("artifact_type") or "runtime_file")[:64]
            title = str(meta.get("title") or Path(rel_norm).name or art_type)[:512]
            mime_raw = meta.get("mime_type")
            mime_s = str(mime_raw)[:256] if isinstance(mime_raw, str) and mime_raw.strip() else None
            if not mime_s:
                guessed, _enc = mimetypes.guess_type(rel_norm)
                mime_s = (guessed or "application/octet-stream")[:256]
            art = persist.persist_copied_file(
                run=run,
                source_file=candidate,
                source_relative_path=rel_norm,
                title=title,
                artifact_type=art_type,
                mime_type=mime_s,
                preview=run.mode == "dry_run",
                metadata_json=None,
            )
            link_run_outputs_to_tasks(db, run=run, artifact=art, proposal=None)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    return errors
