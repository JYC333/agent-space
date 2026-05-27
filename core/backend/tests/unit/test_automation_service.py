"""Unit tests for AutomationService.

Covers all 14 spec requirements for Part B:
  1.  unknown/reserved actions deny before wiring
  2.  automation.create is checked and recorded
  3.  automation.fire is checked and recorded
  4.  failed preflight prevents Automation creation
  5.  failed preflight prevents fire
  6.  fire creates Run(trigger_origin="automation")
  7.  fire creates AutomationRun link
  8.  no MemoryEntry / Policy / Proposal is written by AutomationService
  9.  automation actions are WIRED_DIRECT
  10. insufficient role is denied for automation.create/fire

Note: AutomationService now calls PolicyGateway.enforce() which raises PolicyGateBlocked
(not HTTPException) on policy denial. ALLOW PolicyDecisionRecords are written to an
independent session by DurablePolicyAuditWriter; DENY records are only written by the
global HTTP exception handler (not in unit tests). Use fresh sessions to check records.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.automation.schemas import AutomationCreate, AutomationFireRequest, AutomationUpdate
from app.automation.service import AutomationService
from app.automation.policy_preflight import AutomationPolicyPreflightService
from app.models import (
    Automation,
    AutomationRun,
    Credential,
    MemoryEntry,
    Policy,
    PolicyDecisionRecord,
    Run,
    RuntimeToolBinding,
    Workspace,
)
from app.policy.actions import (
    PolicyActionLifecycle,
    get_action_definition,
    list_action_definitions,
)
from app.policy.decisions import Decision, PolicyDecision, RiskLevel
from app.policy.exceptions import PolicyAuditPersistError, PolicyGateBlocked
from app.policy.gateway import PolicyGateway, PolicyCheckRequest
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count(db, model) -> int:
    return db.query(model).count()


def _decision_records(db, action: str) -> list[PolicyDecisionRecord]:
    return (
        db.query(PolicyDecisionRecord)
        .filter(PolicyDecisionRecord.action == action)
        .all()
    )


def _fresh_records(action: str, decision_value: str | None = None) -> list[PolicyDecisionRecord]:
    """Query PolicyDecisionRecord from a fresh independent session (verifies durability)."""
    from app.db import SessionLocal
    fresh = SessionLocal()
    try:
        q = fresh.query(PolicyDecisionRecord).filter(PolicyDecisionRecord.action == action)
        if decision_value is not None:
            q = q.filter(PolicyDecisionRecord.decision == decision_value)
        return q.all()
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# 1. Action lifecycle: still-reserved actions deny; automation actions are wired
# ---------------------------------------------------------------------------

class TestActionLifecycle:
    """automation.create/update/fire are now WIRED_DIRECT; still-reserved actions deny."""

    def test_automation_create_is_wired_direct(self):
        defn = get_action_definition("automation.create")
        assert defn is not None
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT

    def test_automation_update_is_wired_direct(self):
        defn = get_action_definition("automation.update")
        assert defn is not None
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT

    def test_automation_fire_is_wired_direct(self):
        defn = get_action_definition("automation.fire")
        assert defn is not None
        assert defn.lifecycle_status == PolicyActionLifecycle.WIRED_DIRECT

    def test_reserved_action_still_denies(self, db):
        """deployment.propose is still RESERVED and must fail closed."""
        gw = PolicyGateway(db)
        with pytest.raises(PolicyGateBlocked) as exc_info:
            gw.enforce(PolicyCheckRequest(
                action="deployment.propose",
                actor_type="user",
                actor_id=DEFAULT_USER_ID,
                space_id=PERSONAL_SPACE_ID,
            ))
        d = exc_info.value.decision
        assert d.denied
        assert d.reason_code == "policy_action_not_implemented"

    def test_unknown_action_denies(self, db):
        gw = PolicyGateway(db)
        with pytest.raises(PolicyGateBlocked) as exc_info:
            gw.enforce(PolicyCheckRequest(
                action="totally.unknown.action",
                actor_type="user",
                actor_id=DEFAULT_USER_ID,
                space_id=PERSONAL_SPACE_ID,
            ))
        d = exc_info.value.decision
        assert d.denied
        assert d.reason_code == "unknown_policy_action"


# ---------------------------------------------------------------------------
# 2. automation.create is checked and recorded
# ---------------------------------------------------------------------------

class TestAutomationCreate:

    def test_create_records_policy_decision(self, db, test_agent):
        # ALLOW records are written to an independent session via DurablePolicyAuditWriter.
        before_ids = {r.id for r in _fresh_records("automation.create", "allow")}

        svc = AutomationService(db)
        svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="my-auto", agent_id=test_agent.id),
        )
        db.flush()

        after = _fresh_records("automation.create", "allow")
        new_records = [r for r in after if r.id not in before_ids]
        assert len(new_records) >= 1, "ALLOW record must be visible from fresh session"
        r = new_records[-1]
        assert r.decision == "allow"
        assert r.actor_id == DEFAULT_USER_ID

    def test_create_persists_automation_row(self, db, test_agent):
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="persist-test", agent_id=test_agent.id),
        )
        db.flush()

        row = db.query(Automation).filter(Automation.id == auto.id).first()
        assert row is not None
        assert row.name == "persist-test"
        assert row.trigger_type == "manual"
        assert row.status == "active"

    def test_create_stores_preflight_snapshot(self, db, test_agent):
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="snap-test", agent_id=test_agent.id),
        )
        db.flush()
        assert auto.preflight_snapshot_json is not None
        assert "executable" in auto.preflight_snapshot_json

    def test_create_insufficient_role_denied(self, db, test_agent):
        """A guest cannot create automations — enforce() raises PolicyGateBlocked."""
        from app.models import SpaceMembership

        guest_id = "guest_user_for_auto_test"
        from app.models import User
        guest = User(
            id=guest_id,
            display_name="Guest",
            status="active",
        )
        db.add(guest)
        db.add(SpaceMembership(
            id=f"sm_guest_{guest_id}",
            space_id=PERSONAL_SPACE_ID,
            user_id=guest_id,
            role="guest",
            status="active",
        ))
        db.flush()

        svc = AutomationService(db)
        with pytest.raises(PolicyGateBlocked) as exc:
            svc.create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=guest_id,
                data=AutomationCreate(name="denied-auto", agent_id=test_agent.id),
            )
        pgb = exc.value
        assert pgb.http_status_code == 403
        assert pgb.decision.denied
        assert pgb.action == "automation.create"

    def test_create_checks_policy_before_preflight_diagnostics(self, db, test_agent):
        """Policy denial must happen before PreflightService can reveal diagnostics."""
        from unittest.mock import patch

        denied = PolicyGateBlocked(
            decision=PolicyDecision(
                decision=Decision.DENY,
                message="denied",
                risk_level=RiskLevel.HIGH,
                reason_code="automation_insufficient_role",
                policy_rule_id="automation_insufficient_role",
                audit_code="automation_denied",
            ),
            action="automation.create",
            actor_type="user",
            actor_id="blocked",
            actor_ref=None,
            space_id=PERSONAL_SPACE_ID,
            resource_type="automation",
            resource_id=None,
            run_id=None,
            proposal_id=None,
            metadata_json=None,
        )

        with patch("app.automation.service.PolicyGateway.enforce", side_effect=denied):
            with patch("app.automation.service.PreflightService.check") as check:
                with pytest.raises(PolicyGateBlocked):
                    AutomationService(db).create(
                        space_id=PERSONAL_SPACE_ID,
                        owner_user_id=DEFAULT_USER_ID,
                        data=AutomationCreate(name="blocked-before-preflight", agent_id=test_agent.id),
                    )

        check.assert_not_called()


# ---------------------------------------------------------------------------
# 4 & 5. Failed preflight prevents creation and fire
# ---------------------------------------------------------------------------

class TestPreflightGate:

    def test_failed_preflight_prevents_creation(self, db):
        """An agent that doesn't exist in the space fails preflight → create raises 422."""
        svc = AutomationService(db)
        with pytest.raises(HTTPException) as exc:
            svc.create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=DEFAULT_USER_ID,
                data=AutomationCreate(name="bad-agent-auto", agent_id="nonexistent-agent-id"),
            )
        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert detail["error"] == "preflight_failed"
        assert len(detail["errors"]) > 0

    def test_failed_preflight_prevents_fire(self, db, test_agent):
        """Create automation OK, then break the agent so preflight fails on fire."""
        from app.models import Agent

        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="to-be-broken", agent_id=test_agent.id),
        )

        # Deactivate the agent so preflight fails on fire.
        # Commit to release write lock from svc.create()'s db.flush()
        # so fire's enforce() DurablePolicyAuditWriter.write() can commit.
        agent_row = db.query(Agent).filter(Agent.id == test_agent.id).first()
        agent_row.status = "inactive"
        db.commit()

        with pytest.raises(HTTPException) as exc:
            svc.fire(
                automation_id=auto.id,
                space_id=PERSONAL_SPACE_ID,
                actor_user_id=DEFAULT_USER_ID,
            )
        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert detail["error"] == "preflight_failed"


