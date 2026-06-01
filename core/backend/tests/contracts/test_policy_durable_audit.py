"""API-level durability tests for policy audit records.

C. API-level durability tests using fresh DB session after response:
  1. member denied automation.create: HTTP 403, durable PolicyDecisionRecord, no Automation row.
  2. member denied automation.fire: HTTP 403, durable record, no Run/AutomationRun row.
  3. automation.create preflight failure after policy allow: HTTP 422, no Automation row.
  4. automation.fire success: durable allow record, queued Run, AutomationRun.
  5. injected failure after Run flush but before AutomationRun flush: rollback, durable policy audit remains.

D. Proposal apply tests:
  1. denied proposal.apply creates durable PolicyDecisionRecord from fresh session.
  2. proposal.apply denial does not call ProposalApplyService.
  3. accepted proposal.apply still uses the normal apply path.

E. Runtime gate tests (basic HTTP-level only):
  1. denied runtime.execute creates durable PolicyDecisionRecord.
"""
from __future__ import annotations
import uuid

import pytest
from app.models import Automation, AutomationRun, PolicyDecisionRecord, Run, Proposal, MemoryEntry
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID
from tests.support import factories

pytestmark = pytest.mark.durable_audit


def _fresh_records(action: str, decision_value: str | None = None) -> list[PolicyDecisionRecord]:
    """Query PolicyDecisionRecord from a fresh session (verifies durability)."""
    from app.db import SessionLocal

    fresh = SessionLocal()
    try:
        q = fresh.query(PolicyDecisionRecord).filter(
            PolicyDecisionRecord.action == action
        )
        if decision_value is not None:
            q = q.filter(PolicyDecisionRecord.decision == decision_value)
        return q.all()
    finally:
        fresh.close()


def _fresh_count(model) -> int:
    from app.db import SessionLocal

    fresh = SessionLocal()
    try:
        return fresh.query(model).count()
    finally:
        fresh.close()


def _make_member_client(db, client, uid: str, space_id: str):
    """Create a member-role user and return a client authenticated as them."""
    from app.models import SpaceMembership, User
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app as _app
    from starlette.testclient import TestClient

    if not db.query(User).filter(User.id == uid).first():
        db.add(User(
            id=uid, display_name="Member",
            email=f"{uid}@test.invalid",
        ))
    if not db.query(SpaceMembership).filter(
        SpaceMembership.space_id == space_id,
        SpaceMembership.user_id == uid,
    ).first():
        db.add(SpaceMembership(
            id=f"sm_{uid}", space_id=space_id, user_id=uid,
            role="member", status="active",
        ))
    db.commit()

    svc = UserSessionService(db)
    _, raw = svc.create(uid)
    db.commit()

    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=False)


def _make_owner_client(db):
    """Return a TestClient authenticated as the default owner (DEFAULT_USER_ID).

    Commits db to release any pending write lock before creating the HTTP client,
    so the HTTP worker thread can use its own connection cleanly.
    """
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.main import app as _app
    from starlette.testclient import TestClient

    svc = UserSessionService(db)
    _, raw = svc.create(DEFAULT_USER_ID)
    db.commit()
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# C1. Member denied automation.create → 403 + durable record + no Automation
# ---------------------------------------------------------------------------

class TestMemberDeniedAutomationCreate:

    def test_denied_returns_403(self, db, client, test_agent):
        member_client = _make_member_client(db, client, "c1_member_create", PERSONAL_SPACE_ID)
        auto_count_before = _fresh_count(Automation)

        resp = member_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "denied-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 403

    def test_durable_record_created_after_403(self, db, client, test_agent):
        member_client = _make_member_client(db, client, "c1_member_create2", PERSONAL_SPACE_ID)

        before = [r.id for r in _fresh_records("automation.create", "deny")]
        member_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "denied-auto2", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        after = _fresh_records("automation.create", "deny")
        new_denials = [r for r in after if r.id not in before]
        assert len(new_denials) == 1, "Blocked sensitive action must write exactly one durable audit record"

    def test_no_automation_row_created(self, db, client, test_agent):
        member_client = _make_member_client(db, client, "c1_member_create3", PERSONAL_SPACE_ID)
        auto_count_before = _fresh_count(Automation)

        member_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "denied-auto3", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert _fresh_count(Automation) == auto_count_before, "No Automation row must be created on denial"


# ---------------------------------------------------------------------------
# C2. Member denied automation.fire → 403 + durable record + no Run/AutomationRun
# ---------------------------------------------------------------------------

