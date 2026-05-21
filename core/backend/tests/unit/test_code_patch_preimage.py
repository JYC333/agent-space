"""Unit tests for strict code_patch preimage guards.

Invariants verified:
  Collector:
    1.  collect_worktree_changes includes preimage_sha256 and preimage_exists in ops.
    2.  New files have preimage_exists=False, preimage_sha256=None.
    3.  Modified files have preimage_exists=True, preimage_sha256 matching HEAD content.

  Apply — preimage_sha256 guard (existing files):
    4.  apply_replace with correct preimage_sha256 succeeds.
    5.  apply_replace rejects when workspace file changed after proposal creation
        (preimage mismatch → CodePatchApplyError with stale_code_patch).

  Apply — preimage_exists=False guard (new files):
    6.  apply_replace with preimage_exists=False succeeds when target does not exist.
    7.  apply_replace with preimage_exists=False raises stale_code_patch when target
        already exists (file was created after proposal).

  Apply — strict schema validation (no backward compat):
    8.  Missing preimage_exists in payload fails before writing anything.
    9.  preimage_exists=true with missing/null preimage_sha256 fails before writing anything.
    10. preimage_exists=false with non-null preimage_sha256 fails before writing anything.
    11. Missing content fails before writing anything.

  Atomicity:
    12. Two-op patch: op2 has stale preimage → op1 is rolled back, workspace unchanged.
    13. Two-op patch: op2 targets a new-file path that already exists → op1 rolled back.
    14. op1 rolled back when op2 missing preimage_exists (schema validation failure).

  End-to-end:
    15. apply_code_patch_payload rejects stale file.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

from app.runs.code_patch_collector import collect_worktree_changes
from app.memory.code_patch_apply import (
    CodePatchApplyError,
    CodePatchFileTransaction,
    apply_code_patch_payload,
)
from app.workspace.path_policy import PathPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "original") -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(path))
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


# ===========================================================================
# 1. collect_worktree_changes includes preimage_sha256 and preimage_exists
# ===========================================================================


def test_collect_modified_file_has_preimage_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "hello.txt", "original content")
    (repo / "hello.txt").write_text("modified content", encoding="utf-8")

    ops, _ = collect_worktree_changes(repo)

    assert len(ops) == 1
    assert "preimage_sha256" in ops[0]
    assert "preimage_exists" in ops[0]
    assert ops[0]["preimage_exists"] is True
    assert ops[0]["preimage_sha256"] == _sha256(b"original content")


# ===========================================================================
# 2. New files have preimage_exists=False, preimage_sha256=None
# ===========================================================================


def test_collect_new_file_has_preimage_exists_false(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "new_file.py").write_text("brand new", encoding="utf-8")
    subprocess.run(["git", "add", "new_file.py"], check=True, capture_output=True, cwd=str(repo))

    ops, _ = collect_worktree_changes(repo)

    new_op = next(op for op in ops if op["path"] == "new_file.py")
    assert new_op["preimage_exists"] is False
    assert new_op["preimage_sha256"] is None


# ===========================================================================
# 3. Preimage matches original HEAD content
# ===========================================================================


def test_preimage_sha256_matches_head_content(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    original = "hello from HEAD"
    _init_git_repo(repo, "file.txt", original)
    (repo / "file.txt").write_text("completely different", encoding="utf-8")

    ops, _ = collect_worktree_changes(repo)
    assert len(ops) == 1
    assert ops[0]["preimage_exists"] is True
    assert ops[0]["preimage_sha256"] == _sha256(original.encode())


# ===========================================================================
# 4. apply_replace with correct preimage succeeds
# ===========================================================================


def test_apply_replace_correct_preimage_succeeds(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    original = b"original file content"
    (root / "a.txt").write_bytes(original)

    tx = CodePatchFileTransaction(root=root, policy=PathPolicy())
    tx.apply_replace(
        rel="a.txt",
        content="updated content",
        expected_preimage_sha256=_sha256(original),
        expected_preimage_exists=True,
    )
    assert (root / "a.txt").read_text() == "updated content"


# ===========================================================================
# 5. apply_replace rejects mismatched preimage (stale_code_patch)
# ===========================================================================


def test_apply_replace_rejects_stale_preimage(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "a.txt").write_bytes(b"original")

    # Workspace file changed concurrently after proposal creation.
    (root / "a.txt").write_bytes(b"concurrently modified")

    tx = CodePatchFileTransaction(root=root, policy=PathPolicy())
    with pytest.raises(CodePatchApplyError, match="stale_code_patch"):
        tx.apply_replace(
            rel="a.txt",
            content="agent changes",
            expected_preimage_sha256=_sha256(b"original"),
            expected_preimage_exists=True,
        )

    # File must NOT have been written.
    assert (root / "a.txt").read_bytes() == b"concurrently modified"


# ===========================================================================
# 6. apply_replace with preimage_exists=False succeeds when file absent
# ===========================================================================


def test_apply_replace_new_file_preimage_exists_false_succeeds(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    # File does not exist yet — OK for a new-file operation.

    tx = CodePatchFileTransaction(root=root, policy=PathPolicy())
    tx.apply_replace(
        rel="brand_new.txt",
        content="new content",
        expected_preimage_sha256=None,
        expected_preimage_exists=False,
    )
    assert (root / "brand_new.txt").read_text() == "new content"


# ===========================================================================
# 7. apply_replace with preimage_exists=False raises when file was created
# ===========================================================================


def test_apply_replace_new_file_guard_rejects_when_file_exists(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    # Someone created the file after the proposal was made.
    (root / "new.txt").write_bytes(b"created after proposal")

    tx = CodePatchFileTransaction(root=root, policy=PathPolicy())
    with pytest.raises(CodePatchApplyError, match="file_created_after_proposal"):
        tx.apply_replace(
            rel="new.txt",
            content="agent content",
            expected_preimage_sha256=None,
            expected_preimage_exists=False,
        )

    # File must remain unchanged.
    assert (root / "new.txt").read_bytes() == b"created after proposal"


# ===========================================================================
# 8. Missing preimage_exists in payload fails before writing anything
# ===========================================================================


def test_missing_preimage_exists_fails_before_write(tmp_path, db):
    from tests.support import factories

    space_id = "test-missing-preimage-exists"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "target.txt").write_bytes(b"original")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "target.txt",
                "content": "new content",
                # preimage_exists omitted — must be rejected
                "preimage_sha256": _sha256(b"original"),
            }
        ]
    }

    with mock_patch("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
        with pytest.raises(CodePatchApplyError, match="preimage_exists must be a bool"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-missing-preimage-exists-id",
            )

    assert (root / "target.txt").read_bytes() == b"original"


# ===========================================================================
# 9. preimage_exists=true with missing/null preimage_sha256 fails before write
# ===========================================================================


def test_preimage_exists_true_with_null_sha_fails_before_write(tmp_path, db):
    from tests.support import factories

    space_id = "test-true-null-sha"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "target.txt").write_bytes(b"original")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "target.txt",
                "content": "new content",
                "preimage_exists": True,
                "preimage_sha256": None,  # invalid: must be non-empty string
            }
        ]
    }

    with mock_patch("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
        with pytest.raises(CodePatchApplyError, match="preimage_sha256 must be a non-empty string"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-true-null-sha-id",
            )

    assert (root / "target.txt").read_bytes() == b"original"


# ===========================================================================
# 10. preimage_exists=false with non-null preimage_sha256 fails before write
# ===========================================================================


def test_preimage_exists_false_with_nonnull_sha_fails_before_write(tmp_path, db):
    from tests.support import factories

    space_id = "test-false-nonnull-sha"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "new_file.txt",
                "content": "content",
                "preimage_exists": False,
                "preimage_sha256": "abc123def456",  # invalid: must be null for new files
            }
        ]
    }

    with mock_patch("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
        with pytest.raises(CodePatchApplyError, match="preimage_sha256 must be null"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-false-nonnull-sha-id",
            )

    assert not (root / "new_file.txt").exists()


# ===========================================================================
# 11. Missing content fails before writing anything
# ===========================================================================


def test_missing_content_fails_before_write(tmp_path, db):
    from tests.support import factories

    space_id = "test-missing-content"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "target.txt").write_bytes(b"original")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "target.txt",
                # content omitted — must be rejected
                "preimage_exists": True,
                "preimage_sha256": _sha256(b"original"),
            }
        ]
    }

    with mock_patch("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
        with pytest.raises(CodePatchApplyError, match="content must be a string"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-missing-content-id",
            )

    assert (root / "target.txt").read_bytes() == b"original"


# ===========================================================================
# 12. Atomicity: op2 stale preimage → op1 rolled back
# ===========================================================================


def test_atomicity_op1_rolled_back_when_op2_stale(tmp_path, db):  # noqa: F811
    from tests.support import factories

    space_id = "test-atomic-rollback"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "op1.txt").write_bytes(b"op1 original")
    (root / "op2.txt").write_bytes(b"op2 original")

    # op2 was "original" at proposal creation but is now "modified" — stale.
    (root / "op2.txt").write_bytes(b"op2 modified concurrently")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "op1.txt",
                "content": "op1 new content",
                "preimage_sha256": _sha256(b"op1 original"),
                "preimage_exists": True,
            },
            {
                "op": "replace_file",
                "path": "op2.txt",
                "content": "op2 new content",
                "preimage_sha256": _sha256(b"op2 original"),  # stale: workspace changed
                "preimage_exists": True,
            },
        ]
    }

    with mock_patch(
        "app.memory.code_patch_apply.workspace_absolute_root",
        return_value=root,
    ):
        with pytest.raises(CodePatchApplyError, match="stale_code_patch"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-atomic-id",
            )

    # op1 must have been rolled back — workspace unchanged.
    assert (root / "op1.txt").read_bytes() == b"op1 original"
    assert (root / "op2.txt").read_bytes() == b"op2 modified concurrently"


# ===========================================================================
# 13. Atomicity: op2 new-file guard fires → op1 rolled back
# ===========================================================================


def test_atomicity_op1_rolled_back_when_op2_file_exists(tmp_path, db):
    from tests.support import factories

    space_id = "test-atomic-newfile"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "existing.txt").write_bytes(b"existing op1 content")
    # op2 claims to be a new file, but the workspace already has it.
    (root / "supposed_new.txt").write_bytes(b"created after proposal")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "existing.txt",
                "content": "updated existing",
                "preimage_sha256": _sha256(b"existing op1 content"),
                "preimage_exists": True,
            },
            {
                "op": "replace_file",
                "path": "supposed_new.txt",
                "content": "agent wrote this",
                "preimage_sha256": None,
                "preimage_exists": False,  # new-file guard: must not exist
            },
        ]
    }

    with mock_patch(
        "app.memory.code_patch_apply.workspace_absolute_root",
        return_value=root,
    ):
        with pytest.raises(CodePatchApplyError, match="file_created_after_proposal"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-newfile-id",
            )

    # op1 must have been rolled back.
    assert (root / "existing.txt").read_bytes() == b"existing op1 content"
    assert (root / "supposed_new.txt").read_bytes() == b"created after proposal"


# ===========================================================================
# 14. Atomicity: op2 missing preimage_exists (schema error) → op1 rolled back
# ===========================================================================


def test_atomicity_op1_rolled_back_when_op2_schema_invalid(tmp_path, db):
    from tests.support import factories

    space_id = "test-atomic-schema-invalid"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "op1.txt").write_bytes(b"op1 original")

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "op1.txt",
                "content": "op1 new content",
                "preimage_sha256": _sha256(b"op1 original"),
                "preimage_exists": True,
            },
            {
                "op": "replace_file",
                "path": "op2.txt",
                "content": "op2 content",
                # preimage_exists missing — schema validation must fail
                "preimage_sha256": None,
            },
        ]
    }

    with mock_patch("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
        with pytest.raises(CodePatchApplyError, match="preimage_exists must be a bool"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-schema-atomic-id",
            )

    # op1 must have been rolled back — workspace unchanged.
    assert (root / "op1.txt").read_bytes() == b"op1 original"
    assert not (root / "op2.txt").exists()


# ===========================================================================
# 15. apply_code_patch_payload end-to-end: stale file rejected
# ===========================================================================


def test_apply_code_patch_payload_rejects_stale_file(tmp_path, db):  # noqa: F811
    from tests.support import factories

    space_id = "test-preimage-e2e"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    original = b"original workspace content"
    (root / "target.txt").write_bytes(original)

    # Workspace changed after proposal was created.
    changed_content = b"someone else changed this"
    (root / "target.txt").write_bytes(changed_content)

    patch = {
        "operations": [
            {
                "op": "replace_file",
                "path": "target.txt",
                "content": "agent output",
                "preimage_sha256": _sha256(original),  # hash of the original, now stale
                "preimage_exists": True,
            }
        ]
    }

    with mock_patch(
        "app.memory.code_patch_apply.workspace_absolute_root",
        return_value=root,
    ):
        with pytest.raises(CodePatchApplyError, match="stale_code_patch"):
            apply_code_patch_payload(
                db,
                workspace=ws,
                patch=patch,
                space_id=space_id,
                user_id=user.id,
                source_run_id=None,
                proposal_id="test-proposal-id",
            )

    assert (root / "target.txt").read_bytes() == changed_content


# ===========================================================================
# 16. Regression: DB commit failure triggers file rollback; no orphan activity
# ===========================================================================


def test_db_commit_failure_rolls_back_files_and_no_orphan_activity(tmp_path, db):
    """If the DB commit in ProposalService.accept() fails, file writes must roll
    back and no proposal.code_patch.applied ActivityRecord must persist."""
    from unittest.mock import patch as mock_patch_ctx
    from tests.support import factories
    from app.memory.proposals import ProposalService
    from app.models import ActivityRecord, Proposal
    from app.db_uow import UnitOfWork

    space_id = "test-db-txn-regression"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)

    root = tmp_path / "workspace"
    root.mkdir()
    original = b"original"
    (root / "target.txt").write_bytes(original)

    prop = factories.create_test_proposal(
        db,
        space_id=space_id,
        created_by_user_id=user.id,
        proposal_type="code_patch",
        workspace_id=ws.id,
        title="regression test",
        payload_json={
            "patch": {
                "operations": [
                    {
                        "op": "replace_file",
                        "path": "target.txt",
                        "content": "new content",
                        "preimage_exists": True,
                        "preimage_sha256": _sha256(original),
                    }
                ]
            },
            "source_run_id": None,
        },
        commit=True,
    )
    prop_id = prop.id

    # Simulate a DB commit failure AFTER file writes have succeeded.
    original_commit = UnitOfWork.commit

    commit_calls = {"count": 0}

    def failing_commit(self):
        commit_calls["count"] += 1
        if commit_calls["count"] == 1:
            raise RuntimeError("simulated DB commit failure")
        return original_commit(self)

    with mock_patch_ctx("app.workspace.disk_path.workspace_absolute_root", return_value=root):
        with mock_patch_ctx("app.memory.code_patch_apply.workspace_absolute_root", return_value=root):
            with mock_patch_ctx.object(UnitOfWork, "commit", failing_commit):
                try:
                    ProposalService(db).accept(prop_id, space_id, user.id)
                except Exception:
                    pass  # expected — the commit failed

    # Files must be rolled back to their original state.
    assert (root / "target.txt").read_bytes() == original

    # Proposal must NOT be accepted (still pending or original status).
    db.expire_all()
    refreshed_prop = db.query(Proposal).filter(Proposal.id == prop_id).first()
    assert refreshed_prop is not None
    assert refreshed_prop.status != "accepted"

    # No orphan activity record with proposal.code_patch.applied must exist.
    activities = (
        db.query(ActivityRecord)
        .filter(
            ActivityRecord.activity_type == "proposal.code_patch.applied",
            ActivityRecord.payload_json["proposal_id"].as_string() == prop_id,
        )
        .all()
    )
    assert activities == []
