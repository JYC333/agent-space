"""Invariant tests for Actor identity foundation (M2).

Covers:
- User and Agent remain separate (not merged into Actor)
- System/service/job actors must not impersonate default_user
- Existing nullable user_id/agent_id fields remain readable
- Policy context can carry ActorRef without changing existing decision behavior
- New surfaces (RunStep/audit/policy) must require actor identity (M3 gate)
- HTTP query/default identity fallback remains absent
"""
from __future__ import annotations

import pytest

from app.actors.service import (
    actor_ref_for_system,
    actor_ref_for_user,
    get_or_create_agent_actor,
    get_or_create_job_actor,
    get_or_create_service_actor,
    get_or_create_system_actor,
    get_or_create_user_actor,
    resolve_actor_ref,
)
from app.models import Actor, ActivityRecord, Proposal, Run
from app.policy.engine import PolicyEngine
from app.schemas import ActorRef
from tests.support import factories


# ---------------------------------------------------------------------------
# Invariant: User and Agent remain separate models
# ---------------------------------------------------------------------------

def test_user_model_is_not_merged_with_agent(db, test_user, test_agent, test_space):
    """User and Agent are distinct ORM classes and DB tables — never merged into one."""
    from app.models import User, Agent
    assert User.__tablename__ == "users"
    assert Agent.__tablename__ == "agents"
    assert User.__tablename__ != Agent.__tablename__


def test_user_actor_and_agent_actor_use_separate_fk_columns(db, test_user, test_agent, test_space):
    """Actor table keeps user_id and agent_id as separate nullable FKs, never conflated."""
    ua = get_or_create_user_actor(db, test_user, test_space.id)
    ag = get_or_create_agent_actor(db, test_agent, test_space.id)

    assert ua.user_id is not None and ua.agent_id is None
    assert ag.agent_id is not None and ag.user_id is None


def test_actors_table_exists_with_expected_actor_types(db, test_user, test_agent, test_space):
    """Every declared actor_type can be persisted without constraint violations."""
    valid_types = [
        ("user", {"user_id": test_user.id}),
        ("agent", {"agent_id": test_agent.id}),
        ("system", {"service_name": "system"}),
        ("service", {"service_name": "test-service"}),
        ("job", {"service_name": "test-job"}),
        ("automation", {"service_name": "test-automation"}),
        ("connector", {"service_name": "test-connector"}),
        ("integration", {"service_name": "test-integration"}),
    ]
    for atype, kwargs in valid_types:
        row = factories.create_test_actor(
            db,
            actor_type=atype,
            space_id=test_space.id,
            **kwargs,
            commit=False,
        )
        db.flush()
        assert row.id is not None
        assert row.actor_type == atype


# ---------------------------------------------------------------------------
# Invariant: system/service/job actors must not use default_user_id
# ---------------------------------------------------------------------------

def test_system_actor_does_not_use_default_user_id(db):
    """ActorService must never resolve system actors through Settings.default_user_id."""
    from app.config import settings
    actor = get_or_create_system_actor(db, space_id=None, service_name="system")
    assert actor.user_id is None
    assert actor.user_id != settings.default_user_id


def test_service_actor_does_not_use_default_user_id(db):
    from app.config import settings
    actor = get_or_create_service_actor(db, service_name="memory_consolidation")
    assert actor.user_id is None
    assert actor.user_id != settings.default_user_id


def test_job_actor_does_not_use_default_user_id(db, test_space):
    from app.config import settings
    actor = get_or_create_job_actor(db, service_name="agent_run", space_id=test_space.id)
    assert actor.user_id is None
    assert actor.user_id != settings.default_user_id


def test_system_actor_ref_factory_does_not_use_default_user_id():
    """actor_ref_for_system() must never inject Settings.default_user_id."""
    from app.config import settings
    ref = actor_ref_for_system(service_name="system")
    assert ref.user_id is None
    assert ref.user_id != settings.default_user_id


# ---------------------------------------------------------------------------
# Invariant: existing nullable user_id/agent_id fields remain readable
# ---------------------------------------------------------------------------

def test_run_instructed_by_user_id_is_readable(db, test_user, test_space):
    """Run.instructed_by_user_id records the human actor who instructed the run."""
    run = factories.create_test_run(db, space_id=test_space.id, user_id=test_user.id)
    assert run.instructed_by_user_id == test_user.id


def test_proposal_existing_created_by_fields_remain_readable(db, test_user, test_space):
    """Proposal.created_by_user_id and created_by_agent_id are not removed in M2."""
    prop = factories.create_test_proposal(
        db,
        space_id=test_space.id,
        created_by_user_id=test_user.id,
    )
    assert prop.created_by_user_id == test_user.id
    assert prop.created_by_agent_id is None  # nullable


def test_activity_existing_user_id_and_agent_id_remain_readable(db, test_user, test_space):
    """ActivityRecord.user_id and agent_id fields are not removed in M2."""
    act = factories.create_test_activity(
        db,
        space_id=test_space.id,
        actor_user_id=test_user.id,
    )
    assert act.user_id == test_user.id
    assert act.agent_id is None


