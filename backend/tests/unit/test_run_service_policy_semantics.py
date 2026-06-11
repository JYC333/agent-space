"""Policy semantics invariants for RunService.create_run.

Invariant: RunService.create_run is a run-creation path, not an execution path.
It must not persist PolicyDecisionRecord rows for runtime.execute.
Real enforcement through PolicyGateway and PolicyDecisionRecord happens in
RunExecutionService.

These tests verify:
  1. create_run succeeds for a valid active agent (no PolicyDecisionRecord created).
  2. Disabled (archived) agent is rejected with HTTP 409 and no PolicyDecisionRecord.
  3. Forbidden adapter type is rejected with HTTP 403 and no PolicyDecisionRecord.
  4. PolicyEngine is used directly (no PolicyDecisionRecord from preflight checks).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from unittest.mock import patch

from tests.support import factories
from app.models import AgentVersion, PolicyDecisionRecord
from app.runs.run_service import RunService
from app.schemas import RunCreate


def _count_pdr(db, space_id: str) -> int:
    return db.query(PolicyDecisionRecord).filter(
        PolicyDecisionRecord.space_id == space_id
    ).count()


def _make_run_create(**kwargs) -> RunCreate:
    defaults = dict(
        prompt="test prompt",
        mode="live",
        run_type="agent",
        trigger_origin="manual",
    )
    defaults.update(kwargs)
    return RunCreate(**defaults)


class TestCreateRunDoesNotPersistPolicyDecisionRecord:
    """create_run must not write PolicyDecisionRecord rows (non-mutating preflight only)."""

    def test_valid_agent_creates_run_with_no_pdr(self, db):
        space_id = "svc-policy-1"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        pdr_before = _count_pdr(db, space_id)

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(),
            space_id=space_id,
            user_id=user.id,
        )

        pdr_after = _count_pdr(db, space_id)
        assert run is not None
        assert pdr_after == pdr_before, (
            f"create_run must not persist PolicyDecisionRecord; "
            f"{pdr_after - pdr_before} new record(s) found"
        )

    def test_disabled_agent_raises_409_with_no_pdr(self, db):
        space_id = "svc-policy-2"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Archive the agent — runtime.execute engine rules deny archived agents.
        agent.status = "archived"
        db.commit()

        pdr_before = _count_pdr(db, space_id)

        with pytest.raises(HTTPException) as exc_info:
            RunService(db).create_run(
                agent_id=agent.id,
                data=_make_run_create(),
                space_id=space_id,
                user_id=user.id,
            )

        assert exc_info.value.status_code == 409
        pdr_after = _count_pdr(db, space_id)
        assert pdr_after == pdr_before, (
            f"create_run rejection must not write PolicyDecisionRecord; "
            f"{pdr_after - pdr_before} new record(s) found"
        )

    def test_forbidden_adapter_type_raises_403_with_no_pdr(self, db):
        space_id = "svc-policy-3"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        # Restrict adapter types to only "echo"; request "claude_code" (not in list).
        version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).first()
        version.runtime_policy_json = {
            **(version.runtime_policy_json or {}),
            "allowed_adapter_types": ["echo"],
        }
        db.commit()

        pdr_before = _count_pdr(db, space_id)

        with pytest.raises(HTTPException) as exc_info:
            RunService(db).create_run(
                agent_id=agent.id,
                data=_make_run_create(adapter_type="claude_code"),
                space_id=space_id,
                user_id=user.id,
            )

        assert exc_info.value.status_code == 403
        pdr_after = _count_pdr(db, space_id)
        assert pdr_after == pdr_before, (
            f"adapter rejection must not write PolicyDecisionRecord; "
            f"{pdr_after - pdr_before} new record(s) found"
        )


class TestCreateRunUsesEngineDirectly:
    """Verify that create_run uses PolicyEngine simulation, not durable gateway enforcement."""

    def test_validate_target_agent_calls_engine_not_gateway(self, db):
        space_id = "svc-policy-4"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        engine_calls: list[dict] = []

        from app.policy.engine import PolicyEngine
        original_check = PolicyEngine.check

        def spy_check(self_engine, ctx):
            engine_calls.append(dict(ctx))
            return original_check(self_engine, ctx)

        with patch.object(PolicyEngine, "check", spy_check):
            RunService(db).create_run(
                agent_id=agent.id,
                data=_make_run_create(),
                space_id=space_id,
                user_id=user.id,
            )

        # At least one runtime.execute engine call must have happened.
        runtime_calls = [c for c in engine_calls if c.get("action") == "runtime.execute"]
        assert runtime_calls, (
            "create_run must call PolicyEngine.check() for runtime.execute "
            "(non-mutating preflight)"
        )

    def test_create_run_preflight_does_not_write_runtime_execute_pdr(self, db):
        space_id = "svc-policy-5"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        pdr_before = _count_pdr(db, space_id)
        RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(),
            space_id=space_id,
            user_id=user.id,
        )
        pdr_after = _count_pdr(db, space_id)

        assert pdr_after == pdr_before, (
            "create_run preflight must not persist runtime.execute policy records. "
            "Preflight uses PolicyEngine simulation; real enforcement is in RunExecutionService."
        )


class TestCreateRunRuntimeProviderDefaults:
    """Runtime requirements decide whether RunService attaches ModelProvider defaults."""

    def _make_agent_with_default_provider(self, db, space_id: str):
        factories.create_test_space(db, space_id=space_id)
        user = factories.create_test_user(db, space_id=space_id)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id)
        provider = factories.create_test_model_provider(
            db,
            space_id=space_id,
            is_default=True,
            with_api_key=True,
            commit=False,
        )
        db.flush()
        return user, agent, provider

    def test_space_default_provider_does_not_attach_to_echo_run(self, db):
        space_id = "svc-runtime-provider-echo"
        user, agent, provider = self._make_agent_with_default_provider(db, space_id)

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(adapter_type="echo"),
            space_id=space_id,
            user_id=user.id,
        )

        assert provider.id is not None
        assert run.model_provider_id is None
        assert run.model_override_json is None

    def test_explicit_provider_request_is_ignored_for_echo_run(self, db):
        space_id = "svc-runtime-provider-echo-explicit"
        user, agent, provider = self._make_agent_with_default_provider(db, space_id)

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(adapter_type="echo", model_provider_id=provider.id),
            space_id=space_id,
            user_id=user.id,
        )

        assert run.model_provider_id is None
        assert run.model_override_json is None

    def test_run_adapter_request_overrides_version_config_for_model_defaults(self, db):
        space_id = "svc-provider-request-priority"
        user, agent, provider = self._make_agent_with_default_provider(db, space_id)
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        allowed = set((version.runtime_policy_json or {}).get("allowed_adapter_types") or [])
        allowed.add("model_api")
        version.runtime_config_json = {"adapter_type": "echo"}
        version.runtime_policy_json = {
            **(version.runtime_policy_json or {}),
            "allowed_adapter_types": sorted(allowed),
        }
        db.flush()

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(adapter_type="model_api"),
            space_id=space_id,
            user_id=user.id,
        )

        assert provider.id is not None
        assert run.adapter_type == "model_api"
        assert run.model_provider_id == provider.id
        assert run.model_override_json is not None
        assert run.model_override_json["source"] == "space_default"

    def test_unknown_runtime_requirements_raise_stable_create_error(self, db):
        space_id = "svc-runtime-provider-unknown"
        user, agent, _provider = self._make_agent_with_default_provider(db, space_id)
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        allowed = set((version.runtime_policy_json or {}).get("allowed_adapter_types") or [])
        allowed.add("unknown_requirements_runtime")
        version.runtime_policy_json = {
            **(version.runtime_policy_json or {}),
            "allowed_adapter_types": sorted(allowed),
        }
        db.flush()

        with pytest.raises(HTTPException) as exc:
            RunService(db).create_run(
                agent_id=agent.id,
                data=_make_run_create(adapter_type="unknown_requirements_runtime"),
                space_id=space_id,
                user_id=user.id,
            )

        assert exc.value.status_code == 400
        assert "runtime_requirements_missing" in str(exc.value.detail)

    @pytest.mark.parametrize("adapter_type", ["claude_code", "codex_cli"])
    def test_space_default_provider_does_not_attach_to_cli_runs(self, db, adapter_type):
        space_id = f"svc-runtime-provider-{adapter_type}"
        user, agent, provider = self._make_agent_with_default_provider(db, space_id)
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        version.runtime_config_json = {"adapter_type": adapter_type}
        db.flush()

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(),
            space_id=space_id,
            user_id=user.id,
        )

        assert provider.id is not None
        assert run.model_provider_id is None
        assert run.model_override_json is None

    def test_cli_runtime_ignores_valid_space_default_provider(self, db):
        space_id = "svc-runtime-provider-api-default"
        user, agent, provider = self._make_agent_with_default_provider(db, space_id)
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        version.runtime_config_json = {"adapter_type": "claude_code"}
        db.flush()

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(),
            space_id=space_id,
            user_id=user.id,
        )

        assert provider.id is not None
        assert run.model_provider_id is None
        assert run.model_override_json is None

    def test_cli_runtime_ignores_runtime_scoped_provider_default(self, db):
        space_id = "svc-runtime-provider-scoped-default"
        user, agent, global_default = self._make_agent_with_default_provider(db, space_id)
        runtime_default = factories.create_test_model_provider(
            db,
            space_id=space_id,
            name="api-runtime-default",
            with_api_key=True,
            default_model="gpt-runtime-default",
            commit=False,
        )
        runtime_default.config_json = {"runtime_default_for": "claude_code"}
        version = db.query(AgentVersion).filter(
            AgentVersion.id == agent.current_version_id
        ).first()
        version.runtime_config_json = {"adapter_type": "claude_code"}
        db.flush()

        run = RunService(db).create_run(
            agent_id=agent.id,
            data=_make_run_create(),
            space_id=space_id,
            user_id=user.id,
        )

        assert runtime_default.id is not None
        assert global_default.id is not None
        assert run.model_provider_id is None
        assert run.model_override_json is None