# ---------------------------------------------------------------------------
# 3, 6, 7. automation.fire: policy record, Run with trigger_origin, AutomationRun link
# ---------------------------------------------------------------------------

class TestAutomationFire:

    def _create_active_auto(self, db, test_agent) -> Automation:
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="fire-test", agent_id=test_agent.id),
        )
        # Commit to release the write lock acquired by svc.create()'s db.flush().
        # DurablePolicyAuditWriter in the subsequent svc.fire() call needs to commit
        # independently and SQLite only allows one writer at a time.
        db.commit()
        return auto

    def test_fire_records_policy_decision(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)
        before_ids = {r.id for r in _fresh_records("automation.fire", "allow")}

        AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()

        after = _fresh_records("automation.fire", "allow")
        new_records = [r for r in after if r.id not in before_ids]
        assert len(new_records) >= 1, "ALLOW fire record must be visible from fresh session"
        r = new_records[-1]
        assert r.decision == "allow"
        assert r.resource_id == auto.id

    def test_fire_creates_run_with_automation_trigger_origin(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)

        result = AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()

        run = db.query(Run).filter(Run.id == result.run_id).first()
        assert run is not None
        assert run.trigger_origin == "automation"

    def test_fire_creates_automation_run_link(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)

        result = AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()

        auto_run = db.query(AutomationRun).filter(
            AutomationRun.id == result.automation_run_id
        ).first()
        assert auto_run is not None
        assert auto_run.automation_id == auto.id
        assert auto_run.run_id == result.run_id
        assert auto_run.triggered_by_user_id == DEFAULT_USER_ID
        assert auto_run.trigger_type == "manual"

    def test_fire_creates_exactly_one_automation_run_link(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)

        result = AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()

        links = db.query(AutomationRun).filter(
            AutomationRun.automation_id == auto.id,
            AutomationRun.run_id == result.run_id,
        ).all()
        assert len(links) == 1

    def test_fire_result_has_correct_trigger_origin(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)
        result = AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        assert result.trigger_origin == "automation"
        assert result.preflight_executable is True

    def test_fire_run_is_queued_not_executed(self, db, test_agent):
        """fire() must queue the run, not execute it (status=queued)."""
        auto = self._create_active_auto(db, test_agent)
        result = AutomationService(db).fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()

        run = db.query(Run).filter(Run.id == result.run_id).first()
        assert run is not None
        assert run.status == "queued"

    def test_fire_inactive_automation_raises_409(self, db, test_agent):
        auto = self._create_active_auto(db, test_agent)
        auto.status = "paused"
        db.commit()  # commit status change; no write lock for fire's enforce() DurableWriter

        with pytest.raises(HTTPException) as exc:
            AutomationService(db).fire(
                automation_id=auto.id,
                space_id=PERSONAL_SPACE_ID,
                actor_user_id=DEFAULT_USER_ID,
            )
        assert exc.value.status_code == 409

    def test_fire_atomic_no_orphan_run_on_automation_run_failure(self, db, test_agent):
        """If AutomationRun creation fails after Run is flushed, no orphan Run is committed."""
        from unittest.mock import patch

        auto = self._create_active_auto(db, test_agent)
        before = _count(db, Run)

        # Simulate failure during AutomationRun instantiation (after Run is flushed).
        with patch("app.automation.service.AutomationRun", side_effect=RuntimeError("injected")):
            with pytest.raises(RuntimeError, match="injected"):
                AutomationService(db).fire(
                    automation_id=auto.id,
                    space_id=PERSONAL_SPACE_ID,
                    actor_user_id=DEFAULT_USER_ID,
                )

        # Roll back the failed transaction; no Run should have been committed.
        db.rollback()
        assert _count(db, Run) == before


