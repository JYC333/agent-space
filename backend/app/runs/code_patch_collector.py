"""Collect workspace changes from a git worktree and materialise a pending code_patch proposal.

After a successful CLI run the worktree contains the agent's edits.  This module
diffs the worktree against HEAD, reads each changed file, and—when at least one
readable text change is found—creates a single pending ``code_patch`` Proposal so
the user can review and accept the changes.

Rules:
- Only ``replace_file`` operations are emitted (new file or modified file).
- Deleted, renamed, binary, oversized, and unreadable files are detected and
  reported in the ``skipped`` field of the proposal payload rather than silently
  dropped.  They are NOT represented as operations (delete/rename not yet
  implemented).
- The real workspace is never touched here; changes land only via proposal accept.
- Zero-operation proposals are NOT created.  If no readable text changes are found
  the result records the outcome (no-op or all-skipped) in ``run.output_json``
  instead of creating an empty proposal.
"""

from __future__ import annotations
import uuid

import hashlib
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models import Run

from ..policy import write_blocked_gate_audit
from ..policy import PolicyAuditPersistError, PolicyGateBlocked
from ..policy import PolicyCheckRequest, PolicyGateway

log = logging.getLogger(__name__)

_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB per file; skip larger files
_PROPOSAL_CREATE_AUDIT_FAILURE = (
    "policy_decision_record_persist_failed: policy audit record persistence "
    "failed for proposal.create. No proposal created."
)


def _preimage_info(worktree_path: Path, rel: str) -> tuple[str | None, bool]:
    """Return ``(sha256_hex, preimage_exists)`` for *rel* at HEAD.

    ``preimage_exists=True`` means the file existed at HEAD (modified by agent).
    ``preimage_exists=False`` means the file is new (added by agent, not in HEAD).
    ``sha256_hex`` is None when ``preimage_exists=False``.
    """
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        capture_output=True, cwd=str(worktree_path), timeout=15,
    )
    if result.returncode != 0:
        return None, False  # new file — no preimage
    return hashlib.sha256(result.stdout).hexdigest(), True


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class WorktreeCollectionResult:
    """Outcome of collecting worktree changes for a run."""

    proposal_created: bool
    """True when a code_patch Proposal row was added to the DB session."""

    ops_count: int
    """Number of replace_file operations in the created proposal (0 when no proposal)."""

    skipped: list[dict] = field(default_factory=list)
    """Files detected in the worktree diff that were not turned into operations.

    Each entry: {"path": str, "reason": str}  where reason is one of:
      "deleted", "renamed", "binary", "too_large", "not_utf8", "unreadable"
    """

    no_op_reason: str | None = None
    """Human-readable explanation when no proposal was created."""

    proposal: "Any | None" = None
    """The created Proposal ORM object when proposal_created=True, else None.

    Callers use this to link the proposal to TaskRun-associated tasks without
    requiring a separate DB query. The object is already flushed but not
    committed when returned.
    """

    incomplete_patch: bool = False
    """True when the created proposal is missing some agent changes because one or
    more files were skipped (deleted, renamed, binary, oversized, not_utf8, unreadable).
    Mirrors proposal.payload_json["incomplete_patch"] for callers that do not need
    to inspect the proposal row.
    """


# ---------------------------------------------------------------------------
# Low-level diff helpers
# ---------------------------------------------------------------------------


class GitCommandError(Exception):
    """Raised when a required git command fails during worktree collection."""


def _git(args: list[str], cwd: str, timeout: int = 30) -> str:
    """Run a git command and return stdout; raise GitCommandError on failure."""
    r = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )
    if r.returncode != 0:
        raise GitCommandError(
            f"git {' '.join(args)} failed (exit {r.returncode}): {r.stderr.strip()[:400]}"
        )
    return r.stdout


# ---------------------------------------------------------------------------
# Public collection API
# ---------------------------------------------------------------------------


