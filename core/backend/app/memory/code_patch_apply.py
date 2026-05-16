"""Apply approved ``code_patch`` proposals to workspace files.

File writes are staged through a narrow local file transaction. The proposal
accept path commits DB state after file replacement; if that DB commit fails,
callers can roll file changes back from captured preimages.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import ActivityRecord, Workspace
from ..workspace.path_policy import PathPolicy, PathPolicyError
from ..workspace.disk_path import workspace_absolute_root


class CodePatchApplyError(ValueError):
    """User-visible failure when a patch cannot be applied safely."""


class CodePatchPartialApplyError(CodePatchApplyError):
    """Raised when DB/file compensation cannot fully restore pre-apply state."""


@dataclass
class AppliedFile:
    path: str
    existed_before: bool
    preimage_sha256: str | None
    postimage_sha256: str


@dataclass
class CodePatchApplyResult:
    paths: list[str]
    files: list[AppliedFile]
    transaction: "CodePatchFileTransaction"

    def __iter__(self):
        return iter(self.paths)

    def __eq__(self, other):
        return self.paths == other


@dataclass
class _FilePreimage:
    rel: str
    dest: Path
    existed: bool
    data: bytes | None
    sha256: str | None


def _reject_traversal(rel: str) -> None:
    p = Path(rel)
    if p.is_absolute():
        raise CodePatchApplyError("absolute paths are not allowed in code_patch")
    if ".." in p.parts:
        raise CodePatchApplyError("path traversal is not allowed in code_patch")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rel(rel: str) -> str:
    return rel[:512]


class CodePatchFileTransaction:
    """Small file transaction for approved code_patch apply.

    It validates every target through PathPolicy, captures preimages, writes via
    temp files plus os.replace, and can roll back applied paths if the DB update
    that records proposal acceptance fails afterward.
    """

    def __init__(self, *, root: Path, policy: PathPolicy) -> None:
        self._root = root
        self._policy = policy
        self._preimages: list[_FilePreimage] = []
        self._applied: list[AppliedFile] = []
        self._rolled_back = False

    @property
    def applied(self) -> list[AppliedFile]:
        return list(self._applied)

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self._applied]

    def apply_replace(self, *, rel: str, content: str) -> None:
        dest = self._validate_dest(rel)
        data = content.encode("utf-8")
        pre_bytes = dest.read_bytes() if dest.exists() else None
        pre = _FilePreimage(
            rel=rel,
            dest=dest,
            existed=pre_bytes is not None,
            data=pre_bytes,
            sha256=_sha256(pre_bytes) if pre_bytes is not None else None,
        )
        self._preimages.append(pre)

        tmp_name: str | None = None
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{dest.name}.",
                suffix=".tmp",
                dir=str(dest.parent),
            )
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, dest)
            tmp_name = None
            self._applied.append(
                AppliedFile(
                    path=rel,
                    existed_before=pre.existed,
                    preimage_sha256=pre.sha256,
                    postimage_sha256=_sha256(data),
                )
            )
        except Exception as exc:  # noqa: BLE001
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                self.rollback()
            except CodePatchApplyError as rollback_exc:
                raise CodePatchPartialApplyError(
                    "code_patch file write failed and rollback also failed"
                ) from rollback_exc
            raise CodePatchApplyError(
                f"failed to apply code_patch operation for {_safe_rel(rel)!r}"
            ) from exc

    def rollback(self) -> None:
        if self._rolled_back:
            return
        failures: list[str] = []
        for pre in reversed(self._preimages):
            try:
                if pre.existed:
                    pre.dest.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp_name = tempfile.mkstemp(
                        prefix=f".{pre.dest.name}.rollback.",
                        suffix=".tmp",
                        dir=str(pre.dest.parent),
                    )
                    try:
                        with os.fdopen(fd, "wb") as fh:
                            fh.write(pre.data or b"")
                            fh.flush()
                            os.fsync(fh.fileno())
                        os.replace(tmp_name, pre.dest)
                    finally:
                        Path(tmp_name).unlink(missing_ok=True)
                else:
                    pre.dest.unlink(missing_ok=True)
            except Exception:
                failures.append(pre.rel)
        self._rolled_back = True
        if failures:
            raise CodePatchPartialApplyError(
                "code_patch rollback failed for: " + ", ".join(_safe_rel(p) for p in failures)
            )

    def _validate_dest(self, rel: str) -> Path:
        _reject_traversal(rel)
        dest = (self._root / Path(rel)).resolve()
        try:
            dest.relative_to(self._root)
        except ValueError as exc:
            raise CodePatchApplyError("resolved path escapes workspace root") from exc
        try:
            self._policy.validate(
                dest,
                allowed_root=self._root,
                mode="write",
                for_trusted_code_patch_apply=True,
            )
        except PathPolicyError as exc:
            raise CodePatchApplyError(str(exc)) from exc
        return dest


def apply_code_patch_payload(
    db: Session,
    *,
    workspace: Workspace,
    patch: dict,
    space_id: str,
    user_id: str,
    source_run_id: str | None,
    proposal_id: str,
) -> CodePatchApplyResult:
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
    tx = CodePatchFileTransaction(root=root, policy=policy)

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

        content = op.get("content")
        if content is not None and not isinstance(content, str):
            raise CodePatchApplyError(f"operations[{i}].content must be a string when present")
        tx.apply_replace(rel=rel, content=content if content is not None else "")

    _record_applied_activity(
        db,
        space_id=space_id,
        user_id=user_id,
        source_run_id=source_run_id,
        proposal_id=proposal_id,
        paths=tx.paths,
        files=tx.applied,
    )
    return CodePatchApplyResult(paths=tx.paths, files=tx.applied, transaction=tx)


def _record_applied_activity(
    db: Session,
    *,
    space_id: str,
    user_id: str,
    source_run_id: str | None,
    proposal_id: str,
    paths: list[str],
    files: list[AppliedFile],
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
            payload_json={
                "proposal_id": proposal_id,
                "paths": paths,
                "files": [
                    {
                        "path": f.path,
                        "existed_before": f.existed_before,
                        "preimage_sha256": f.preimage_sha256,
                        "postimage_sha256": f.postimage_sha256,
                    }
                    for f in files
                ],
            },
            occurred_at=now,
            status="processed",
            updated_at=now,
        )
    )