# ---------------------------------------------------------------------------
# 8. No MemoryEntry / Policy / Proposal written by AutomationService
# ---------------------------------------------------------------------------

class TestAutomationDoesNotWriteForbiddenTypes:
    """AutomationService must not directly write Memory, Policy, Workspace, Capability, Credentials."""

    def _forbidden_counts(self, db) -> dict[str, int]:
        return {
            "memory_entries": _count(db, MemoryEntry),
            "policies": _count(db, Policy),
            "workspaces": _count(db, Workspace),
            "credentials": _count(db, Credential),
            "runtime_tool_bindings": _count(db, RuntimeToolBinding),
        }

    def test_create_does_not_write_memory_entry(self, db, test_agent):
        before = _count(db, MemoryEntry)
        AutomationService(db).create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="no-mem-test", agent_id=test_agent.id),
        )
        db.flush()
        assert _count(db, MemoryEntry) == before

    def test_fire_does_not_write_memory_entry(self, db, test_agent):
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="fire-no-mem", agent_id=test_agent.id),
        )
        # Commit to release write lock so fire's enforce() DurableWriter can commit.
        db.commit()
        before = _count(db, MemoryEntry)

        svc.fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()
        assert _count(db, MemoryEntry) == before

    def test_create_does_not_write_proposal(self, db, test_agent):
        from app.models import Proposal
        before = _count(db, Proposal)
        AutomationService(db).create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="no-prop-test", agent_id=test_agent.id),
        )
        db.flush()
        assert _count(db, Proposal) == before

    def test_create_does_not_write_forbidden_policy_automation_surfaces(self, db, test_agent):
        before = self._forbidden_counts(db)
        AutomationService(db).create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="no-forbidden-create", agent_id=test_agent.id),
        )
        db.flush()
        assert self._forbidden_counts(db) == before

    def test_fire_does_not_write_forbidden_policy_automation_surfaces(self, db, test_agent):
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="no-forbidden-fire", agent_id=test_agent.id),
        )
        db.commit()
        before = self._forbidden_counts(db)

        svc.fire(
            automation_id=auto.id,
            space_id=PERSONAL_SPACE_ID,
            actor_user_id=DEFAULT_USER_ID,
        )
        db.flush()
        assert self._forbidden_counts(db) == before


