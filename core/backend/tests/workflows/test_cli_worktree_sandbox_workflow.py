"""CLI worktree sandbox hardening — end-to-end workflow tests.

Covers:
1. CLI run (requires_file_access=True) with a git workspace creates a real git
   worktree, not an empty sandbox directory.
2. Mock CLI modifies a file inside the worktree sandbox.
3. Real workspace root is unchanged after the run.
4. A pending code_patch proposal is created capturing the diff.
5. Accepting the proposal applies the change to the real workspace.
6. runs with requires_file_access=True and sandbox_level<=dry_run fail with
   error_code=sandbox_required (guard enforcement).
7. CLI run with no file changes does NOT create a code_patch proposal; the run
   succeeds and no-op reason is visible in run.output_json.
8. code_patch collector failure is captured in run.output_json.materialization_errors.
9. External root without allow_external_root fails with workspace_root_untrusted_external.
10. External root with allow_external_root=True succeeds.
11. Cross-space workspace fails at execution time.
12. claude_code adapter with risk_level!=high fails clearly with
    file_access_adapter_requires_worktree_policy before execution.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models import AgentVersion, Proposal, Run, Task, TaskProposal, TaskRun
from app.runtimes.base import BaseRuntimeAdapter, RuntimeAdapterResult, RuntimeExecutionContext
from tests.support import factories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path, filename: str = "hello.txt", content: str = "original") -> None:
    """Create a git repo with one committed file."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.invalid"],
        check=True, capture_output=True, cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        check=True, capture_output=True, cwd=str(path),
    )
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], check=True, capture_output=True, cwd=str(path))
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True, capture_output=True, cwd=str(path),
    )


class WorktreeWritingAdapter(BaseRuntimeAdapter):
    """Fake CLI adapter that modifies a file inside the worktree sandbox."""

    adapter_type = "claude_code"
    requires_file_access = True
    supports_sandboxed_execution = True

    def __init__(self, write_path: str, write_content: str) -> None:
        self._write_path = write_path
        self._write_content = write_content
        self.executed_sandbox_cwd: str | None = None

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        self.executed_sandbox_cwd = ctx.sandbox_cwd
        if ctx.sandbox_cwd:
            (Path(ctx.sandbox_cwd) / self._write_path).write_text(
                self._write_content, encoding="utf-8"
            )
        return RuntimeAdapterResult(
            success=True,
            stdout="done",
            output_text="",
            exit_code=0,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )


class FileAccessAdapter(BaseRuntimeAdapter):
    """Fake CLI adapter that declares requires_file_access but makes no writes."""

    adapter_type = "claude_code"
    requires_file_access = True
    supports_sandboxed_execution = True

    def execute(self, ctx: RuntimeExecutionContext) -> RuntimeAdapterResult:
        return RuntimeAdapterResult(
            success=True, stdout="ok", output_text="", exit_code=0,
            started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
        )


def _params(space_id: str) -> dict:
    return {"space_id": space_id}


# ---------------------------------------------------------------------------
# Test 1-5: git worktree, workspace isolation, proposal creation, accept
# ---------------------------------------------------------------------------