def collect_worktree_changes(worktree_path: Path) -> tuple[list[dict], list[dict]]:
    """Return ``(ops, skipped)`` for every file changed in the worktree.

    *ops* — ``replace_file`` operations for modified/added text files under the
    size limit that are valid UTF-8.

    *skipped* — entries for deleted, renamed, binary, oversized, non-UTF-8, and
    unreadable files.  Format: ``{"path": str, "reason": str}``.

    Covers all change types visible via ``git diff HEAD --name-status`` and
    ``git status --porcelain``.
    """
    cwd = str(worktree_path)
    ops: list[dict] = []
    skipped: list[dict] = []

    # -----------------------------------------------------------------
    # 1. Tracked changes (M / A / D / R / C / T …) from diff HEAD
    # Raises GitCommandError if git is unavailable or the worktree is corrupt.
    # -----------------------------------------------------------------
    name_status = _git(["diff", "HEAD", "--name-status"], cwd)
    seen: set[str] = set()

    for line in name_status.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_code = parts[0][0] if parts else ""
        if status_code == "D":
            path = parts[1] if len(parts) > 1 else ""
            if path and path not in seen:
                skipped.append({"path": path, "reason": "deleted"})
                seen.add(path)
        elif status_code == "R":
            # Rename: parts = [R<score>, old, new]
            new_path = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")
            old_path = parts[1] if len(parts) > 1 else ""
            for p in (old_path, new_path):
                if p and p not in seen:
                    skipped.append({"path": p, "reason": "renamed"})
                    seen.add(p)
        elif status_code in ("M", "A", "C", "T"):
            path = parts[1] if len(parts) > 1 else ""
            if path and path not in seen:
                seen.add(path)
                _collect_text_file(worktree_path, path, ops, skipped)

    # -----------------------------------------------------------------
    # 2. Untracked new files (git status --porcelain codes ?? and A)
    # Raises GitCommandError on failure.
    # -----------------------------------------------------------------
    status_out = _git(["status", "--porcelain"], cwd)
    for line in status_out.splitlines():
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:].strip()
        if not path or path in seen:
            continue
        if code in ("??", "A "):
            seen.add(path)
            _collect_text_file(worktree_path, path, ops, skipped)

    return ops, skipped


def _collect_text_file(
    worktree_path: Path,
    rel: str,
    ops: list[dict],
    skipped: list[dict],
) -> None:
    """Attempt to read *rel* as a UTF-8 text file and append a replace_file op.

    Appends to *skipped* with the appropriate reason when the file cannot be
    included as a text operation.
    """
    file_path = worktree_path / rel
    if not file_path.exists() or not file_path.is_file():
        # File vanished between git diff and read — treat as deleted/unsupported.
        skipped.append({"path": rel, "reason": "deleted"})
        return

    size = file_path.stat().st_size
    if size > _MAX_FILE_BYTES:
        skipped.append({"path": rel, "reason": "too_large"})
        log.warning("code_patch collector: skipping %s (size=%d > %d)", rel, size, _MAX_FILE_BYTES)
        return

    try:
        content = file_path.read_bytes()
    except OSError:
        skipped.append({"path": rel, "reason": "unreadable"})
        log.warning("code_patch collector: skipping %s (unreadable)", rel)
        return

    # Binary detection: presence of null bytes is a reliable heuristic.
    if b"\x00" in content:
        skipped.append({"path": rel, "reason": "binary"})
        log.warning("code_patch collector: skipping %s (binary)", rel)
        return

    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        skipped.append({"path": rel, "reason": "not_utf8"})
        log.warning("code_patch collector: skipping %s (not UTF-8)", rel)
        return

    preimage_sha, preimage_exists = _preimage_info(worktree_path, rel)
    ops.append({
        "op": "replace_file",
        "path": rel,
        "content": text,
        # Whether the file existed at HEAD before the agent's edits.
        # True  → modified existing file; preimage_sha256 is set.
        # False → new file added by agent; preimage_sha256 is None.
        # The apply side uses these fields to detect concurrent workspace
        # changes after proposal creation (stale_code_patch guard).
        "preimage_exists": preimage_exists,
        "preimage_sha256": preimage_sha,
    })