# ---------------------------------------------------------------------------
# 11. Insufficient-role API calls go through PolicyGateway and are recorded
# ---------------------------------------------------------------------------

def _make_member_user(db, uid: str) -> None:
    """Add a member-role user to PERSONAL_SPACE_ID (idempotent)."""
    from app.models import SpaceMembership, User

    if not db.query(User).filter(User.id == uid).first():
        db.add(User(
            id=uid,
            display_name="Member",
            email=f"{uid}@test.invalid",
        ))
    if not db.query(SpaceMembership).filter(
        SpaceMembership.space_id == PERSONAL_SPACE_ID,
        SpaceMembership.user_id == uid,
    ).first():
        db.add(SpaceMembership(
            id=f"sm_{uid}",
            space_id=PERSONAL_SPACE_ID,
            user_id=uid,
            role="member",
            status="active",
        ))
    db.flush()


def _make_role_user(db, uid: str, role: str) -> None:
    """Add a user with a specific role to PERSONAL_SPACE_ID (idempotent)."""
    from app.models import SpaceMembership, User

    if not db.query(User).filter(User.id == uid).first():
        db.add(User(
            id=uid,
            display_name=role.title(),
            email=f"{uid}@test.invalid",
        ))
    membership = db.query(SpaceMembership).filter(
        SpaceMembership.space_id == PERSONAL_SPACE_ID,
        SpaceMembership.user_id == uid,
    ).first()
    if membership is None:
        db.add(SpaceMembership(
            id=f"sm_{uid}",
            space_id=PERSONAL_SPACE_ID,
            user_id=uid,
            role=role,
            status="active",
        ))
    else:
        membership.role = role
        membership.status = "active"
    db.flush()


