"""Apply approved ``code_patch`` proposals to workspace files.

File writes are staged through a narrow local file transaction. The proposal
accept path commits DB state after file replacement; if that DB commit fails,
callers can roll file changes back from captured preimages.

Schema contract (strict — no backward compatibility):
  Every replace_file operation must include:
    op              = "replace_file"
    path            = non-empty string
    content         = string
    preimage_exists = bool (true = file existed at proposal creation time)
    preimage_sha256 = non-empty string when preimage_exists=true, else null

  preimage_exists=true  → file must currently exist and sha256 must match;
                          otherwise raises stale_code_patch:preimage_mismatch.
  preimage_exists=false → file must currently not exist and preimage_sha256 must
                          be null; otherwise raises stale_code_patch:file_created_after_proposal.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import ActivityRecord, Workspace
from ..policy.gateway import PolicyGateway, PolicyCheckRequest, PolicyDecisionRecordPersistError
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

    def apply_replace(
        self,
        *,
        rel: str,
        content: str,
        expected_preimage_sha256: str | None,
        expected_preimage_exists: bool,
    ) -> None:
        dest = self._validate_dest(rel)
        data = content.encode("utf-8")
        pre_bytes = dest.read_bytes() if dest.exists() else None

        if expected_preimage_exists:
            # File must exist and sha256 must match the preimage taken at proposal creation time.
            current_sha = _sha256(pre_bytes) if pre_bytes is not None else None
            if current_sha != expected_preimage_sha256:
                raise CodePatchApplyError(
                    f"stale_code_patch: preimage_mismatch for {_safe_rel(rel)!r} — "
                    "the workspace file was modified after this proposal was created. "
                    "Reject the proposal and re-run the agent to generate a fresh one."
                )
        else:
            # File must not exist — if it does, it was created after the proposal.
            if pre_bytes is not None:
                raise CodePatchApplyError(
                    f"stale_code_patch: file_created_after_proposal for {_safe_rel(rel)!r} — "
                    "the file did not exist when this proposal was created but now exists. "
                    "Reject the proposal and re-run the agent to generate a fresh one."
                )

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
    # Policy gate: workspace.write_patch — record before any file writes.
    # Human-accepted code_patch proposal satisfies the review requirement, but
    # the decision is recorded for audit evidence. Store safe summary only —
    # never the patch body or file content.
    ops = patch.get("operations")
    if not isinstance(ops, list) or not ops:
        raise CodePatchApplyError("patch.operations must be a non-empty list")

    _safe_paths = [
        str(op.get("path", ""))[:256]
        for op in ops[:32]
        if isinstance(op, dict)
    ]
    try:
        _patch_decision = PolicyGateway(db).check_and_record(
            PolicyCheckRequest(
                action="workspace.write_patch",
                actor_type="user",
                actor_id=user_id,
                space_id=space_id,
                resource_type="workspace",
                resource_id=str(workspace.id),
                proposal_id=proposal_id,
                context={
                    "proposal_type": "code_patch",
                    "proposal_apply_allowed": True,
                },
                metadata_json={
                    "ops_count": len(ops),
                    "paths": _safe_paths,
                    "source_run_id": source_run_id,
                    "proposal_id": proposal_id,
                },
                force_record=True,
            )
        )
    except PolicyDecisionRecordPersistError:
        raise CodePatchApplyError(
            "policy_decision_record_persist_failed: policy audit record persistence "
            "failed for workspace.write_patch. No files written."
        )
    if _patch_decision.denied:
        raise CodePatchApplyError(
            f"workspace.write_patch denied by policy: {_patch_decision.message}"
        )
    if _patch_decision.requires_approval:
        raise CodePatchApplyError(
            f"workspace.write_patch requires an accepted code_patch proposal: {_patch_decision.message}"
        )

    root = workspace_absolute_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    policy = PathPolicy()
    tx = CodePatchFileTransaction(root=root, policy=policy)

    # Validate and apply all operations inside a single try block so that any
    # failure (preimage mismatch, file-write error, or validation error) rolls
    # back ALL previously applied operations before re-raising.  This makes the
    # entire payload atomic: either every operation lands, or none do.
    try:
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
            if not isinstance(content, str):
                raise CodePatchApplyError(f"operations[{i}].content must be a string")

            # preimage_exists is required and must be a real bool.
            preimage_exists_raw = op.get("preimage_exists")
            if not isinstance(preimage_exists_raw, bool):
                raise CodePatchApplyError(
                    f"operations[{i}].preimage_exists must be a bool (true or false)"
                )
            preimage_exists: bool = preimage_exists_raw

            # preimage_sha256 must be consistent with preimage_exists.
            expected_preimage = op.get("preimage_sha256")
            if preimage_exists:
                if not isinstance(expected_preimage, str) or not expected_preimage:
                    raise CodePatchApplyError(
                        f"operations[{i}].preimage_sha256 must be a non-empty string when preimage_exists=true"
                    )
            else:
                if expected_preimage is not None:
                    raise CodePatchApplyError(
                        f"operations[{i}].preimage_sha256 must be null when preimage_exists=false"
                    )

            tx.apply_replace(
                rel=rel,
                content=content,
                expected_preimage_sha256=expected_preimage if preimage_exists else None,
                expected_preimage_exists=preimage_exists,
            )
    except CodePatchApplyError:
        # apply_replace() rolls back internally for file-write failures.
        # For preimage/validation errors it raises before any write, so prior
        # successfully applied operations would remain on disk.  Explicitly
        # rolling back here makes the entire payload atomic.
        try:
            tx.rollback()
        except CodePatchApplyError as rollback_exc:
            raise CodePatchPartialApplyError(
                "code_patch apply failed and rollback also failed — "
                "workspace may be in a partially-modified state"
            ) from rollback_exc
        raise

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