def test_cli_worktree_run_creates_code_patch_proposal_and_leaves_workspace_unchanged(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    A CLI run against a git workspace:
    - runs in a real git worktree (not an empty sandbox)
    - does NOT touch the real workspace during execution
    - creates a pending code_patch proposal with the worktree diff
    - accepting the proposal writes the change to the real workspace
    """
    from app.config import settings

    # --- Set up directories ---
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "hello.txt", "original content")

    art_root = tmp_path / "artifacts"
    art_root.mkdir()
    sb_root = tmp_path / "sandboxes"
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "sandbox_root", str(sb_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # --- Create workspace pointing at the git repo (external root, explicitly trusted) ---
    ws = factories.create_test_workspace(
        db,
        space_id=a,
        root_path=str(repo),
        name="test-git-ws",
        allow_external_root=True,
        commit=True,
    )

    # --- Create agent with risk_level=high so sandbox_level=worktree ---
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    # --- Create run targeting the workspace ---
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "do some work"
    db.commit()

    # --- Fake adapter: writes "modified content" to hello.txt in the worktree ---
    fake_adapter = WorktreeWritingAdapter(
        write_path="hello.txt",
        write_content="modified content",
    )
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: fake_adapter,
    )

    # --- Execute run ---
    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded", body

    # --- The adapter received a worktree path (not None) ---
    assert fake_adapter.executed_sandbox_cwd is not None
    sandbox_path = Path(fake_adapter.executed_sandbox_cwd)
    # Worktree is cleaned up after execution
    assert not sandbox_path.exists()

    # --- Real workspace is unchanged ---
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "original content"

    # --- A code_patch proposal was created ---
    db.expire_all()
    proposals = (
        db.query(Proposal)
        .filter(
            Proposal.space_id == a,
            Proposal.created_by_run_id == run_row.id,
            Proposal.proposal_type == "code_patch",
        )
        .all()
    )
    assert len(proposals) == 1, f"expected 1 proposal, got {len(proposals)}"
    prop = proposals[0]
    assert prop.status == "pending"
    assert prop.workspace_id == ws.id

    ops = prop.payload_json["patch"]["operations"]
    assert any(
        op["op"] == "replace_file" and op["path"] == "hello.txt" and "modified content" in op["content"]
        for op in ops
    ), f"expected replace_file for hello.txt in ops: {ops}"

    # --- Accept proposal: change lands in real workspace ---
    from app.memory.proposals import ProposalService

    result = ProposalService(db).accept(prop.id, space_id=a, user_id=ua.id)
    assert result is not None, "proposal accept returned None"
    assert result.updated_paths is not None
    assert "hello.txt" in result.updated_paths

    assert (repo / "hello.txt").read_text(encoding="utf-8") == "modified content"


# ---------------------------------------------------------------------------
# Test 6: sandbox_required guard
# ---------------------------------------------------------------------------


def test_cli_adapter_with_file_access_fails_when_sandbox_level_is_none(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    A run whose policy produces required_sandbox_level=none must fail with
    error_code=sandbox_required when the adapter has requires_file_access=True.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # risk_level=low → required_sandbox_level=none
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "low",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.prompt = "work in no-sandbox mode"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed", body
    error_json = body.get("error_json") or {}
    # Task 6: claude_code is caught by the early file-access adapter policy guard,
    # which fires before the generic sandbox_required guard.
    assert error_json.get("error_code") in (
        "file_access_adapter_requires_worktree_policy",
        "sandbox_required",
    ), body


# ---------------------------------------------------------------------------
# Test 7: workspace not a git repo → run fails clearly
# ---------------------------------------------------------------------------


def test_cli_worktree_run_fails_when_workspace_is_not_git_repo(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    When the workspace root_path is not a git repo, the run fails with a clear
    error message rather than silently running in an empty directory.
    """
    from app.config import settings

    non_git_dir = tmp_path / "plain_dir"
    non_git_dir.mkdir()
    (non_git_dir / "file.txt").write_text("some content", encoding="utf-8")

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws = factories.create_test_workspace(
        db,
        space_id=a,
        root_path=str(non_git_dir),
        name="non-git-ws",
        allow_external_root=True,
        commit=True,
    )

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "work in non-git workspace"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed", body
    # Real workspace must be untouched
    assert (non_git_dir / "file.txt").read_text() == "some content"


# ---------------------------------------------------------------------------
# Test 8: No file changes → no code_patch proposal; no-op visible in output_json
# ---------------------------------------------------------------------------


def test_cli_run_with_no_file_changes_creates_no_code_patch_proposal(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    Task 1: A CLI run that completes without touching any files must NOT create a
    code_patch proposal.  The no-op reason must be visible in run.output_json.
    """
    from app.config import settings

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "unchanged.txt", "original")

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws = factories.create_test_workspace(
        db, space_id=a, root_path=str(repo), name="no-change-ws",
        allow_external_root=True, commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "read but do not change"
    db.commit()

    # Adapter that does not write any files
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded", body

    db.expire_all()
    proposals = (
        db.query(Proposal)
        .filter(
            Proposal.space_id == a,
            Proposal.created_by_run_id == run_row.id,
            Proposal.proposal_type == "code_patch",
        )
        .all()
    )
    assert len(proposals) == 0, "No code_patch proposal should be created for a no-op run"

    run_row_reloaded = db.query(Run).filter(Run.id == run_row.id).one()
    out = run_row_reloaded.output_json or {}
    mat_errors = out.get("materialization_errors") or []
    assert any("code_patch_no_op" in e for e in mat_errors), (
        f"Expected code_patch_no_op in materialization_errors, got: {mat_errors}"
    )


# ---------------------------------------------------------------------------
# Test 9: code_patch collector failure → visible in run.output_json
# ---------------------------------------------------------------------------


def test_code_patch_collector_failure_is_visible_in_run_output(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    Task 3: When code_patch collection raises an exception the run still succeeds
    but the error must appear in run.output_json.materialization_errors.
    """
    from app.config import settings

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "main.txt", "base")

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws = factories.create_test_workspace(
        db, space_id=a, root_path=str(repo), name="collector-fail-ws",
        allow_external_root=True, commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "trigger collector failure"
    db.commit()

    def _raise_collector(*args, **kwargs):
        raise RuntimeError("injected collector failure")

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )
    monkeypatch.setattr(
        "app.runs.execution.collect_and_create_code_patch_proposal",
        _raise_collector,
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded", body

    db.expire_all()
    run_row_reloaded = db.query(Run).filter(Run.id == run_row.id).one()
    out = run_row_reloaded.output_json or {}
    mat_errors = out.get("materialization_errors") or []
    assert any("code_patch_collection_error" in e for e in mat_errors), (
        f"Expected code_patch_collection_error in materialization_errors, got: {mat_errors}"
    )


# ---------------------------------------------------------------------------
# Test 10: External root without allow_external_root fails (unchanged)
# ---------------------------------------------------------------------------


def test_external_workspace_root_without_trust_fails(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    Task 4: A workspace whose root_path resolves outside settings.workspace_root
    must fail with workspace_root_untrusted_external unless allow_external_root=True.
    """
    from app.config import settings

    external_repo = tmp_path / "external-repo"
    external_repo.mkdir()
    _init_git_repo(external_repo)

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(ws_root))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # allow_external_root=False (default) → should fail
    ws = factories.create_test_workspace(
        db, space_id=a, root_path=str(external_repo), name="untrusted-ext-ws",
        allow_external_root=False, commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "work"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed", body
    error_json = body.get("error_json") or {}
    assert error_json.get("error_code") == "workspace_root_untrusted_external", body


# ---------------------------------------------------------------------------
# Test 11: claude_code adapter with low risk fails early with clear error
# ---------------------------------------------------------------------------


def test_claude_code_with_low_risk_fails_with_policy_error(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    Task 6: A run using claude_code adapter with risk_level!=high must fail before
    execution starts with error_code=file_access_adapter_requires_worktree_policy.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    # risk_level=medium → required_sandbox_level=dry_run, not worktree
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "medium",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.prompt = "work"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed", body
    error_json = body.get("error_json") or {}
    assert error_json.get("error_code") == "file_access_adapter_requires_worktree_policy", body


# ---------------------------------------------------------------------------
# Test 12: Cross-space workspace_id → workspace_not_found, no space_id leak
# ---------------------------------------------------------------------------


def test_cross_space_workspace_returns_not_found_without_leaking_space_id(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    A run in space A that references a workspace belonging to space B must fail
    with workspace_not_found and must not expose space B's id in the error message.
    """
    from app.config import settings

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]

    # Workspace belongs to space B
    ws_b = factories.create_test_workspace(
        db, space_id=b, root_path=str(repo), name="space-b-ws",
        allow_external_root=True, commit=True,
    )

    # Agent and run in space A
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws_b.id  # points at space B's workspace
    run_row.prompt = "attempt cross-space"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed", body
    error_json = body.get("error_json") or {}
    assert error_json.get("error_code") == "workspace_not_found", body
    # Error message must not expose the other space's id
    error_text = str(error_json.get("error_text") or "")
    assert b not in error_text, f"Other space_id leaked in error: {error_text}"


# ---------------------------------------------------------------------------
# Test 13: git diff/status failure → materialization_error, not silent no-op
# ---------------------------------------------------------------------------


def test_git_command_failure_in_collector_becomes_materialization_error(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    If git diff or git status fails inside code_patch_collector (e.g. corrupt
    worktree), the run still succeeds but the git error must appear in
    run.output_json.materialization_errors — it must not silently produce a no-op.
    """
    from app.config import settings
    from app.runs.code_patch_collector import GitCommandError

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    (tmp_path / "artifacts").mkdir()

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws = factories.create_test_workspace(
        db, space_id=a, root_path=str(repo), name="git-fail-ws",
        allow_external_root=True, commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "work"
    db.commit()

    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: FileAccessAdapter(),
    )

    # Make _git raise GitCommandError to simulate a corrupt worktree / git failure.
    def _fail_git(args, cwd, timeout=30):
        raise GitCommandError("git diff HEAD --name-status failed (exit 128): not a git repository")

    monkeypatch.setattr("app.runs.code_patch_collector._git", _fail_git)

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded", body  # run itself still succeeds

    db.expire_all()
    run_row_reloaded = db.query(Run).filter(Run.id == run_row.id).one()
    out = run_row_reloaded.output_json or {}
    mat_errors = out.get("materialization_errors") or []
    assert any("code_patch_collection_error" in e for e in mat_errors), (
        f"Expected code_patch_collection_error in materialization_errors, got: {mat_errors}"
    )


# ---------------------------------------------------------------------------
# Test 14: Task-linked run → code_patch proposal → TaskProposal link
# ---------------------------------------------------------------------------


def test_task_linked_run_code_patch_produces_task_proposal_link(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    A run linked to a Task via TaskRun that produces a code_patch proposal must
    also create a TaskProposal row linking the proposal back to the task.
    """
    from ulid import ULID
    from app.config import settings

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo, "main.py", "# original")

    art_root = tmp_path / "artifacts"
    art_root.mkdir()
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    ws = factories.create_test_workspace(
        db, space_id=a, root_path=str(repo), name="task-link-ws",
        allow_external_root=True, commit=True,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).one()
    version.runtime_policy_json = {
        "risk_level": "high",
        "default_adapter_type": "claude_code",
        "allowed_adapter_types": ["claude_code"],
    }
    db.commit()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()
    run_row.workspace_id = ws.id
    run_row.prompt = "modify main.py"
    db.commit()

    # Create a Task and link the run to it via TaskRun
    task = Task(id=str(ULID()), space_id=a, title="Implement feature X")
    db.add(task)
    db.flush()
    tr = TaskRun(id=str(ULID()), space_id=a, task_id=task.id, run_id=run_row.id)
    db.add(tr)
    db.commit()

    fake_adapter = WorktreeWritingAdapter(write_path="main.py", write_content="# modified")
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _t: fake_adapter,
    )

    resp = cross_space_pair["client_a"].post(
        f"/api/v1/runs/{run_row.id}/execute",
        params=_params(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded", body

    db.expire_all()

    proposals = (
        db.query(Proposal)
        .filter(
            Proposal.space_id == a,
            Proposal.created_by_run_id == run_row.id,
            Proposal.proposal_type == "code_patch",
        )
        .all()
    )
    assert len(proposals) == 1, f"Expected 1 code_patch proposal, got {len(proposals)}"
    prop = proposals[0]
    assert prop.status == "pending"

    # TaskProposal link must exist with role='code_patch'
    tp = (
        db.query(TaskProposal)
        .filter(TaskProposal.task_id == task.id, TaskProposal.proposal_id == prop.id)
        .first()
    )
    assert tp is not None, "TaskProposal link was not created for the task-linked run"
    assert tp.role == "code_patch"
    assert tp.space_id == a

    # Real workspace unchanged
    assert (repo / "main.py").read_text(encoding="utf-8") == "# original"


def test_task_proposal_link_not_duplicated(
    api_client, db, cross_space_pair, tmp_path, monkeypatch,
):
    """
    Calling link_run_outputs_to_tasks a second time for the same proposal does not
    produce a duplicate TaskProposal row.
    """
    from ulid import ULID
    from app.models import Proposal
    from app.runs.task_output_linkage import link_run_outputs_to_tasks

    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]

    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    run_row = db.query(Run).filter(Run.id == run.id).one()

    task = Task(id=str(ULID()), space_id=a, title="Idempotence check")
    db.add(task)
    db.flush()

    tr = TaskRun(id=str(ULID()), space_id=a, task_id=task.id, run_id=run_row.id)
    db.add(tr)

    proposal = Proposal(
        id=str(ULID()),
        space_id=a,
        created_by_run_id=run_row.id,
        proposal_type="code_patch",
        status="pending",
        title="Idempotence proposal",
        payload_json={"patch": {"operations": []}},
    )
    db.add(proposal)
    db.commit()

    link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
    db.commit()
    link_run_outputs_to_tasks(db, run=run_row, artifact=None, proposal=proposal, proposal_role="code_patch")
    db.commit()

    count = (
        db.query(TaskProposal)
        .filter(TaskProposal.task_id == task.id, TaskProposal.proposal_id == proposal.id)
        .count()
    )
    assert count == 1, f"Expected exactly 1 TaskProposal, got {count}"