def _attach_version_model_provider(db, agent, *, with_api_key: bool = True):
    from app.models import AgentVersion
    from tests.support import factories

    provider = factories.create_test_model_provider(
        db,
        space_id=PERSONAL_SPACE_ID,
        with_api_key=with_api_key,
        commit=False,
    )
    version = db.query(AgentVersion).filter(
        AgentVersion.id == agent.current_version_id
    ).first()
    version.model_provider_id = provider.id
    db.flush()
    return provider


def _set_agent_version_provider(db, agent, provider_id: str) -> None:
    from app.models import AgentVersion

    version = db.query(AgentVersion).filter(
        AgentVersion.id == agent.current_version_id
    ).first()
    version.model_provider_id = provider_id
    db.flush()


def _set_agent_runtime_adapter_type(db, agent, adapter_type: str) -> None:
    from app.models import AgentVersion

    version = db.query(AgentVersion).filter(
        AgentVersion.id == agent.current_version_id
    ).first()
    version.runtime_config_json = {
        **(version.runtime_config_json or {}),
        "adapter_type": adapter_type,
    }
    allowed = set((version.runtime_policy_json or {}).get("allowed_adapter_types") or [])
    allowed.add(adapter_type)
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "allowed_adapter_types": sorted(allowed),
    }
    db.flush()