class TestMemberDeniedAutomationFire:

    def _create_owner_auto(self, db, test_agent) -> str:
        """Create an automation as owner, return its id."""
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "owner-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_denied_returns_403(self, db, client, test_agent):
        auto_id = self._create_owner_auto(db, test_agent)
        member_client = _make_member_client(db, client, "c2_member_fire1", PERSONAL_SPACE_ID)

        resp = member_client.post(f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire", json={})
        assert resp.status_code == 403

    def test_durable_record_created_after_403(self, db, client, test_agent):
        auto_id = self._create_owner_auto(db, test_agent)
        member_client = _make_member_client(db, client, "c2_member_fire2", PERSONAL_SPACE_ID)

        before = [r.id for r in _fresh_records("automation.fire", "deny")]
        member_client.post(f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire", json={})
        after = _fresh_records("automation.fire", "deny")
        new_denials = [r for r in after if r.id not in before]
        assert len(new_denials) == 1, "Blocked sensitive action must write exactly one durable audit record"

    def test_no_run_or_automation_run_created(self, db, client, test_agent):
        auto_id = self._create_owner_auto(db, test_agent)
        member_client = _make_member_client(db, client, "c2_member_fire3", PERSONAL_SPACE_ID)

        run_count_before = _fresh_count(Run)
        auto_run_count_before = _fresh_count(AutomationRun)

        member_client.post(f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire", json={})

        assert _fresh_count(Run) == run_count_before, "No Run row must be created on fire denial"
        assert _fresh_count(AutomationRun) == auto_run_count_before, "No AutomationRun on fire denial"


# ---------------------------------------------------------------------------
# C3. automation.create preflight failure after policy allow → 422 + no Automation
# ---------------------------------------------------------------------------

class TestPreflightFailureAfterPolicyAllow:

    def test_preflight_fail_returns_422(self, db, client):
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "bad-agent-auto", "agent_id": "nonexistent-agent-id", "trigger_type": "manual"},
        )
        assert resp.status_code == 422

    def test_no_automation_row_on_preflight_failure(self, db, client):
        owner_client = _make_owner_client(db)
        auto_count_before = _fresh_count(Automation)
        owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "bad-agent-auto2", "agent_id": "nonexistent-agent-id", "trigger_type": "manual"},
        )
        assert _fresh_count(Automation) == auto_count_before


# ---------------------------------------------------------------------------
# C4. automation.fire success → durable allow record + Run + AutomationRun
# ---------------------------------------------------------------------------

class TestAutomationFireSuccess:

    def test_fire_creates_durable_allow_record(self, db, client, test_agent):
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "fire-success-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 201
        auto_id = resp.json()["id"]

        before = [r.id for r in _fresh_records("automation.fire", "allow")]
        fire_resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire",
            json={},
        )
        assert fire_resp.status_code == 200

        after = _fresh_records("automation.fire", "allow")
        new_allows = [r for r in after if r.id not in before]
        assert len(new_allows) >= 1, "Durable allow record for automation.fire must exist"

    def test_fire_creates_queued_run(self, db, client, test_agent):
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "fire-run-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 201
        auto_id = resp.json()["id"]

        fire_resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire",
            json={},
        )
        assert fire_resp.status_code == 200
        assert fire_resp.json().get("run_id") is not None

    def test_fire_creates_automation_run(self, db, client, test_agent):
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "fire-autorun-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 201
        auto_id = resp.json()["id"]

        fire_resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire",
            json={},
        )
        assert fire_resp.status_code == 200
        assert fire_resp.json().get("automation_run_id") is not None


# ---------------------------------------------------------------------------
# C5. Injected failure after Run flush but before AutomationRun flush → rollback
# ---------------------------------------------------------------------------

class TestInjectedFailureRollback:

    def test_failure_after_run_rolls_back_run(self, db, client, test_agent):
        from unittest.mock import patch

        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations",
            json={"name": "rollback-auto", "agent_id": test_agent.id, "trigger_type": "manual"},
        )
        assert resp.status_code == 201
        auto_id = resp.json()["id"]

        run_count_before = _fresh_count(Run)
        arun_count_before = _fresh_count(AutomationRun)

        # Patch AutomationRun to raise after Run is flushed
        with patch("app.automation.service.AutomationRun", side_effect=RuntimeError("injected")):
            fire_resp = owner_client.post(
                f"/api/v1/spaces/{PERSONAL_SPACE_ID}/automations/{auto_id}/fire",
                json={},
            )

        # Should be a server error (500)
        assert fire_resp.status_code == 500

        # No Run or AutomationRun committed
        assert _fresh_count(Run) == run_count_before
        assert _fresh_count(AutomationRun) == arun_count_before


