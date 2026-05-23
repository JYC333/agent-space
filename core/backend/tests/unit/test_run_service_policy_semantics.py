"""Policy semantics invariants for RunService.create_run.

Invariant: RunService.create_run is a run-creation path, not an execution path.
It must not persist PolicyDecisionRecord rows for runtime.execute.
Real enforcement (with PolicyGateway.check_and_record and PolicyDecisionRecord)
happens exclusively in RunExecutionService.

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
    """Verify that create_run uses PolicyEngine, not PolicyGateway.check_and_record."""

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

    def test_gateway_check_and_record_not_called_during_create_run(self, db):
        space_id = "svc-policy-5"
        factories.create_test_space(db, space_id=space_id, commit=True)
        user = factories.create_test_user(db, space_id=space_id, commit=True)
        agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user.id, commit=True)

        gateway_calls: list[str] = []

        from app.policy.gateway import PolicyGateway
        original_check_and_record = PolicyGateway.check_and_record

        def spy_check_and_record(self_gw, req):
            gateway_calls.append(req.action)
            return original_check_and_record(self_gw, req)

        with patch.object(PolicyGateway, "check_and_record", spy_check_and_record):
            RunService(db).create_run(
                agent_id=agent.id,
                data=_make_run_create(),
                space_id=space_id,
                user_id=user.id,
            )

        runtime_gateway_calls = [a for a in gateway_calls if a == "runtime.execute"]
        assert not runtime_gateway_calls, (
            f"create_run must not call PolicyGateway.check_and_record('runtime.execute'). "
            f"Found {len(runtime_gateway_calls)} call(s). "
            "Preflight uses PolicyEngine directly; real enforcement is in RunExecutionService."
        )
