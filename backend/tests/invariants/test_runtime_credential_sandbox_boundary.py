"""Invariant: runtime credential and sandbox path boundary enforcement.

Tests in this file assert:
- Current RunExecutionService uses app.runtimes, not app.agents, for execution.
- Run sandbox/workdir stays inside configured sandbox root.
- Path escape attempts from the worktree manager are rejected.
- workspace/sandbox_manager.SandboxManager is NOT the canonical path for new execution.
- raw secrets are not persisted to RunStep error or metadata after execution.
- adapter_config passed to the runtime adapter does not contain raw api_key fields.
"""
from __future__ import annotations

import inspect

import pytest

from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig


# ---------------------------------------------------------------------------
# Canonical path: RunExecutionService uses app.runtimes, not app.agents
# ---------------------------------------------------------------------------

class TestRunExecutionUsesCanonicalRuntimeRegistry:
    def test_execution_service_imports_from_runtimes_not_agents(self):
        """RunExecutionService must import instantiate_runtime_adapter from app.runtimes."""
        import app.runs.execution as svc_module
        source = inspect.getsource(svc_module)
        # Must import from canonical registry
        assert "from ..runtimes.registry import instantiate_runtime_adapter" in source

    def test_execution_service_has_no_agents_imports(self):
        """RunExecutionService must not import anything from app.agents (M4 boundary)."""
        import app.runs.execution as svc_module
        source = inspect.getsource(svc_module)
        # No import of any kind from ..agents or app.agents
        assert "from ..agents" not in source
        assert "import agents" not in source

    def test_runtime_registry_exposes_echo_adapter(self):
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("echo")

    def test_local_cli_runtime_types_registered_via_spec(self):
        """claude_code and codex_cli must execute through RuntimeAdapterSpec."""
        from app.runtimes.registry import is_adapter_type_implemented
        assert is_adapter_type_implemented("claude_code"), (
            "claude_code must be registered through RuntimeAdapterSpec and GenericCliRuntimeAdapter"
        )
        assert is_adapter_type_implemented("codex_cli"), (
            "codex_cli must be registered through RuntimeAdapterSpec and GenericCliRuntimeAdapter"
        )


# ---------------------------------------------------------------------------
# Sandbox/path boundary — worktree manager path escape rejection
# ---------------------------------------------------------------------------

class TestWorktreeManagerPathEscape:
    def test_workdir_stays_inside_sandbox_root(self, tmp_path):
        from app.config import settings
        import os

        sandbox_root = tmp_path / "sandboxes"
        sandbox_root.mkdir()

        from unittest.mock import patch
        with patch.object(settings, "sandbox_root", str(sandbox_root)):
            from app.runs.worktree_manager import isolated_run_workdir
            with isolated_run_workdir("space1", "run1") as workdir:
                assert workdir is not None
                from pathlib import Path
                wp = Path(workdir).resolve()
                sr = sandbox_root.resolve()
                # workdir must be under sandbox_root
                wp.relative_to(sr)  # raises ValueError if not under root

    def test_worktree_root_itself_is_under_sandbox_root(self, tmp_path):
        from app.config import settings
        from pathlib import Path
        from unittest.mock import patch

        sandbox_root = tmp_path / "sandboxes"
        sandbox_root.mkdir()

        with patch.object(settings, "sandbox_root", str(sandbox_root)):
            from app.runs.worktree_manager import isolated_run_workdir
            with isolated_run_workdir("myspace", "myrun") as workdir:
                wp = Path(workdir).resolve()
                sr = sandbox_root.resolve()
                wp.relative_to(sr)

    def test_ensure_under_root_rejects_path_outside_root(self):
        """_ensure_under_root rejects any path not under its declared root."""
        from pathlib import Path
        from app.runs.worktree_manager import _ensure_under_root

        root = Path("/safe/root")
        # A path that is simply outside the root — not the same prefix
        with pytest.raises(ValueError, match="escapes"):
            _ensure_under_root(Path("/other/directory/attack"), root)

    def test_ensure_under_root_rejects_sibling_path(self):
        from pathlib import Path
        from app.runs.worktree_manager import _ensure_under_root

        root = Path("/safe/root")
        # /safe/root-sibling is NOT under /safe/root
        with pytest.raises(ValueError, match="escapes"):
            _ensure_under_root(Path("/safe/root-sibling/file"), root)

    def test_ensure_under_root_accepts_valid_path(self):
        from pathlib import Path
        from app.runs.worktree_manager import _ensure_under_root

        root = Path("/safe/root")
        # Should not raise
        _ensure_under_root(Path("/safe/root/subdir/file"), root)


# ---------------------------------------------------------------------------
# Canonical sandbox manager — execution_workspace uses runs.worktree_manager
# ---------------------------------------------------------------------------

