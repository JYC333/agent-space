"""Unit tests for app.runs.code_patch_collector.

Covers:
  1. collect_worktree_changes: no changes → empty ops and skipped
  2. collect_worktree_changes: modified text file → replace_file op
  3. collect_worktree_changes: deleted file → in skipped, not in ops
  4. collect_worktree_changes: renamed file → both paths in skipped
  5. collect_worktree_changes: binary file → in skipped with reason=binary
  6. collect_worktree_changes: file over size limit → in skipped with reason=too_large
  7. collect_worktree_changes: non-UTF-8 file → in skipped with reason=not_utf8
  8. collect_and_create_code_patch_proposal: creates proposal when ops exist
  9. collect_and_create_code_patch_proposal: no proposal when no changes (no-op result)
 10. collect_and_create_code_patch_proposal: no proposal when all changes are unsupported;
     no_op_reason is set
 11. collect_and_create_code_patch_proposal: skipped list included in proposal payload
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.runs.code_patch_collector import (
    WorktreeCollectionResult,
    _MAX_FILE_BYTES,
    collect_and_create_code_patch_proposal,
    collect_worktree_changes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "hi") -> None:
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], check=True, capture_output=True, cwd=str(path))
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], check=True, capture_output=True, cwd=str(path))


# ===========================================================================
# 1. No changes
# ===========================================================================


def test_collect_no_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    ops, skipped = collect_worktree_changes(repo)
    assert ops == []
    assert skipped == []


# ===========================================================================
# 2. Modified text file → replace_file op
# ===========================================================================


def test_collect_modified_text_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "hello.txt", "original")
    (repo / "hello.txt").write_text("modified", encoding="utf-8")

    ops, skipped = collect_worktree_changes(repo)
    assert len(ops) == 1
    assert ops[0]["op"] == "replace_file"
    assert ops[0]["path"] == "hello.txt"
    assert "modified" in ops[0]["content"]
    assert skipped == []


# ===========================================================================
# 3. Deleted file → skipped, not in ops
# ===========================================================================


def test_collect_deleted_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "todelete.txt", "gone soon")
    (repo / "todelete.txt").unlink()
    subprocess.run(["git", "rm", "todelete.txt"], check=True, capture_output=True, cwd=str(repo))

    ops, skipped = collect_worktree_changes(repo)
    assert ops == []
    assert any(s["path"] == "todelete.txt" and s["reason"] == "deleted" for s in skipped)


# ===========================================================================
# 4. Binary file → skipped with reason=binary
# ===========================================================================


def test_collect_binary_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    # Write a file with null bytes (binary)
    (repo / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    subprocess.run(["git", "add", "data.bin"], check=True, capture_output=True, cwd=str(repo))

    ops, skipped = collect_worktree_changes(repo)
    assert all(op["path"] != "data.bin" for op in ops)
    assert any(s["path"] == "data.bin" and s["reason"] == "binary" for s in skipped)


# ===========================================================================
# 5. File over size limit → skipped with reason=too_large
# ===========================================================================


def test_collect_oversized_file(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    big = repo / "big.txt"
    big.write_text("x" * 100, encoding="utf-8")
    subprocess.run(["git", "add", "big.txt"], check=True, capture_output=True, cwd=str(repo))

    # Monkeypatch the size limit so a small file trips it
    monkeypatch.setattr("app.runs.code_patch_collector._MAX_FILE_BYTES", 10)

    ops, skipped = collect_worktree_changes(repo)
    assert all(op["path"] != "big.txt" for op in ops)
    assert any(s["path"] == "big.txt" and s["reason"] == "too_large" for s in skipped)


# ===========================================================================
# 6. Non-UTF-8 file → skipped with reason=not_utf8
# ===========================================================================


def test_collect_non_utf8_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    # Write valid non-null bytes that are not valid UTF-8
    (repo / "latin.txt").write_bytes(b"\xff\xfe latin1 \xe9\xe0\xfc")
    subprocess.run(["git", "add", "latin.txt"], check=True, capture_output=True, cwd=str(repo))

    ops, skipped = collect_worktree_changes(repo)
    assert all(op["path"] != "latin.txt" for op in ops)
    assert any(s["path"] == "latin.txt" and s["reason"] == "not_utf8" for s in skipped)


# ===========================================================================
# 7. collect_and_create_code_patch_proposal: creates proposal when ops exist
# ===========================================================================


def test_proposal_created_when_ops_exist(db, tmp_path):
    from app.models import Proposal
    from tests.support import factories

    space_id = "test-space-collector"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.workspace_id = ws.id
    db.flush()

    ops = [{"op": "replace_file", "path": "a.txt", "content": "new"}]
    skipped: list[dict] = []

    with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

    assert result.proposal_created is True
    assert result.ops_count == 1
    assert result.no_op_reason is None

    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
    assert prop is not None
    assert prop.proposal_type == "code_patch"
    assert prop.status == "pending"


# ===========================================================================
# 8. collect_and_create_code_patch_proposal: no proposal when no changes
# ===========================================================================


def test_no_proposal_when_no_changes(db, tmp_path):
    from app.models import Proposal
    from tests.support import factories

    space_id = "test-space-noop"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.workspace_id = ws.id
    db.flush()

    with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=([], [])):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

    assert result.proposal_created is False
    assert result.ops_count == 0
    assert result.no_op_reason is not None
    assert "without modifying" in result.no_op_reason.lower() or "no" in result.no_op_reason.lower()

    count = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count()
    assert count == 0, "Expected no proposal when there are no file changes"


# ===========================================================================
# 9. collect_and_create_code_patch_proposal: no proposal when all changes unsupported
# ===========================================================================


def test_no_proposal_when_all_changes_unsupported(db, tmp_path):
    from app.models import Proposal
    from tests.support import factories

    space_id = "test-space-allskip"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.workspace_id = ws.id
    db.flush()

    skipped = [
        {"path": "deleted.txt", "reason": "deleted"},
        {"path": "img.png", "reason": "binary"},
    ]

    with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=([], skipped)):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

    assert result.proposal_created is False
    assert result.ops_count == 0
    assert result.skipped == skipped
    assert result.no_op_reason is not None
    assert "unsupported" in result.no_op_reason.lower()

    count = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).count()
    assert count == 0, "Expected no proposal when all changes are unsupported"


# ===========================================================================
# 10. collect_and_create_code_patch_proposal: skipped list in proposal payload
# ===========================================================================


def test_skipped_included_in_proposal_payload(db, tmp_path):
    from app.models import Proposal
    from tests.support import factories

    space_id = "test-space-mixed"
    factories.create_test_space(db, space_id=space_id, commit=True)
    user = factories.create_test_user(db, space_id=space_id, commit=True)
    ws = factories.create_test_workspace(db, space_id=space_id, commit=True)
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=False)
    run = factories.create_test_run(db, space_id=space_id, user_id=user.id, agent=agent, commit=False)
    run.workspace_id = ws.id
    db.flush()

    ops = [{"op": "replace_file", "path": "main.py", "content": "code"}]
    skipped = [{"path": "big.bin", "reason": "binary"}]

    with patch("app.runs.code_patch_collector.collect_worktree_changes", return_value=(ops, skipped)):
        result = collect_and_create_code_patch_proposal(db, run=run, worktree_path=tmp_path)

    assert result.proposal_created is True
    prop = db.query(Proposal).filter(Proposal.created_by_run_id == run.id).first()
    assert prop is not None
    payload = prop.payload_json
    assert payload["skipped"] == skipped
    assert payload["file_count"] == 1
