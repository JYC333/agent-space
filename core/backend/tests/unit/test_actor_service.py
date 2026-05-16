"""Unit tests for ActorService helpers (M2).

Tests cover idempotency, invariants, and the rule that system/service/job actors
must not resolve through Settings.default_user_id.
"""
from __future__ import annotations

import pytest

from app.actors.service import (
    actor_ref_for_agent,
    actor_ref_for_job,
    actor_ref_for_service,
    actor_ref_for_system,
    actor_ref_for_user,
    get_or_create_agent_actor,
    get_or_create_job_actor,
    get_or_create_service_actor,
    get_or_create_system_actor,
    get_or_create_user_actor,
    resolve_actor_ref,
)
from app.models import Actor
from app.schemas import ActorRef
from tests.support import factories


# ---------------------------------------------------------------------------
# get_or_create_user_actor — idempotency
# ---------------------------------------------------------------------------

def test_user_actor_creation(db, test_user, test_space):
    actor = get_or_create_user_actor(db, test_user, test_space.id)
    assert actor.id is not None
    assert actor.actor_type == "user"
    assert actor.user_id == test_user.id
    assert actor.space_id == test_space.id
    assert actor.agent_id is None
    assert actor.status == "active"


def test_user_actor_is_idempotent(db, test_user, test_space):
    a1 = get_or_create_user_actor(db, test_user, test_space.id)
    a2 = get_or_create_user_actor(db, test_user, test_space.id)
    assert a1.id == a2.id


def test_user_actor_has_no_agent_id(db, test_user, test_space):
    actor = get_or_create_user_actor(db, test_user, test_space.id)
    assert actor.agent_id is None


# ---------------------------------------------------------------------------
# get_or_create_agent_actor — idempotency
# ---------------------------------------------------------------------------

def test_agent_actor_creation(db, test_agent, test_space):
    actor = get_or_create_agent_actor(db, test_agent, test_space.id)
    assert actor.actor_type == "agent"
    assert actor.agent_id == test_agent.id
    assert actor.user_id is None
    assert actor.space_id == test_space.id


def test_agent_actor_is_idempotent(db, test_agent, test_space):
    a1 = get_or_create_agent_actor(db, test_agent, test_space.id)
    a2 = get_or_create_agent_actor(db, test_agent, test_space.id)
    assert a1.id == a2.id


def test_agent_actor_has_no_user_id(db, test_agent, test_space):
    actor = get_or_create_agent_actor(db, test_agent, test_space.id)
    assert actor.user_id is None


# ---------------------------------------------------------------------------
# get_or_create_system_actor — idempotency and no default_user reliance
# ---------------------------------------------------------------------------

def test_system_actor_creation(db):
    actor = get_or_create_system_actor(db, space_id=None, service_name="system")
    assert actor.actor_type == "system"
    assert actor.user_id is None
    assert actor.agent_id is None
    assert actor.service_name == "system"


def test_system_actor_is_idempotent(db):
    a1 = get_or_create_system_actor(db, space_id=None, service_name="system")
    a2 = get_or_create_system_actor(db, space_id=None, service_name="system")
    assert a1.id == a2.id


def test_system_actor_does_not_require_user_id(db):
    """Critical: system actor must never require or use Settings.default_user_id."""
    actor = get_or_create_system_actor(db, space_id=None)
    assert actor.user_id is None
    assert actor.agent_id is None


def test_system_actor_with_space(db, test_space):
    actor = get_or_create_system_actor(db, space_id=test_space.id, service_name="reflector")
    assert actor.actor_type == "system"
    assert actor.space_id == test_space.id
    assert actor.user_id is None


# ---------------------------------------------------------------------------
# get_or_create_service_actor
# ---------------------------------------------------------------------------

def test_service_actor_creation(db):
    actor = get_or_create_service_actor(db, service_name="memory_consolidation")
    assert actor.actor_type == "service"
    assert actor.service_name == "memory_consolidation"
    assert actor.user_id is None
    assert actor.agent_id is None


def test_service_actor_is_idempotent(db):
    a1 = get_or_create_service_actor(db, service_name="memory_consolidation")
    a2 = get_or_create_service_actor(db, service_name="memory_consolidation")
    assert a1.id == a2.id


# ---------------------------------------------------------------------------
# get_or_create_job_actor
# ---------------------------------------------------------------------------

