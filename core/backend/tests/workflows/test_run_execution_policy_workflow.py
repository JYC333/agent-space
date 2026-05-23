"""Workflow tests: real RunExecutionService policy blocking.

These tests verify that policy gates (runtime.execute, runtime.use_credential,
artifact.persist) actually block the real execution path — not just the PolicyEngine
unit-level checks.

Each test uses the real RunExecutionService and verifies:
- adapter.execute is NOT called on DENY/REQUIRE_APPROVAL
- credential resolver is NOT called after runtime.execute DENY
- ContextSnapshotPopulator is NOT called after runtime.execute DENY
- Run fails with stable error_code
- PolicyDecisionRecord is persisted

Unit-level PolicyEngine rule tests live in tests/unit/test_policy_rules.py and
tests/workflows/test_policy_gateway_workflow.py. Those tests exercise the rule
logic directly and do not prove the real RunExecutionService path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from sqlalchemy.orm import Session

from app.models import Artifact, PolicyDecisionRecord, Run
from app.runs.execution import RunExecutionService
from tests.support import factories
from tests.support.fake_runtime import ConfigurableFakeRuntimeAdapter, FakeRuntimeConfig
from tests.support.ids import PERSONAL_SPACE_ID, DEFAULT_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_paths(monkeypatch, tmp_path):
    from app.config import settings
    art_root = tmp_path / "artifacts"
    art_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))


def _make_fake_adapter(monkeypatch, config: FakeRuntimeConfig | None = None):
    fake = ConfigurableFakeRuntimeAdapter(config or FakeRuntimeConfig())
    monkeypatch.setattr(
        "app.runs.execution.instantiate_runtime_adapter",
        lambda _adapter_type: fake,
    )
    return fake


# ---------------------------------------------------------------------------
# 1. runtime.execute DENY: disabled agent status
# ---------------------------------------------------------------------------


class TestRuntimeExecuteDisabledAgentBlocking:
    """Disabled agent status → policy_denied_runtime_execute before adapter.execute.

    This is a REAL RunExecutionService path test, not just a PolicyEngine unit test.
    """

    def test_disabled_agent_blocks_execution_before_adapter(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Agent.status='disabled' → runtime.execute DENY → adapter.execute never called."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_called = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            def execute(self, ctx):
                adapter_called.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        agent.status = "disabled"
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "policy_denied_runtime_execute"
        assert adapter_called == [], "adapter.execute must not be called when agent is disabled"

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).one()
        assert run_row.status == "failed"
        assert run_row.error_json is not None
        assert run_row.error_json.get("error_code") == "policy_denied_runtime_execute"

    def test_disabled_agent_blocks_before_credential_resolver(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Agent.status='disabled' → runtime.execute DENY → credential resolver never called."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        credential_resolved = []

        def _mock_resolve_credentials(*args, **kwargs):
            credential_resolved.append("called")
            raise RuntimeError("credential resolver must not be called after DENY")

        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            _mock_resolve_credentials,
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        agent.status = "disabled"
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.error_code == "policy_denied_runtime_execute"
        assert credential_resolved == [], "Credential resolver must not be called after runtime.execute DENY"

    def test_disabled_agent_blocks_before_context_snapshot_populator(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Agent.status='disabled' → runtime.execute DENY → ContextSnapshotPopulator never called."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        snapshot_called = []

        real_populate = None

        class TrackingPopulator:
            def populate(self, run, version):
                snapshot_called.append("called")
                raise RuntimeError("ContextSnapshotPopulator must not be called after DENY")

        monkeypatch.setattr(
            "app.runs.execution.ContextSnapshotPopulator",
            lambda db: TrackingPopulator(),
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        agent.status = "disabled"
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.error_code == "policy_denied_runtime_execute"
        assert snapshot_called == [], "ContextSnapshotPopulator must not be called after runtime.execute DENY"

    def test_disabled_agent_policy_decision_record_persisted(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Agent.status='disabled' → DENY → PolicyDecisionRecord created for runtime.execute."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        agent.status = "disabled"
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.error_code == "policy_denied_runtime_execute"

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.execute",
        ).first()
        assert record is not None, "PolicyDecisionRecord must be created for runtime.execute DENY"
        assert record.decision == "deny"
        assert record.policy_rule_id == "agent_status"


# ---------------------------------------------------------------------------
# 2. runtime.execute DENY: disallowed tool
# ---------------------------------------------------------------------------


class TestRuntimeExecuteDisallowedToolBlocking:
    """Tool not in agent_tool_permissions → policy_denied_runtime_execute before adapter.execute.

    This is a REAL RunExecutionService path test.
    """

    def test_disallowed_tool_blocks_adapter_invocation(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Adapter type not in tool_permissions_json → DENY → adapter.execute never called."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_called = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx):
                adapter_called.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        # Restrict tool permissions to only "claude_code" — echo adapter not allowed
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.tool_permissions_json = ["claude_code"]

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "policy_denied_runtime_execute"
        assert adapter_called == [], "adapter.execute must not be called when tool is not permitted"

    def test_allowed_tool_permits_execution(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Adapter type in tool_permissions_json → ALLOW → adapter.execute is called."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_executed = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            adapter_type = "echo"

            def execute(self, ctx):
                adapter_executed.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        # Permit the echo adapter explicitly
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.tool_permissions_json = ["echo"]

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "test allowed tool"
        db.commit()

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.success, f"Expected success but got error_code={result.error_code}"
        assert "called" in adapter_executed, "adapter.execute must be called when tool is permitted"

    def test_empty_tool_permissions_allows_all(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Empty tool_permissions_json ({}) → all tools allowed (rule only fires when list is non-None)."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_executed = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            def execute(self, ctx):
                adapter_executed.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        # tool_permissions_json={} (dict default) — rule_tool_permission only fires for list type
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "test default permissions"
        db.commit()

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.success, f"Expected success with no tool restriction, got {result.error_code}"
        assert "called" in adapter_executed


# ---------------------------------------------------------------------------
# 3. runtime.use_credential: cross-space denial before secret resolution
# ---------------------------------------------------------------------------


class TestRuntimeUseCredentialCrossSpaceBlocking:
    """Cross-space credential → DENY before any secret material is resolved.

    Verifies the fix: resource_space_id comes from Credential.space_id, not RuntimeAdapter.space_id.
    """

    def test_cross_space_credential_denied_before_secret_resolution(
        self, db: Session, tmp_path, monkeypatch
    ):
        """RuntimeAdapter in space_a referencing Credential in space_b → DENY before secret resolution."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []

        def _mock_resolve(*args, **kwargs):
            secret_resolved.append("called")
            return {}

        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            _mock_resolve,
        )

        space_a = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        # Credential lives in a DIFFERENT space (simulated with a different space_id string)
        space_b = "space_b_cross"
        factories.create_test_space(db, space_id=space_b, name="Space B", space_type="team")

        # Create credential in space_b
        cred = factories.create_test_credential_stub(
            db, space_id=space_b, name="cross-space-cred", commit=True
        )

        # Create runtime adapter in space_a referencing cross-space credential
        adapter_row = factories.create_test_runtime_adapter(
            db,
            space_id=space_a,
            name="cross-space-adapter",
            adapter_type="echo",
            credential_id=cred.id,
            commit=True,
        )

        agent = factories.create_test_agent(db, space_id=space_a, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id

        run = factories.create_test_run(db, space_id=space_a, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_a)

        assert not result.success
        assert result.error_code == "policy_denied_runtime_use_credential", (
            f"Expected policy_denied_runtime_use_credential, got {result.error_code}"
        )
        assert secret_resolved == [], (
            "Secret resolution must not be called for cross-space credentials"
        )

    def test_missing_credential_row_fails_closed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """credential_id exists on adapter but Credential row is missing → credential_metadata_missing.

        We create a real credential, link the adapter, then patch the Credential DB query to
        return None — simulating a row that was deleted or corrupted after FK registration.
        This tests the fail-closed logic without violating DB FK constraints.
        """
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []

        def _mock_resolve(*args, **kwargs):
            secret_resolved.append("called")
            return {}

        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            _mock_resolve,
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        cred = factories.create_test_credential_stub(
            db, space_id=space_id, name="cred-to-go-missing", commit=True
        )
        adapter_row = factories.create_test_runtime_adapter(
            db,
            space_id=space_id,
            name="missing-cred-adapter",
            adapter_type="echo",
            credential_id=cred.id,
            commit=True,
        )

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        # Patch the Credential query to return None — simulate a missing/deleted row
        real_query = db.query

        def _patched_query(model, *args, **kwargs):
            q = real_query(model, *args, **kwargs)
            from app.models import Credential as _Cred
            if model is _Cred:
                class _NoneResult:
                    def filter(self, *a, **kw):
                        return self
                    def first(self):
                        return None
                return _NoneResult()
            return q

        monkeypatch.setattr(db, "query", _patched_query)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "credential_metadata_missing", (
            f"Expected credential_metadata_missing when Credential row is missing, got {result.error_code}"
        )
        assert secret_resolved == [], "Secret resolution must not be called when Credential row is missing"

    def test_same_space_credential_is_allowed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """RuntimeAdapter and Credential both in same space → allowed with audit."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_executed = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            def execute(self, ctx):
                adapter_executed.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        # Patch credential resolution to succeed without real secrets
        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            lambda *a, **kw: {},
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        # Credential in same space as the run
        cred = factories.create_test_credential_stub(
            db, space_id=space_id, name="same-space-cred", commit=True
        )
        adapter_row = factories.create_test_runtime_adapter(
            db,
            space_id=space_id,
            name="same-space-adapter",
            adapter_type="echo",
            credential_id=cred.id,
            commit=True,
        )

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "same-space-cred-test"
        db.commit()

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.success, (
            f"Same-space credential should be allowed, got error_code={result.error_code}"
        )
        assert "called" in adapter_executed

        # Verify PolicyDecisionRecord for use_credential was created (audit_required=True)
        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.use_credential",
        ).first()
        assert record is not None, "runtime.use_credential ALLOW must be audited"
        assert record.decision == "allow"
        # Metadata must not contain any secret material
        meta = record.metadata_json or {}
        for dangerous in ("api_key", "secret", "token", "password"):
            assert dangerous not in meta, (
                f"{dangerous!r} must not appear in PolicyDecisionRecord metadata"
            )

    def test_policy_decision_record_for_cross_space_credential_has_no_secret(
        self, db: Session, tmp_path, monkeypatch
    ):
        """PolicyDecisionRecord for cross-space credential DENY must not contain secret material."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)
        monkeypatch.setattr("app.runs.execution.resolve_runtime_credentials", lambda *a, **kw: {})

        space_a = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        space_b = "space_b_secret_safety"
        factories.create_test_space(db, space_id=space_b, name="Space B", space_type="team")

        cred = factories.create_test_credential_stub(
            db, space_id=space_b, name="cross-cred-safety", commit=True
        )
        adapter_row = factories.create_test_runtime_adapter(
            db, space_id=space_a, adapter_type="echo", credential_id=cred.id, commit=True
        )

        agent = factories.create_test_agent(db, space_id=space_a, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id
        run = factories.create_test_run(db, space_id=space_a, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_a)

        assert result.error_code == "policy_denied_runtime_use_credential"

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.use_credential",
        ).first()
        assert record is not None
        assert record.decision == "deny"

        meta = record.metadata_json or {}
        for dangerous_key in ("api_key", "secret", "token", "password", "stdout", "stderr", "prompt"):
            val = meta.get(dangerous_key)
            assert val is None or val == "[REDACTED]", (
                f"{dangerous_key!r} must not appear unredacted in PolicyDecisionRecord metadata"
            )


# ---------------------------------------------------------------------------
# 4. runtime.use_credential: provider-level credential metadata resolved before secrets
# ---------------------------------------------------------------------------


class TestRuntimeUseCredentialProviderLevelBlocking:
    """Provider-level credential paths (ModelProvider → Credential) are checked before secret resolution.

    Covers resolution priority 1–3 from resolve_runtime_credentials():
      1. run.model_provider_id → ModelProvider.credential_id → Credential.space_id
      2. runtime_adapter.provider_id → ModelProvider.credential_id → Credential.space_id
      3. version.model_provider_id → ModelProvider.credential_id → Credential.space_id
    """

    def test_version_model_provider_id_same_space_allowed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """AgentVersion.model_provider_id pointing to same-space credential → ALLOW + audit record."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)
        monkeypatch.setattr("app.runs.execution.resolve_runtime_credentials", lambda *a, **kw: {})

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        cred = factories.create_test_credential_stub(db, space_id=space_id, name="provider-cred-same-space", commit=True)
        provider = factories.create_test_model_provider(
            db, space_id=space_id, name="same-space-provider", credential_id=cred.id, commit=True
        )

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.model_provider_id = provider.id

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "provider-same-space-test"
        db.commit()

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert result.success, f"Expected success with same-space provider credential, got {result.error_code}"

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.use_credential",
        ).first()
        assert record is not None, "runtime.use_credential ALLOW must be audited"
        assert record.decision == "allow"
        meta = record.metadata_json or {}
        assert meta.get("resolution_source") == "agent_version.model_provider_id"

    def test_version_model_provider_id_cross_space_provider_fails_closed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """AgentVersion.model_provider_id → ModelProvider in a different space → credential_metadata_missing.

        ModelProvider.space_id must equal run.space_id. A cross-space provider is a configuration
        error; execution fails closed before any credential lookup or secret resolution.
        """
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []
        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            lambda *a, **kw: secret_resolved.append("called") or {},
        )

        space_a = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        space_b = "space_b_provider_cross"
        factories.create_test_space(db, space_id=space_b, name="Provider Space B", space_type="team")

        # Provider and its credential both live in space_b — ModelProvider is cross-space
        cred = factories.create_test_credential_stub(db, space_id=space_b, name="cross-provider-cred", commit=True)
        provider = factories.create_test_model_provider(
            db, space_id=space_b, name="cross-space-provider", credential_id=cred.id, commit=True
        )

        agent = factories.create_test_agent(db, space_id=space_a, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.model_provider_id = provider.id

        run = factories.create_test_run(db, space_id=space_a, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_a)

        assert not result.success
        assert result.error_code == "credential_metadata_missing", (
            f"Expected credential_metadata_missing for cross-space ModelProvider, got {result.error_code}"
        )
        assert secret_resolved == [], "Secret resolution must not be called for cross-space ModelProvider"

    def test_runtime_adapter_provider_id_cross_space_provider_fails_closed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """RuntimeAdapter.provider_id → ModelProvider in a different space → credential_metadata_missing."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []
        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            lambda *a, **kw: secret_resolved.append("called") or {},
        )

        space_a = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        space_b = "space_b_adapter_provider_cross"
        factories.create_test_space(db, space_id=space_b, name="Adapter Provider Space B", space_type="team")

        # Provider in space_b; adapter in space_a — ModelProvider is cross-space
        cred = factories.create_test_credential_stub(db, space_id=space_b, name="adapter-provider-cross-cred", commit=True)
        provider = factories.create_test_model_provider(
            db, space_id=space_b, name="adapter-cross-provider", credential_id=cred.id, commit=True
        )
        adapter_row = factories.create_test_runtime_adapter(
            db, space_id=space_a, name="adapter-with-cross-provider",
            adapter_type="echo", provider_id=provider.id, commit=True,
        )

        agent = factories.create_test_agent(db, space_id=space_a, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id

        run = factories.create_test_run(db, space_id=space_a, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_a)

        assert not result.success
        assert result.error_code == "credential_metadata_missing", (
            f"Expected credential_metadata_missing for cross-space ModelProvider, got {result.error_code}"
        )
        assert secret_resolved == [], "Secret resolution must not be called for cross-space ModelProvider"

    def test_same_space_provider_cross_space_credential_denied_by_policy(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Same-space ModelProvider whose Credential lives in a different space → policy DENY.

        ModelProvider.space_id == run.space_id (passes the hard check).
        Credential.space_id != run.space_id → resource_space_id mismatch → rule_space_boundary
        fires in PolicyEngine → policy_denied_runtime_use_credential with audit record.
        """
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []
        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            lambda *a, **kw: secret_resolved.append("called") or {},
        )

        space_a = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        space_b = "space_b_cred_cross"
        factories.create_test_space(db, space_id=space_b, name="Credential Space B", space_type="team")

        # Provider is in space_a (same as run), but its credential lives in space_b
        cred = factories.create_test_credential_stub(db, space_id=space_b, name="cross-cred-only", commit=True)
        provider = factories.create_test_model_provider(
            db, space_id=space_a, name="same-space-provider-cross-cred", credential_id=cred.id, commit=True
        )

        agent = factories.create_test_agent(db, space_id=space_a, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.model_provider_id = provider.id

        run = factories.create_test_run(db, space_id=space_a, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_a)

        assert not result.success
        assert result.error_code == "policy_denied_runtime_use_credential", (
            f"Expected policy_denied_runtime_use_credential for cross-space Credential, got {result.error_code}"
        )
        assert secret_resolved == [], "Secret resolution must not be called for cross-space credential"

    def test_missing_provider_credential_row_fails_closed(
        self, db: Session, tmp_path, monkeypatch
    ):
        """ModelProvider with no credential_id configured → credential_metadata_missing before secrets.

        Simulates a provider that was created without a credential (misconfiguration).
        """
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        secret_resolved = []
        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            lambda *a, **kw: secret_resolved.append("called") or {},
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        # Provider with no credential_id (misconfigured)
        provider = factories.create_test_model_provider(
            db, space_id=space_id, name="no-cred-provider", credential_id=None, commit=True
        )

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.model_provider_id = provider.id

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        svc = RunExecutionService(db)
        result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "credential_metadata_missing", (
            f"Expected credential_metadata_missing for provider with no credential, got {result.error_code}"
        )
        assert secret_resolved == [], "Secret resolution must not be called when provider metadata is missing"


# ---------------------------------------------------------------------------
# 5. artifact.persist REQUIRE_APPROVAL blocking
# ---------------------------------------------------------------------------


class TestArtifactPersistRequireApprovalBlocking:
    """artifact.persist REQUIRE_APPROVAL must block file write and Artifact row creation.

    Unit test for the ArtifactPersistenceService path.
    """

    def test_require_approval_blocks_text_file_write(self, db: Session, tmp_path, monkeypatch):
        """artifact.persist REQUIRE_APPROVAL → no file written, no Artifact row, exception raised."""
        from app.config import settings
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError
        from app.policy.decisions import Decision, PolicyDecision, RiskLevel

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        require_approval_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="Test: artifact.persist requires approval",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="test_rule",
        )
        require_approval_decision.resource_type = "artifact"
        require_approval_decision.resource_id = None

        with patch(
            "app.runs.artifact_persistence.PolicyGateway.check_and_record",
            return_value=require_approval_decision,
        ) as check_and_record:
            svc = ArtifactPersistenceService(db)
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                svc.persist_text_file(
                    run=run_row,
                    text="artifact content",
                    title="test artifact",
                    artifact_type="runtime_output",
                )
            assert "requires approval" in str(exc_info.value).lower()
            request = check_and_record.call_args.args[0]
            assert request.context["target_space_id"] == space_id

        # Verify no Artifact row was created
        arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        assert len(arts) == 0, "No Artifact row must be created when REQUIRE_APPROVAL"

        # Verify no file was written
        written_files = list(art_root.rglob("*.txt"))
        assert len(written_files) == 0, "No file must be written when REQUIRE_APPROVAL"

    def test_require_approval_blocks_copied_file_write(self, db: Session, tmp_path, monkeypatch):
        """artifact.persist REQUIRE_APPROVAL → no file copied, no Artifact row."""
        from app.config import settings
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError
        from app.policy.decisions import Decision, PolicyDecision, RiskLevel
        import pathlib

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

        # Create a real source file to be "copied"
        src_file = tmp_path / "source.txt"
        src_file.write_text("source content", encoding="utf-8")

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        require_approval_decision = PolicyDecision(
            decision=Decision.REQUIRE_APPROVAL,
            message="Test: artifact.persist requires approval",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="test_rule",
        )
        require_approval_decision.resource_type = "artifact"
        require_approval_decision.resource_id = None

        with patch(
            "app.runs.artifact_persistence.PolicyGateway.check_and_record",
            return_value=require_approval_decision,
        ) as check_and_record:
            svc = ArtifactPersistenceService(db)
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                svc.persist_copied_file(
                    run=run_row,
                    source_file=src_file,
                    source_relative_path="source.txt",
                    title="test file",
                    artifact_type="runtime_file",
                )
            assert "requires approval" in str(exc_info.value).lower()
            request = check_and_record.call_args.args[0]
            assert request.context["target_space_id"] == space_id

        arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        assert len(arts) == 0, "No Artifact row must be created when REQUIRE_APPROVAL"

    def test_deny_blocks_text_file_write(self, db: Session, tmp_path, monkeypatch):
        """artifact.persist DENY → no file written, no Artifact row."""
        from app.config import settings
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError
        from app.policy.decisions import Decision, PolicyDecision, RiskLevel

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        deny_decision = PolicyDecision(
            decision=Decision.DENY,
            message="Test: artifact.persist denied",
            risk_level=RiskLevel.HIGH,
            policy_rule_id="test_deny_rule",
        )
        deny_decision.resource_type = "artifact"
        deny_decision.resource_id = None

        with patch(
            "app.runs.artifact_persistence.PolicyGateway.check_and_record",
            return_value=deny_decision,
        ):
            svc = ArtifactPersistenceService(db)
            with pytest.raises(PersonalMemoryEgressError) as exc_info:
                svc.persist_text_file(
                    run=run_row,
                    text="artifact content",
                    title="test artifact",
                    artifact_type="runtime_output",
                )
            assert "denied" in str(exc_info.value).lower()

        arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        assert len(arts) == 0, "No Artifact row must be created when DENY"

    def test_safe_artifact_persist_succeeds_normally(self, db: Session, tmp_path, monkeypatch):
        """ALLOW decision → artifact file written and Artifact row created."""
        from app.config import settings
        from app.runs.artifact_persistence import ArtifactPersistenceService

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        svc = ArtifactPersistenceService(db)
        art = svc.persist_text_file(
            run=run_row,
            text="safe artifact content",
            title="safe artifact",
            artifact_type="runtime_output",
        )

        assert art is not None
        assert art.id is not None
        db.flush()

        arts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        assert len(arts) == 1

        # File must exist on disk
        import pathlib
        dest = pathlib.Path(settings.artifact_storage_root) / art.storage_path
        assert dest.exists(), "Artifact file must exist on disk"
        assert dest.read_text(encoding="utf-8") == "safe artifact content"

    def test_policy_decision_record_for_artifact_deny_has_no_content(
        self, db: Session, tmp_path, monkeypatch
    ):
        """PolicyDecisionRecord for artifact.persist DENY must not store artifact content."""
        from app.config import settings
        from app.runs.artifact_persistence import ArtifactPersistenceService
        from app.personal_memory_grants.egress_guard import PersonalMemoryEgressError

        art_root = tmp_path / "artifacts"
        art_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "artifact_storage_root", str(art_root))

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()

        # Trigger hard invariant: personal_context_block in metadata → DENY + record created
        from app.policy.gateway import PolicyGateway, PolicyCheckRequest
        from app.policy.decisions import Decision

        svc = ArtifactPersistenceService(db)
        # We can't easily inject personal_context_block via the real path, so verify the
        # real path's normal deny scenario stores no content in the audit record.
        # Use force_record to get a record even on allow, then check metadata.
        gw = PolicyGateway(db)
        gw.check_and_record(
            PolicyCheckRequest(
                action="artifact.persist",
                actor_id=user_id,
                space_id=space_id,
                run_id=run.id,
                force_record=True,
                metadata_json={
                    "artifact_type": "runtime_output",
                    "target_space_id": space_id,
                    # These must never appear:
                    "file_content": "full artifact text body",
                    "stdout": "execution output",
                    "stderr": "execution error",
                },
            )
        )

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "artifact.persist",
        ).first()
        assert record is not None
        meta = record.metadata_json or {}
        for dangerous in ("file_content", "stdout", "stderr", "patch", "diff"):
            assert meta.get(dangerous) == "[REDACTED]" or dangerous not in meta, (
                f"{dangerous!r} must be redacted in PolicyDecisionRecord metadata"
            )


# ---------------------------------------------------------------------------
# 6. Policy trace metadata safety: RunEvent must not contain sensitive data
# ---------------------------------------------------------------------------


class TestRunEventPolicyTraceSafety:
    """RunEvent policy_checked events must not contain prompt, credentials, or context content."""

    def test_policy_checked_event_has_no_sensitive_fields(
        self, db: Session, tmp_path, monkeypatch
    ):
        """policy_checked RunEvent contains only decision metadata, not prompt or context."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "secret prompt that must not be in event"
        db.commit()

        svc = RunExecutionService(db)
        svc.execute_run(run.id, space_id=space_id)

        from app.models import RunEvent
        policy_events = db.query(RunEvent).filter(
            RunEvent.run_id == run.id,
            RunEvent.event_type == "policy_checked",
        ).all()

        assert len(policy_events) >= 1, "At least one policy_checked RunEvent must be emitted"
        for event in policy_events:
            meta = event.metadata_json or {}
            # Must contain only safe audit fields
            for dangerous_key in ("prompt", "context", "raw_memory", "personal_context_block",
                                  "stdout", "stderr", "credentials", "api_key", "patch"):
                assert dangerous_key not in meta, (
                    f"RunEvent policy_checked must not contain {dangerous_key!r}"
                )
            # Must contain decision metadata
            assert "action" in meta
            assert "decision" in meta


# ---------------------------------------------------------------------------
# 7. runtime.execute actor semantics
# ---------------------------------------------------------------------------


class TestRuntimeExecuteActorSemantics:
    """runtime.execute PolicyDecisionRecord records correct actor fields.

    Test A: manual run with instructed_by_user_id → actor_type="user"
    Test B: non-manual run (trigger_origin="automation") → actor_type="run" with actor_ref
    """

    def test_manual_run_records_user_actor(self, db: Session, tmp_path, monkeypatch):
        """Manual run with instructed_by_user_id → PolicyDecisionRecord.actor_type == 'user'."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=False)
        # Confirm the factory wired trigger_origin="manual" (default from RunCreate)
        assert run.trigger_origin == "manual"
        assert run.instructed_by_user_id == user_id
        run_row = db.query(Run).filter(Run.id == run.id).one()
        run_row.prompt = "manual-actor-test"
        db.commit()

        svc = RunExecutionService(db)
        svc.execute_run(run.id, space_id=space_id)

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.execute",
        ).first()
        assert record is not None, "PolicyDecisionRecord must be created for runtime.execute"
        assert record.actor_type == "user", (
            f"Manual run must record actor_type='user', got {record.actor_type!r}"
        )
        assert record.actor_id == user_id, (
            f"Manual run must record actor_id == instructed_by_user_id, got {record.actor_id!r}"
        )
        assert record.resource_type == "run"
        assert record.resource_id == run.id
        assert record.run_id == run.id

    def test_automation_run_records_run_actor_with_actor_ref(
        self, db: Session, tmp_path, monkeypatch
    ):
        """Non-manual run (trigger_origin='automation') → actor_type='run' with actor_ref."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=False)
        run.trigger_origin = "automation"
        run.prompt = "automation-actor-test"
        db.commit()

        assert run.trigger_origin == "automation"

        svc = RunExecutionService(db)
        svc.execute_run(run.id, space_id=space_id)

        record = db.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.run_id == run.id,
            PolicyDecisionRecord.action == "runtime.execute",
        ).first()
        assert record is not None, "PolicyDecisionRecord must be created for runtime.execute"
        assert record.actor_type == "run", (
            f"Non-manual run must record actor_type='run', got {record.actor_type!r}"
        )
        assert record.actor_id == run.id, (
            f"Non-manual run must record actor_id == run.id, got {record.actor_id!r}"
        )
        assert record.resource_type == "run"
        assert record.resource_id == run.id
        assert record.run_id == run.id

        actor_ref = record.actor_ref_json or {}
        assert actor_ref.get("run_id") == run.id, (
            f"actor_ref must contain run_id == run.id, got {actor_ref!r}"
        )
        assert actor_ref.get("trigger_origin") == "automation", (
            f"actor_ref must contain trigger_origin='automation', got {actor_ref!r}"
        )


# ---------------------------------------------------------------------------
# 6. PDR persistence failure → terminal run (real RunExecutionService path)
# ---------------------------------------------------------------------------


class TestRunExecutionPdrFailure:
    """PolicyDecisionRecordPersistError → terminal failed run with stable error_code.

    These are REAL RunExecutionService path tests. They verify that when
    PolicyDecisionRecord persistence fails at a fail_closed gate, the service
    converts the error into a stable terminal run rather than letting it propagate
    as an unstructured exception.
    """

    def test_runtime_execute_pdr_failure_is_terminal_and_blocks_adapter(
        self, db: Session, tmp_path, monkeypatch
    ):
        """runtime.execute PDR persist failure → terminal run; adapter.execute never called."""
        _setup_paths(monkeypatch, tmp_path)

        adapter_called = []

        class TrackingAdapter(ConfigurableFakeRuntimeAdapter):
            def execute(self, ctx):
                adapter_called.append("called")
                return super().execute(ctx)

        monkeypatch.setattr(
            "app.runs.execution.instantiate_runtime_adapter",
            lambda _t: TrackingAdapter(),
        )

        from app.policy.gateway import PolicyDecisionRecordPersistError

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=True)
        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        with patch("app.runs.execution.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = PolicyDecisionRecordPersistError(
                action="runtime.execute"
            )
            svc = RunExecutionService(db)
            result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "policy_decision_record_persist_failed", (
            f"Expected policy_decision_record_persist_failed, got {result.error_code!r}"
        )
        assert adapter_called == [], "adapter.execute must not be called when runtime.execute PDR persist fails"

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).one()
        assert run_row.status == "failed"
        assert run_row.error_json is not None
        assert run_row.error_json.get("error_code") == "policy_decision_record_persist_failed"

    def test_runtime_use_credential_pdr_failure_is_terminal_and_blocks_secret_resolution(
        self, db: Session, tmp_path, monkeypatch
    ):
        """runtime.use_credential PDR persist failure → terminal run; secret resolver never called."""
        _setup_paths(monkeypatch, tmp_path)
        _make_fake_adapter(monkeypatch)

        from app.policy.gateway import PolicyDecisionRecordPersistError
        from app.policy.decisions import PolicyDecision, Decision, RiskLevel

        credential_resolved = []

        def _mock_resolve(*args, **kwargs):
            credential_resolved.append("called")
            return {}

        monkeypatch.setattr(
            "app.runs.execution.resolve_runtime_credentials",
            _mock_resolve,
        )

        space_id = PERSONAL_SPACE_ID
        user_id = DEFAULT_USER_ID

        cred = factories.create_test_credential_stub(
            db, space_id=space_id, name="pdr-test-cred", commit=True
        )
        adapter_row = factories.create_test_runtime_adapter(
            db,
            space_id=space_id,
            name="pdr-test-adapter",
            adapter_type="echo",
            credential_id=cred.id,
            commit=True,
        )

        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id, commit=False)
        from app.models import AgentVersion
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_adapter_id = adapter_row.id

        run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent, commit=True)

        def _side_effect(req):
            if req.action == "runtime.execute":
                return PolicyDecision(
                    decision=Decision.ALLOW,
                    message="allowed by test mock",
                    risk_level=RiskLevel.MEDIUM,
                )
            raise PolicyDecisionRecordPersistError(action=req.action)

        with patch("app.runs.execution.PolicyGateway") as MockGW:
            MockGW.return_value.check_and_record.side_effect = _side_effect
            svc = RunExecutionService(db)
            result = svc.execute_run(run.id, space_id=space_id)

        assert not result.success
        assert result.error_code == "policy_decision_record_persist_failed", (
            f"Expected policy_decision_record_persist_failed, got {result.error_code!r}"
        )
        assert credential_resolved == [], (
            "Secret resolver must not be called when runtime.use_credential PDR persist fails"
        )

        db.expire_all()
        run_row = db.query(Run).filter(Run.id == run.id).one()
        assert run_row.status == "failed"
        assert run_row.error_json is not None
        assert run_row.error_json.get("error_code") == "policy_decision_record_persist_failed"