class TestInsufficientRoleCreatesPolicyRecord:
    """Denied automation.create/fire raises PolicyGateBlocked with correct decision attributes.

    Note: enforce() raises PolicyGateBlocked without writing a record itself.
    The global HTTP handler writes the durable deny record. Unit tests verify the
    exception's decision attributes; contract tests verify durable record persistence.
    """

    def test_member_create_denied_raises_policy_gate_blocked(self, db, test_agent):
        member_id = "member_create_test"
        _make_member_user(db, member_id)

        with pytest.raises(PolicyGateBlocked) as exc:
            AutomationService(db).create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=member_id,
                data=AutomationCreate(name="member-denied", agent_id=test_agent.id),
            )
        pgb = exc.value
        assert pgb.http_status_code == 403
        assert pgb.decision.denied
        assert pgb.decision.actor_id == member_id
        assert pgb.action == "automation.create"
        assert pgb.error_code == "policy_denied"

    def test_member_fire_denied_raises_policy_gate_blocked(self, db, test_agent):
        """Member cannot fire an automation — enforce() raises PolicyGateBlocked."""
        member_id = "member_fire_test"
        _make_member_user(db, member_id)
        # Commit to release write lock from _make_member_user's db.flush()
        # so the subsequent svc.create()'s enforce() DurableWriter can commit.
        db.commit()

        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="fire-member-denied", agent_id=test_agent.id),
        )
        db.flush()

        with pytest.raises(PolicyGateBlocked) as exc:
            svc.fire(
                automation_id=auto.id,
                space_id=PERSONAL_SPACE_ID,
                actor_user_id=member_id,
            )
        pgb = exc.value
        assert pgb.http_status_code == 403
        assert pgb.decision.denied
        assert pgb.decision.actor_id == member_id
        assert pgb.action == "automation.fire"
        assert pgb.error_code == "policy_denied"

    def test_member_update_denied_raises_policy_gate_blocked(self, db, test_agent):
        member_id = "member_update_test"
        _make_member_user(db, member_id)
        db.commit()

        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="update-member-denied", agent_id=test_agent.id),
        )
        db.flush()

        with pytest.raises(PolicyGateBlocked) as exc:
            svc.update(
                automation_id=auto.id,
                space_id=PERSONAL_SPACE_ID,
                actor_user_id=member_id,
                data=AutomationUpdate(name="should-not-change"),
            )
        pgb = exc.value
        assert pgb.http_status_code == 403
        assert pgb.decision.denied
        assert pgb.decision.actor_id == member_id
        assert pgb.action == "automation.update"
        assert pgb.error_code == "policy_denied"

    def test_member_create_denial_has_correct_policy_rule(self, db, test_agent):
        member_id = "member_reason_test"
        _make_member_user(db, member_id)

        with pytest.raises(PolicyGateBlocked) as exc:
            AutomationService(db).create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=member_id,
                data=AutomationCreate(name="reason-test", agent_id=test_agent.id),
            )
        pgb = exc.value
        assert pgb.decision.denied
        assert pgb.decision.policy_rule_id == "automation_insufficient_role"