def collect_and_create_code_patch_proposal(
    db: "Session",
    *,
    run: "Run",
    worktree_path: Path,
    validation_evidence: "Any | None" = None,
    base_commit_sha: str | None = None,
) -> WorktreeCollectionResult:
    """Diff the worktree against HEAD and create a pending ``code_patch`` Proposal.

    A Proposal is created only when at least one ``replace_file`` operation is
    collected.  Zero-operation proposals are not created — the outcome is returned
    in :class:`WorktreeCollectionResult` for the caller to persist in
    ``run.output_json``.

    The Proposal is linked to ``run.workspace_id`` and ``run.id``.
    Must be called while the worktree still exists (before sandbox cleanup).
    Commits nothing — the caller is responsible for the surrounding DB transaction.

    Returns :class:`WorktreeCollectionResult` describing what happened.
    """
    from ..models import Proposal

    ops, skipped = collect_worktree_changes(worktree_path)

    if not ops:
        if skipped:
            reason = (
                f"All {len(skipped)} changed file(s) were unsupported "
                f"(reasons: {', '.join(sorted({s['reason'] for s in skipped}))}). "
                "No code_patch proposal was created."
            )
        else:
            reason = "The CLI run completed without modifying any tracked files."
        log.info(
            "code_patch collector: no proposal for run=%s worktree=%s — %s",
            run.id, str(worktree_path), reason,
        )
        return WorktreeCollectionResult(
            proposal_created=False,
            ops_count=0,
            skipped=skipped,
            no_op_reason=reason,
        )

    # At least one text operation — build the proposal.
    file_names = [op["path"] for op in ops]
    preview = ", ".join(file_names[:5])
    if len(file_names) > 5:
        preview += f" and {len(file_names) - 5} more"
    title = f"Code changes from run {run.id[:8]}: {preview}"
    summary = f"{len(ops)} file(s) changed: {preview}"
    if skipped:
        summary += f"; {len(skipped)} file(s) skipped (unsupported change type)"

    # Mark the patch as incomplete when some changed files were skipped.
    # Callers and the UI can use this flag to warn the user that the proposal
    # does not represent the full set of agent changes.
    incomplete_patch = len(skipped) > 0

    # Attach validation evidence if provided.
    # Failed validation makes the proposal visibly risky but does NOT block creation.
    validation_dict: dict = (
        validation_evidence.to_dict()
        if validation_evidence is not None
        else {"status": "skipped", "skip_reason": "no_validation_config", "command_count": 0}
    )
    # Degrade risk_level when validation failed so reviewers see the signal.
    effective_risk_level = (
        "high"
        if validation_dict.get("status") == "failed"
        else "medium"
    )

    try:
        PolicyGateway(db).enforce(
            PolicyCheckRequest(
                action="proposal.create",
                actor_type="run",
                actor_id=str(run.id),
                space_id=run.space_id,
                resource_type="proposal",
                run_id=str(run.id),
                force_record=True,
                metadata_json={
                    "proposal_type": "code_patch",
                    "workspace_id": str(run.workspace_id) if run.workspace_id else None,
                    "source_run_id": str(run.id),
                    "risk_level": effective_risk_level,
                    "ops_count": len(ops),
                    "skipped_count": len(skipped),
                    "incomplete_patch": incomplete_patch,
                    "validation_status": validation_dict.get("status"),
                },
            )
        )
    except PolicyGateBlocked as exc:
        try:
            write_blocked_gate_audit(exc)
        except Exception:
            log.error(
                "code_patch proposal.create blocked audit failed for run=%s",
                run.id,
                exc_info=True,
            )
            return WorktreeCollectionResult(
                proposal_created=False,
                ops_count=len(ops),
                skipped=skipped,
                no_op_reason=_PROPOSAL_CREATE_AUDIT_FAILURE,
            )
        log.warning(
            "code_patch proposal.create denied by policy for run=%s: %s",
            run.id, exc.decision.message,
        )
        return WorktreeCollectionResult(
            proposal_created=False,
            ops_count=len(ops),
            skipped=skipped,
            no_op_reason=f"code_patch proposal.create denied by policy: {exc.decision.message}",
        )
    except PolicyAuditPersistError:
        log.error(
            "code_patch proposal.create allow audit failed for run=%s",
            run.id,
            exc_info=True,
        )
        return WorktreeCollectionResult(
            proposal_created=False,
            ops_count=len(ops),
            skipped=skipped,
            no_op_reason=_PROPOSAL_CREATE_AUDIT_FAILURE,
        )

    proposal = Proposal(
        id=str(uuid.uuid4()),
        space_id=run.space_id,
        created_by_run_id=run.id,
        created_by_user_id=run.instructed_by_user_id,
        proposal_type="code_patch",
        status="pending",
        risk_level=effective_risk_level,
        urgency="normal",
        title=title[:512],
        summary=summary,
        workspace_id=run.workspace_id,
        payload_json={
            "patch": {"operations": ops},
            "source_run_id": run.id,
            "worktree_collected": True,
            "file_count": len(ops),
            "skipped": skipped,
            # incomplete_patch=True when one or more changed files were skipped
            # (deleted, renamed, binary, oversized, not_utf8, unreadable).
            # Reviewers should be aware the proposal may not reflect all agent changes.
            "incomplete_patch": incomplete_patch,
            "skipped_changes": skipped,
            # Workspace HEAD commit SHA at worktree creation time.  Used to correlate
            # the proposal with the exact workspace state the agent operated on.
            "base_commit_sha": base_commit_sha,
            # Validation evidence: status, commands run, exit codes, snippets.
            # Never contains raw secrets — commands come from WorkspaceProfile.test_commands_json.
            "validation": validation_dict,
        },
    )
    db.add(proposal)
    db.flush()
    log.info(
        "code_patch proposal created run=%s workspace=%s ops=%d skipped=%d incomplete=%s",
        run.id, run.workspace_id, len(ops), len(skipped), incomplete_patch,
    )
    return WorktreeCollectionResult(
        proposal_created=True,
        ops_count=len(ops),
        skipped=skipped,
        no_op_reason=None,
        proposal=proposal,
        incomplete_patch=incomplete_patch,
    )