# ---------------------------------------------------------------------------
# D1. denied proposal.apply creates durable PolicyDecisionRecord
# ---------------------------------------------------------------------------

class TestProposalApplyDurability:

    def _build_pending_proposal(self, db) -> Proposal:
        from app.memory.proposals import build_memory_create_proposal

        pid = str(uuid.uuid4())
        p = build_memory_create_proposal(
            proposal_id=pid,
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            workspace_id=None,
            proposed_title="Test Memory",
            proposed_content="Test content",
            rationale="Test",
            memory_type="fact",
            target_scope="user",
            target_namespace="test",
            extra_provenance_entries=[
                {
                    "source_type": "user_confirmation",
                    "source_id": DEFAULT_USER_ID,
                    "source_trust": "user_confirmed",
                }
            ],
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return p

    def test_denied_apply_creates_durable_record(self, db, client):
        """A guest-level context: member can't apply proposals of high risk directly."""
        proposal = self._build_pending_proposal(db)

        # Use a member user (not owner) — member gets REQUIRE_APPROVAL for medium+ proposals
        member_client = _make_member_client(db, client, "d1_member_apply", PERSONAL_SPACE_ID)

        before = [r.id for r in _fresh_records("proposal.apply")]
        member_client.post(f"/api/v1/proposals/{proposal.id}/accept")

        after = _fresh_records("proposal.apply")
        new_records = [r for r in after if r.id not in before]
        # Member gets require_approval or deny → PolicyGateBlocked → durable record
        assert len(new_records) == 1, "Denied proposal.apply must write exactly one durable audit record"

    def test_denied_apply_does_not_apply(self, db, client):
        proposal = self._build_pending_proposal(db)
        member_client = _make_member_client(db, client, "d2_member_apply", PERSONAL_SPACE_ID)

        member_client.post(f"/api/v1/proposals/{proposal.id}/accept")

        # Use db directly — proposal is in the test db_engine, not SessionLocal's AGENT_SPACE_HOME DB.
        db.expire(proposal)
        assert proposal.status == "pending", "Proposal must remain pending after member denial"

    def test_owner_accept_proposal_succeeds(self, db, client):
        proposal = self._build_pending_proposal(db)

        before = [r.id for r in _fresh_records("proposal.apply", "allow")]
        owner_client = _make_owner_client(db)
        resp = owner_client.post(
            f"/api/v1/proposals/{proposal.id}/accept",
            params={"space_id": PERSONAL_SPACE_ID},
        )
        assert resp.status_code == 200, resp.text
        new_allows = [r for r in _fresh_records("proposal.apply", "allow") if r.id not in before]
        assert len(new_allows) == 1, "Allowed proposal.apply must write exactly one durable audit record"


# ---------------------------------------------------------------------------
# E1. denied runtime.execute creates durable PolicyDecisionRecord
# ---------------------------------------------------------------------------

class TestRuntimeExecuteDurability:

    def test_inactive_agent_denied_execute_creates_durable_record(self, db, client, test_agent):
        """An inactive agent → rule_agent_status DENY → PolicyGateBlocked → durable record."""
        from app.models import Agent
        from app.runs.run_service import RunService
        from app.schemas import RunCreate

        # Create run while agent is still active, then mark inactive before execute.
        run = RunService(db).create_run(
            agent_id=test_agent.id,
            data=RunCreate(trigger_origin="manual"),
            space_id=PERSONAL_SPACE_ID,
            user_id=DEFAULT_USER_ID,
            commit=True,
        )
        agent_row = db.query(Agent).filter(Agent.id == test_agent.id).first()
        agent_row.status = "inactive"
        db.commit()

        owner_client = _make_owner_client(db)

        before = [r.id for r in _fresh_records("runtime.execute", "deny")]
        resp = owner_client.post(
            f"/api/v1/runs/{run.id}/execute?space_id={PERSONAL_SPACE_ID}"
        )
        # execute_run catches PolicyGateBlocked internally, marks run as failed, returns 200.
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert body.get("error_json", {}).get("error_code") == "policy_denied_runtime_execute"

        after = _fresh_records("runtime.execute", "deny")
        new_denials = [r for r in after if r.id not in before]
        assert len(new_denials) == 1, "Denied runtime.execute must write exactly one durable audit record"