class TestAutomationPolicyPreflight:
    def test_owner_create_succeeds_when_policy_preflight_passes(self, db, test_agent):
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="policy-preflight-ok", agent_id=test_agent.id),
        )
        db.flush()

        assert auto.preflight_snapshot_json["executable"] is True
        assert auto.preflight_snapshot_json["runtime_preflight"]["executable"] is True
        assert auto.preflight_snapshot_json["policy_preflight"]["executable"] is True

    def test_admin_create_succeeds_when_policy_preflight_passes(self, db, test_agent):
        admin_id = "admin_policy_preflight_ok"
        _make_role_user(db, admin_id, "admin")
        db.commit()

        auto = AutomationService(db).create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=admin_id,
            data=AutomationCreate(name="admin-policy-preflight-ok", agent_id=test_agent.id),
        )
        db.flush()

        assert auto.owner_user_id == admin_id
        assert auto.preflight_snapshot_json["policy_preflight"]["executable"] is True

    @pytest.mark.parametrize("role", ["member", "reviewer"])
    def test_create_fails_for_roles_denied_automation_create(self, db, test_agent, role):
        user_id = f"{role}_create_denied"
        _make_role_user(db, user_id, role)

        with pytest.raises(PolicyGateBlocked) as exc:
            AutomationService(db).create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=user_id,
                data=AutomationCreate(name=f"{role}-denied", agent_id=test_agent.id),
            )

        assert exc.value.action == "automation.create"
        assert exc.value.decision.denied
        assert exc.value.decision.policy_rule_id == "automation_insufficient_role"

    def test_create_fails_when_credential_policy_preflight_requires_approval(
        self, db, test_agent, monkeypatch
    ):
        monkeypatch.setattr(
            "app.runtimes.registry.is_adapter_type_implemented",
            lambda adapter_type: adapter_type == "model_provider_api",
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")
        _attach_version_model_provider(db, test_agent, with_api_key=True)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            AutomationService(db).create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=DEFAULT_USER_ID,
                data=AutomationCreate(name="credential-policy-blocked", agent_id=test_agent.id),
            )

        assert exc.value.status_code == 422
        detail = exc.value.detail
        assert detail["error"] == "policy_preflight_failed"
        assert any("runtime.use_credential" in e for e in detail["errors"])
        checks = detail["checks"]
        credential_checks = [c for c in checks if c["action"] == "runtime.use_credential"]
        assert credential_checks
        assert credential_checks[0]["decision"] == "require_approval"

    def test_fire_reruns_policy_preflight_and_fails_if_policy_changed_since_creation(
        self, db, test_agent, monkeypatch
    ):
        monkeypatch.setattr(
            "app.runtimes.registry.is_adapter_type_implemented",
            lambda adapter_type: adapter_type in {"echo", "model_provider_api"},
        )
        svc = AutomationService(db)
        auto = svc.create(
            space_id=PERSONAL_SPACE_ID,
            owner_user_id=DEFAULT_USER_ID,
            data=AutomationCreate(name="policy-preflight-rerun", agent_id=test_agent.id),
        )
        db.commit()

        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")
        _attach_version_model_provider(db, test_agent, with_api_key=True)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            svc.fire(
                automation_id=auto.id,
                space_id=PERSONAL_SPACE_ID,
                actor_user_id=DEFAULT_USER_ID,
            )

        assert exc.value.status_code == 422
        assert exc.value.detail["error"] == "policy_preflight_failed"
        assert any("runtime.use_credential" in e for e in exc.value.detail["errors"])

    def test_policy_preflight_does_not_write_policy_decision_record(self, db, test_agent):
        from unittest.mock import patch

        before = _count(db, PolicyDecisionRecord)

        with patch.object(PolicyGateway, "enforce", side_effect=AssertionError("no gateway")):
            result = AutomationPolicyPreflightService(db).check(
                space_id=PERSONAL_SPACE_ID,
                agent_id=test_agent.id,
                workspace_id=None,
                trigger_origin="automation",
            )

        assert result.executable is True
        assert _count(db, PolicyDecisionRecord) == before

    def test_policy_preflight_fails_for_unknown_runtime_requirements(self, db, test_agent):
        _set_agent_runtime_adapter_type(db, test_agent, "unknown_requirements_runtime")
        before = _count(db, PolicyDecisionRecord)

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        assert result.executable is False
        assert any("runtime_requirements_missing" in e for e in result.errors)
        assert _count(db, PolicyDecisionRecord) == before

    @pytest.mark.parametrize("adapter_type", ["claude_code", "codex_cli"])
    def test_cli_automation_policy_preflight_ignores_space_default_model_provider(
        self, db, test_agent, adapter_type
    ):
        from tests.support import factories

        factories.create_test_model_provider(
            db,
            space_id=PERSONAL_SPACE_ID,
            with_api_key=True,
            is_default=True,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, adapter_type)
        before = _count(db, PolicyDecisionRecord)

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        assert result.executable is True
        assert [c for c in result.checks if c.action == "runtime.use_credential"] == []
        assert _count(db, PolicyDecisionRecord) == before

    def test_api_runtime_policy_preflight_ignores_space_default_for_execution_parity(
        self, db, test_agent
    ):
        from tests.support import factories

        factories.create_test_model_provider(
            db,
            space_id=PERSONAL_SPACE_ID,
            with_api_key=True,
            is_default=True,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        credential_checks = [
            c for c in result.checks if c.action == "runtime.use_credential"
        ]
        assert result.executable is True
        assert credential_checks == []

    def test_manual_api_runtime_policy_preflight_ignores_space_default_for_execution_parity(
        self, db, test_agent
    ):
        from tests.support import factories

        factories.create_test_model_provider(
            db,
            space_id=PERSONAL_SPACE_ID,
            with_api_key=True,
            is_default=True,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="manual",
        )

        credential_checks = [
            c for c in result.checks if c.action == "runtime.use_credential"
        ]
        assert result.executable is True
        assert credential_checks == []

    def test_policy_preflight_fails_for_cross_space_agent_version_provider(self, db, test_agent):
        from tests.support import factories

        other_space = "policy-preflight-other-provider-space"
        factories.create_test_space(db, space_id=other_space, space_type="team")
        provider = factories.create_test_model_provider(
            db,
            space_id=other_space,
            with_api_key=True,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")
        _set_agent_version_provider(db, test_agent, provider.id)
        before = _count(db, PolicyDecisionRecord)

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        assert result.executable is False
        assert any("credential_metadata_cross_space" in e for e in result.errors)
        assert _count(db, PolicyDecisionRecord) == before

    def test_policy_preflight_fails_for_disabled_model_provider(self, db, test_agent):
        from tests.support import factories

        provider = factories.create_test_model_provider(
            db,
            space_id=PERSONAL_SPACE_ID,
            with_api_key=True,
            enabled=False,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")
        _set_agent_version_provider(db, test_agent, provider.id)
        before = _count(db, PolicyDecisionRecord)

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        assert result.executable is False
        assert any("credential_metadata_disabled_provider" in e for e in result.errors)
        assert _count(db, PolicyDecisionRecord) == before

    def test_policy_preflight_fails_for_cross_space_provider_credential(self, db, test_agent):
        from tests.support import factories

        other_space = "policy-preflight-other-credential-space"
        factories.create_test_space(db, space_id=other_space, space_type="team")
        credential = factories.create_test_credential_stub(
            db,
            space_id=other_space,
            commit=False,
        )
        provider = factories.create_test_model_provider(
            db,
            space_id=PERSONAL_SPACE_ID,
            credential_id=credential.id,
            commit=False,
        )
        _set_agent_runtime_adapter_type(db, test_agent, "model_provider_api")
        _set_agent_version_provider(db, test_agent, provider.id)
        before = _count(db, PolicyDecisionRecord)

        result = AutomationPolicyPreflightService(db).check(
            space_id=PERSONAL_SPACE_ID,
            agent_id=test_agent.id,
            workspace_id=None,
            trigger_origin="automation",
        )

        assert result.executable is False
        credential_checks = [
            c for c in result.checks if c.action == "runtime.use_credential"
        ]
        assert credential_checks
        assert credential_checks[0].decision == "deny"
        assert credential_checks[0].policy_rule_id == "space_boundary"
        assert any("runtime.use_credential" in e for e in result.errors)
        assert _count(db, PolicyDecisionRecord) == before


class TestAutomationConfigValidation:
    @pytest.mark.parametrize("key", [
        "api_key",
        "token",
        "secret",
        "password",
        "credential",
        "personal_context_block",
        "approved_by_user",
        "approved_by_granting_user",
        "approval_status",
        "is_approved",
        "auto_approved",
        "pre_approved",
    ])
    def test_create_config_json_rejects_forbidden_keys_before_persist(self, db, test_agent, key):
        before = _count(db, Automation)

        with pytest.raises(ValidationError):
            AutomationCreate(
                name="bad-config",
                agent_id=test_agent.id,
                config_json={"nested": {key: "blocked"}},
            )

        assert _count(db, Automation) == before

    def test_update_config_json_rejects_forbidden_keys(self):
        with pytest.raises(ValidationError):
            AutomationUpdate(config_json={"ok": [{"auto_approved": True}]})

    def test_config_json_rejects_oversized_string_before_persist(self, db, test_agent):
        before = _count(db, Automation)

        with pytest.raises(ValidationError):
            AutomationCreate(
                name="too-large-config",
                agent_id=test_agent.id,
                config_json={"value": "x" * 3000},
            )

        assert _count(db, Automation) == before


def test_create_audit_writer_failure_blocks_automation_row(db, test_agent):
    from unittest.mock import patch

    before = _count(db, Automation)
    with patch("app.policy.audit.DurablePolicyAuditWriter.write", side_effect=RuntimeError("audit down")):
        with pytest.raises(PolicyAuditPersistError):
            AutomationService(db).create(
                space_id=PERSONAL_SPACE_ID,
                owner_user_id=DEFAULT_USER_ID,
                data=AutomationCreate(name="audit-fail", agent_id=test_agent.id),
            )
    db.rollback()
    assert _count(db, Automation) == before