class TestCanonicalSandboxManagerSource:
    def test_execution_workspace_uses_runs_worktree_manager(self):
        """execution_workspace in app.runs.sandbox_manager must delegate to isolated_run_workdir."""
        import app.runs.sandbox_manager as sm
        source = inspect.getsource(sm)
        assert "isolated_run_workdir" in source
        assert "worktree_manager" in source

    def test_workspace_sandbox_manager_is_not_imported_by_execution(self):
        """app.runs.execution must not import workspace.sandbox_manager."""
        import app.runs.execution as svc
        source = inspect.getsource(svc)
        assert "workspace.sandbox_manager" not in source
        assert "SandboxManager" not in source


# ---------------------------------------------------------------------------
# Credential boundary — adapter_config must not contain raw secrets post-sanitize
# ---------------------------------------------------------------------------

class TestAdapterConfigSanitization:
    def test_sanitize_removes_api_key_before_context(self, db, cross_space_pair, tmp_path, monkeypatch):
        """execution service strips api_key from adapter_config before building RuntimeExecutionContext."""
        from app.config import settings

        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
        (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

        captured_ctx = {}

        class CapturingFakeAdapter(ConfigurableFakeRuntimeAdapter):
            adapter_type = "capturing_fake"

            def execute(self, ctx):
                captured_ctx["adapter_config"] = dict(ctx.adapter_config)
                captured_ctx["resolved_credentials"] = dict(ctx.resolved_credentials)
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: CapturingFakeAdapter(FakeRuntimeConfig(output_text="")),
        )
        db.commit()

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)

        from app.models import AgentVersion
        from sqlalchemy.orm.attributes import flag_modified
        ver = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
        # Inject raw api_key into runtime_config_json (the merged config source)
        ver.runtime_config_json = {"api_key": "sk-raw-should-be-stripped", "model": "test"}
        flag_modified(ver, "runtime_config_json")
        db.commit()

        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        cross_space_pair["client_a"].post(
            f"/api/v1/runs/{run.id}/execute",
            params={"space_id": a},
        )

        # api_key must be stripped from adapter_config
        assert "api_key" not in captured_ctx.get("adapter_config", {})


# ---------------------------------------------------------------------------
# Secret redaction — secrets must not persist into RunStep / Run rows
# ---------------------------------------------------------------------------

class TestSecretRedactionAtPersistence:
    def test_raw_secret_in_adapter_error_is_redacted_in_run_row(
        self, db, cross_space_pair, tmp_path, monkeypatch
    ):
        """A secret in adapter error_text must not appear in Run.error_message."""
        from app.config import settings
        from app.models import Run

        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
        (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

        raw_secret = "sk-leak-test-secret-xyz9876"
        cfg = FakeRuntimeConfig(
            success=False,
            error_code="adapter_error_with_secret",
            error_text=f"API error: key {raw_secret} was rejected by provider",
            output_text="",
        )
        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
        )
        db.commit()

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        rid = run.id

        cross_space_pair["client_a"].post(
            f"/api/v1/runs/{rid}/execute", params={"space_id": a}
        )
        db.expire_all()
        run_row = db.query(Run).filter(Run.id == rid).one()

        # Raw secret must not appear in persistent fields
        assert raw_secret not in (run_row.error_message or "")
        out_str = str(run_row.output_json or "")
        assert raw_secret not in out_str
        err_str = str(run_row.error_json or "")
        assert raw_secret not in err_str

    def test_raw_secret_in_step_error_is_redacted(
        self, db, cross_space_pair, tmp_path, monkeypatch
    ):
        """A secret surfaced via adapter failure must not appear in RunStep.error_message."""
        from app.config import settings
        from app.models import Run, RunStep

        monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
        monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
        monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
        (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)

        raw_secret = "sk-step-leak-test-secret"
        cfg = FakeRuntimeConfig(
            success=False,
            error_code="step_secret_test",
            error_text=f"Auth failed: {raw_secret}",
            output_text="",
        )
        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: ConfigurableFakeRuntimeAdapter(cfg),
        )
        db.commit()

        a = cross_space_pair["space_a_id"]
        ua = cross_space_pair["user_a"]
        agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
        run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
        rid = run.id

        cross_space_pair["client_a"].post(
            f"/api/v1/runs/{rid}/execute", params={"space_id": a}
        )
        db.expire_all()
        steps = db.query(RunStep).filter(RunStep.run_id == rid).all()
        for step in steps:
            assert raw_secret not in (step.error_message or ""), (
                f"Raw secret found in RunStep.error_message for step_type={step.step_type}"
            )
            meta_str = str(step.metadata_json or "")
            assert raw_secret not in meta_str