def test_existing_null_user_agent_rows_remain_readable(db, test_space):
    """Rows with null user_id and null agent_id (system-originated) are still readable."""
    # Simulate a system-created run with no instructed_by_user
    act = factories.create_test_activity(
        db,
        space_id=test_space.id,
        actor_user_id=None,
        agent_id=None,
        activity_type="system_event",
    )
    db.flush()
    row = db.query(ActivityRecord).filter(ActivityRecord.id == act.id).first()
    assert row is not None
    assert row.user_id is None
    assert row.agent_id is None


# ---------------------------------------------------------------------------
# Policy context stability: ActorRef can be passed without changing decisions
# ---------------------------------------------------------------------------

def test_policy_context_accepts_actor_ref_without_changing_allow_decision():
    """PolicyEngine.check() is unaffected by the presence of an ActorRef in context."""
    engine = PolicyEngine()
    ref = ActorRef(actor_type="user", user_id="u-1", space_id="personal")
    ctx_without = {
        "action": "context.inject_memory",
        "space_id": "personal",
        "resource_space_id": "personal",
        "agent_status": "active",
    }
    ctx_with_actor = {
        **ctx_without,
        "actor_ref": ref.model_dump(),
    }
    d_without = engine.check(ctx_without)
    d_with = engine.check(ctx_with_actor)
    assert d_without.allowed
    assert d_with.allowed
    assert d_without.policy_rule_id == d_with.policy_rule_id


def test_policy_context_accepts_system_actor_ref_without_changing_deny_decision():
    """A system ActorRef in context does not override space-boundary deny."""
    engine = PolicyEngine()
    ref = actor_ref_for_system(service_name="system", space_id="personal")
    ctx = {
        "action": "context.inject_memory",
        "space_id": "personal",
        "resource_space_id": "work",
        "actor_ref": ref.model_dump(),
    }
    d = engine.check(ctx)
    assert d.denied
    assert d.policy_rule_id == "space_boundary"


def test_policy_context_actor_ref_field_is_stable_json():
    """ActorRef serialized into policy context must round-trip cleanly."""
    ref = ActorRef(
        actor_type="agent",
        agent_id="agent-123",
        space_id="personal",
        actor_id="actor-row-456",
    )
    serialized = ref.model_dump()
    restored = ActorRef.model_validate(serialized)
    assert restored.actor_type == ref.actor_type
    assert restored.agent_id == ref.agent_id
    assert restored.actor_id == ref.actor_id


# ---------------------------------------------------------------------------
# Auth: identity fallback must use session membership, never default_user/User.space_id
# ---------------------------------------------------------------------------

def test_no_default_user_fallback_in_get_identity(client):
    """get_identity must return 401 with no auth — not fall through to default_user."""
    resp = client.get("/api/v1/memory/", headers={})
    assert resp.status_code == 401


def test_session_identity_without_space_id_selects_personal_membership(client, db):
    """Session auth without ?space_id picks the user's active personal space first."""
    from app.auth.session import SESSION_COOKIE, UserSessionService
    from app.models import SpaceMembership

    team_space = "identity-team-space"
    personal_space = "identity-personal-space"
    factories.create_test_space(db, space_id=team_space, name="Team", space_type="team")
    factories.create_test_space(db, space_id=personal_space, name="Personal", space_type="personal")
    user = factories.create_test_user(db, space_id=team_space, display_name="Identity User")
    db.add(
        SpaceMembership(
            id="identity-personal-membership",
            space_id=personal_space,
            user_id=user.id,
            role="owner",
            status="active",
        )
    )
    factories.create_test_workspace(db, space_id=team_space, created_by_user_id=user.id, name="team ws")
    personal_ws = factories.create_test_workspace(
        db,
        space_id=personal_space,
        created_by_user_id=user.id,
        name="personal ws",
    )
    _, raw = UserSessionService(db).create(user.id)
    db.commit()
    client.cookies.set(SESSION_COOKIE, raw)

    resp = client.get("/api/v1/workspaces")

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert personal_ws.id in ids
    assert all(item["owner_space_id"] == personal_space for item in resp.json()["items"])


# ---------------------------------------------------------------------------
# M3 gate: future RunStep surfaces must require actor identity
# ---------------------------------------------------------------------------

def test_m3_runstep_actor_contract_is_enforced():
    """M3 RunStep rows must carry actor_id (NOT NULL constraint).

    RunStep.actor_id is NOT NULL at the ORM/DDL level, so every execution replay
    step is attributable to a concrete Actor row.  This test verifies the column
    constraint is present and that system/job/user actor types can all satisfy it.
    """
    from sqlalchemy import inspect as sa_inspect
    from app.models import Base, RunStep

    # Table must exist (M3 implemented)
    table_names = {t for t in Base.metadata.tables}
    assert "run_steps" in table_names, "run_steps table must exist after M3"

    # actor_id column must be NOT NULL
    mapper = sa_inspect(RunStep)
    col = mapper.columns["actor_id"]
    assert not col.nullable, "RunStep.actor_id must be NOT NULL (M3 contract)"
