"""Scheduled automations: cron helper, service wiring, scheduler scan, and the
Option-A credential pre-authorization gate (incl. an end-to-end scheduled model_api run).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.automation.schedule import (
    InvalidScheduleError,
    compute_next_run_at,
    parse_schedule,
)
from app.automation.schemas import AutomationCreate, AutomationUpdate
from app.automation.service import AutomationService
from app.models import (
    AgentVersion,
    Automation,
    AutomationCredentialGrant,
    AutomationRun,
    Run,
)
from tests.support import factories


def _schedule_cfg(cron: str = "0 9 * * *", tz: str = "UTC") -> dict:
    return {"cron": cron, "timezone": tz}


# ===========================================================================
# 1. Cron helper
# ===========================================================================

class TestScheduleHelper:
    def test_parse_valid(self):
        cron, tz = parse_schedule(_schedule_cfg("*/15 * * * *", "Asia/Shanghai"))
        assert cron == "*/15 * * * *"
        assert tz == "Asia/Shanghai"

    def test_missing_cron_rejected(self):
        with pytest.raises(InvalidScheduleError):
            parse_schedule({"timezone": "UTC"})

    def test_invalid_cron_rejected(self):
        with pytest.raises(InvalidScheduleError):
            parse_schedule(_schedule_cfg("not a cron"))

    def test_invalid_timezone_rejected(self):
        with pytest.raises(InvalidScheduleError):
            parse_schedule(_schedule_cfg("0 9 * * *", "Mars/Phobos"))

    def test_next_run_is_future_utc(self):
        after = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
        nxt = compute_next_run_at(_schedule_cfg("0 9 * * *", "UTC"), after=after)
        assert nxt == datetime(2026, 6, 3, 9, 0, tzinfo=UTC)
        assert nxt.tzinfo is not None


# ===========================================================================
# 2. Service: schedule create / grant / archive
# ===========================================================================

class TestScheduleAutomationService:
    def _create_schedule(self, db, test_agent, cron="0 9 * * *"):
        return AutomationService(db).create(
            space_id=test_agent.space_id,
            owner_user_id=test_agent.owner_user_id,
            data=AutomationCreate(
                name="sched", agent_id=test_agent.id,
                trigger_type="schedule", config_json=_schedule_cfg(cron),
            ),
        )

    def test_create_schedule_sets_next_run_and_grant(self, db, test_agent):
        auto = self._create_schedule(db, test_agent)
        assert auto.trigger_type == "schedule"
        assert auto.next_run_at is not None and auto.next_run_at > datetime.now(UTC)
        grant = (
            db.query(AutomationCredentialGrant)
            .filter(AutomationCredentialGrant.automation_id == auto.id)
            .one()
        )
        assert grant.status == "active"
        assert grant.granted_by_user_id == test_agent.owner_user_id

    def test_create_schedule_invalid_cron_422(self, db, test_agent):
        with pytest.raises(HTTPException) as exc:
            AutomationService(db).create(
                space_id=test_agent.space_id,
                owner_user_id=test_agent.owner_user_id,
                data=AutomationCreate(
                    name="bad", agent_id=test_agent.id,
                    trigger_type="schedule", config_json={"cron": "nope"},
                ),
            )
        assert exc.value.status_code == 422

    def test_manual_automation_has_no_grant_or_schedule(self, db, test_agent):
        auto = AutomationService(db).create(
            space_id=test_agent.space_id,
            owner_user_id=test_agent.owner_user_id,
            data=AutomationCreate(name="manual1", agent_id=test_agent.id),
        )
        assert auto.next_run_at is None
        assert (
            db.query(AutomationCredentialGrant)
            .filter(AutomationCredentialGrant.automation_id == auto.id)
            .count() == 0
        )

    def test_archive_revokes_grant_and_clears_schedule(self, db, test_agent):
        auto = self._create_schedule(db, test_agent)
        AutomationService(db).update(
            automation_id=auto.id,
            space_id=test_agent.space_id,
            actor_user_id=test_agent.owner_user_id,
            data=AutomationUpdate(status="archived"),
        )
        db.expire_all()
        auto2 = db.query(Automation).filter(Automation.id == auto.id).one()
        assert auto2.next_run_at is None
        grant = (
            db.query(AutomationCredentialGrant)
            .filter(AutomationCredentialGrant.automation_id == auto.id)
            .one()
        )
        assert grant.status == "revoked"
        assert grant.revoked_at is not None

    def test_advance_schedule_sets_last_fired_and_next(self, db, test_agent):
        auto = self._create_schedule(db, test_agent)
        before = auto.next_run_at
        AutomationService(db).advance_schedule(auto)
        assert auto.last_fired_at is not None
        assert auto.next_run_at is not None and auto.next_run_at >= before


# ===========================================================================
# 4. Option-A pre-authorization gate
# ===========================================================================

class TestPreauthGate:
    def test_rule_allows_when_preauthorized(self):
        from app.policy.rules import rule_use_credential
        ctx = {
            "action": "runtime.use_credential",
            "space_id": "s1", "resource_space_id": "s1",
            "trigger_origin": "automation",
            "automation_pre_authorized": True,
        }
        d = rule_use_credential(ctx)
        assert d is not None and d.decision.name == "ALLOW"
        assert d.reason_code == "credential_automation_preauthorized"

    def test_rule_requires_approval_without_preauth(self):
        from app.policy.rules import rule_use_credential
        ctx = {
            "action": "runtime.use_credential",
            "space_id": "s1", "resource_space_id": "s1",
            "trigger_origin": "automation",
        }
        d = rule_use_credential(ctx)
        assert d is not None and d.decision.name == "REQUIRE_APPROVAL"

    def test_preauthorized_lookup_true_then_false_after_revoke(self, db, test_agent):
        from app.runs.policy_inputs import automation_credential_preauthorized
        svc = AutomationService(db)
        auto = svc.create(
            space_id=test_agent.space_id,
            owner_user_id=test_agent.owner_user_id,
            data=AutomationCreate(
                name="grant-auto", agent_id=test_agent.id,
                trigger_type="schedule", config_json=_schedule_cfg(),
            ),
        )
        run = factories.create_test_run(
            db, space_id=test_agent.space_id, user_id=test_agent.owner_user_id,
            agent=None, commit=False,
        )
        run.trigger_origin = "automation"
        db.add(AutomationRun(automation_id=auto.id, run_id=run.id, trigger_type="schedule"))
        db.commit()

        assert automation_credential_preauthorized(db, run) is True

        svc.update(
            automation_id=auto.id, space_id=test_agent.space_id,
            actor_user_id=test_agent.owner_user_id,
            data=AutomationUpdate(status="archived"),
        )
        db.commit()
        db.expire_all()
        run2 = db.query(Run).filter(Run.id == run.id).one()
        assert automation_credential_preauthorized(db, run2) is False

    def test_preauthorized_false_for_non_automation_run(self, db, test_agent):
        from app.runs.policy_inputs import automation_credential_preauthorized
        run = factories.create_test_run(
            db, space_id=test_agent.space_id, user_id=test_agent.owner_user_id,
            agent=None, commit=True,
        )
        assert automation_credential_preauthorized(db, run) is False


# ===========================================================================
# 5. End-to-end: scheduled fire → model_api run executes (pre-auth un-blocks the gate)
# ===========================================================================

def _fake_litellm_response(text: str):
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _point_agent_at_model_api(db, agent, provider_id: str) -> None:
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    rp = dict(version.runtime_policy_json or {})
    rp["default_adapter_type"] = "model_api"
    version.runtime_policy_json = rp
    version.model_provider_id = provider_id
    db.commit()


def test_scheduled_model_api_run_executes_end_to_end(db, test_agent, tmp_path, monkeypatch):
    from app.config import settings
    from app.runs.execution import RunExecutionService

    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))

    provider = factories.create_test_model_provider(
        db, space_id=test_agent.space_id, provider_type="anthropic",
        with_api_key=True, default_model="claude-3-5-sonnet-latest", enabled=True, commit=False,
    )
    _point_agent_at_model_api(db, test_agent, provider.id)

    svc = AutomationService(db)
    auto = svc.create(
        space_id=test_agent.space_id, owner_user_id=test_agent.owner_user_id,
        data=AutomationCreate(
            name="daily-summary", agent_id=test_agent.id,
            trigger_type="schedule", config_json=_schedule_cfg(),
        ),
    )

    # Fire the automation directly; scheduler scans are TS-owned.
    result = svc.fire(
        automation_id=auto.id,
        space_id=test_agent.space_id,
        actor_user_id=test_agent.owner_user_id,
        trigger_type="schedule",
    )
    db.commit()
    link = db.query(AutomationRun).filter(AutomationRun.automation_id == auto.id).one()
    assert link.run_id == result.run_id

    # Execute the fired run — the standing grant must let it pass runtime.use_credential.
    with patch("litellm.completion", return_value=_fake_litellm_response("scheduled output")):
        result = RunExecutionService(db).execute_run(link.run_id, space_id=test_agent.space_id)

    assert result.success is True
    db.expire_all()
    run = db.query(Run).filter(Run.id == link.run_id).one()
    assert run.status == "succeeded"
    assert run.output_json["runtime_adapter_type"] == "model_api"
    assert run.output_json["output_text"] == "scheduled output"


def test_manual_credential_automation_blocked_without_grant(db, test_agent):
    """A manual automation whose agent uses a credential adapter is blocked at create:
    without a standing grant, the use_credential gate requires approval (Option A)."""
    provider = factories.create_test_model_provider(
        db, space_id=test_agent.space_id, provider_type="anthropic",
        with_api_key=True, default_model="claude-3-5-sonnet-latest", enabled=True, commit=False,
    )
    _point_agent_at_model_api(db, test_agent, provider.id)

    with pytest.raises(HTTPException) as exc:
        AutomationService(db).create(  # manual → no pre-authorization
            space_id=test_agent.space_id, owner_user_id=test_agent.owner_user_id,
            data=AutomationCreate(name="manual-cred", agent_id=test_agent.id),
        )
    assert exc.value.status_code == 422
    assert "require_approval" in str(exc.value.detail) or "credential_automation_origin" in str(exc.value.detail)
