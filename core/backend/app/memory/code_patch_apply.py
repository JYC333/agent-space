"""Apply approved ``code_patch`` proposals to workspace files (minimal replace_file)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..models import ActivityRecord, Workspace
from ..workspace.path_policy import PathPolicy, PathPolicyError
from ..workspace.disk_path import workspace_absolute_root


class CodePatchApplyError(ValueError):
    """User-visible failure when a patch cannot be applied safely."""


def _reject_traversal(rel: str) -> None:
    p = Path(rel)
    if p.is_absolute():
        raise CodePatchApplyError("absolute paths are not allowed in code_patch")
    if ".." in p.parts:
        raise CodePatchApplyError("path traversal is not allowed in code_patch")


def apply_code_patch_payload(
    db: Session,
    *,
    workspace: Workspace,
    patch: dict,
    space_id: str,
    user_id: str,
    source_run_id: str | None,
    proposal_id: str,
) -> list[str]:
    """
    Apply ``replace_file`` operations under the workspace root.

    Raises :class:`CodePatchApplyError` on any validation or unsupported-op error.
    """
    ops = patch.get("operations")
    if not isinstance(ops, list) or not ops:
        raise CodePatchApplyError("patch.operations must be a non-empty list")

    root = workspace_absolute_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    policy = PathPolicy()
    updated: list[str] = []

    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise CodePatchApplyError(f"operations[{i}] must be an object")
        kind = op.get("op")
        if kind != "replace_file":
            raise CodePatchApplyError(f"unsupported operation {kind!r} (only replace_file is supported)")
        rel = op.get("path")
        if not isinstance(rel, str) or not rel.strip():
            raise CodePatchApplyError(f"operations[{i}].path must be a non-empty string")
        rel = rel.strip().replace("\\", "/")
        _reject_traversal(rel)
        dest = (root / Path(rel)).resolve()
        try:
            dest.relative_to(root)
        except ValueError as exc:
            raise CodePatchApplyError("resolved path escapes workspace root") from exc
        try:
            policy.validate(
                dest,
                allowed_root=root,
                mode="write",
                for_trusted_code_patch_apply=True,
            )
        except PathPolicyError as exc:
            raise CodePatchApplyError(str(exc)) from exc

        content = op.get("content")
        if content is not None and not isinstance(content, str):
            raise CodePatchApplyError(f"operations[{i}].content must be a string when present")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content if content is not None else "", encoding="utf-8")
        updated.append(rel)

    _record_applied_activity(
        db,
        space_id=space_id,
        user_id=user_id,
        source_run_id=source_run_id,
        proposal_id=proposal_id,
        paths=updated,
    )
    return updated


def _record_applied_activity(
    db: Session,
    *,
    space_id: str,
    user_id: str,
    source_run_id: str | None,
    proposal_id: str,
    paths: list[str],
) -> None:
    from datetime import UTC, datetime
    from ulid import ULID

    now = datetime.now(UTC)
    db.add(
        ActivityRecord(
            id=str(ULID()),
            space_id=space_id,
            source_run_id=source_run_id,
            user_id=user_id,
            activity_type="proposal.code_patch.applied",
            title="Code patch proposal applied",
            content=(", ".join(paths))[:8000],
            payload_json={"proposal_id": proposal_id, "paths": paths},
            occurred_at=now,
            status="processed",
            updated_at=now,
        )
    )