def test_job_actor_creation(db, test_space):
    actor = get_or_create_job_actor(db, service_name="agent_run", space_id=test_space.id)
    assert actor.actor_type == "job"
    assert actor.service_name == "agent_run"
    assert actor.user_id is None
    assert actor.agent_id is None


def test_job_actor_is_idempotent(db, test_space):
    a1 = get_or_create_job_actor(db, service_name="agent_run", space_id=test_space.id)
    a2 = get_or_create_job_actor(db, service_name="agent_run", space_id=test_space.id)
    assert a1.id == a2.id


# ---------------------------------------------------------------------------
# ActorRef factory functions (no DB required)
# ---------------------------------------------------------------------------

def test_actor_ref_for_user(test_user, test_space):
    ref = actor_ref_for_user(test_user, test_space.id)
    assert ref.actor_type == "user"
    assert ref.user_id == test_user.id
    assert ref.space_id == test_space.id
    assert ref.agent_id is None


def test_actor_ref_for_agent(test_agent, test_space):
    ref = actor_ref_for_agent(test_agent, test_space.id)
    assert ref.actor_type == "agent"
    assert ref.agent_id == test_agent.id
    assert ref.space_id == test_space.id
    assert ref.user_id is None


def test_actor_ref_for_system():
    ref = actor_ref_for_system()
    assert ref.actor_type == "system"
    assert ref.user_id is None
    assert ref.agent_id is None


def test_actor_ref_for_system_no_default_user():
    """Verify system ActorRef factory never injects Settings.default_user_id."""
    from app.config import settings
    ref = actor_ref_for_system(service_name="system")
    assert ref.user_id != settings.default_user_id
    assert ref.user_id is None


def test_actor_ref_for_service():
    ref = actor_ref_for_service("memory_consolidation")
    assert ref.actor_type == "service"
    assert ref.service_name == "memory_consolidation"


def test_actor_ref_for_job():
    ref = actor_ref_for_job("agent_run", space_id="personal")
    assert ref.actor_type == "job"
    assert ref.space_id == "personal"


# ---------------------------------------------------------------------------
# resolve_actor_ref
# ---------------------------------------------------------------------------

def test_resolve_actor_ref_by_actor_id(db, test_user, test_space):
    actor = get_or_create_user_actor(db, test_user, test_space.id)
    ref = ActorRef(actor_type="user", user_id=test_user.id, actor_id=actor.id)
    resolved = resolve_actor_ref(db, ref)
    assert resolved is not None
    assert resolved.id == actor.id


def test_resolve_actor_ref_by_user_id(db, test_user, test_space):
    actor = get_or_create_user_actor(db, test_user, test_space.id)
    ref = ActorRef(actor_type="user", user_id=test_user.id, space_id=test_space.id)
    resolved = resolve_actor_ref(db, ref)
    assert resolved is not None
    assert resolved.id == actor.id


def test_resolve_actor_ref_by_system_service_name(db):
    actor = get_or_create_system_actor(db, space_id=None, service_name="system")
    ref = ActorRef(actor_type="system", service_name="system")
    resolved = resolve_actor_ref(db, ref)
    assert resolved is not None
    assert resolved.id == actor.id


def test_resolve_actor_ref_returns_none_when_not_found(db):
    ref = ActorRef(actor_type="user", user_id="nonexistent-user-id")
    resolved = resolve_actor_ref(db, ref)
    assert resolved is None


# ---------------------------------------------------------------------------
# User and Agent remain separate models
# ---------------------------------------------------------------------------

def test_user_and_agent_are_separate_orm_models(db, test_user, test_agent, test_space):
    """Invariant: user Actor and agent Actor use separate FK columns; never merged."""
    user_actor = get_or_create_user_actor(db, test_user, test_space.id)
    agent_actor = get_or_create_agent_actor(db, test_agent, test_space.id)

    assert user_actor.id != agent_actor.id
    assert user_actor.user_id == test_user.id
    assert user_actor.agent_id is None
    assert agent_actor.agent_id == test_agent.id
    assert agent_actor.user_id is None

    # DB-level check: both rows exist and are distinct
    rows = db.query(Actor).filter(
        Actor.id.in_([user_actor.id, agent_actor.id])
    ).all()
    assert len(rows) == 2
