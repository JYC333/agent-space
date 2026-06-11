"""Unit tests for ActorRef validation and serialization (M2)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import ActorRef, ACTOR_TYPES


# ---------------------------------------------------------------------------
# Valid actor refs
# ---------------------------------------------------------------------------

def test_user_actor_ref_valid():
    ref = ActorRef(actor_type="user", user_id="u-1", space_id="personal")
    assert ref.actor_type == "user"
    assert ref.user_id == "u-1"
    assert ref.agent_id is None


def test_agent_actor_ref_valid():
    ref = ActorRef(actor_type="agent", agent_id="a-1", space_id="personal")
    assert ref.actor_type == "agent"
    assert ref.agent_id == "a-1"
    assert ref.user_id is None


def test_system_actor_ref_valid():
    ref = ActorRef(actor_type="system", service_name="system")
    assert ref.actor_type == "system"
    assert ref.user_id is None
    assert ref.agent_id is None


def test_service_actor_ref_valid():
    ref = ActorRef(actor_type="service", service_name="memory_consolidation")
    assert ref.actor_type == "service"
    assert ref.service_name == "memory_consolidation"


def test_job_actor_ref_valid():
    ref = ActorRef(actor_type="job", service_name="agent_run", space_id="personal")
    assert ref.actor_type == "job"
    assert ref.service_name == "agent_run"


def test_automation_actor_ref_valid():
    ref = ActorRef(actor_type="automation", service_name="scheduled_digest")
    assert ref.actor_type == "automation"


def test_connector_actor_ref_valid():
    ref = ActorRef(actor_type="connector", service_name="github")
    assert ref.actor_type == "connector"


def test_integration_actor_ref_valid():
    ref = ActorRef(actor_type="integration", service_name="slack")
    assert ref.actor_type == "integration"


def test_actor_ref_with_actor_id():
    ref = ActorRef(actor_type="user", user_id="u-1", actor_id="actor-row-123")
    assert ref.actor_id == "actor-row-123"


# ---------------------------------------------------------------------------
# Invalid actor refs
# ---------------------------------------------------------------------------

def test_user_actor_ref_missing_user_id_rejected():
    with pytest.raises(ValidationError, match="user_id"):
        ActorRef(actor_type="user")


def test_agent_actor_ref_missing_agent_id_rejected():
    with pytest.raises(ValidationError, match="agent_id"):
        ActorRef(actor_type="agent")


def test_user_actor_ref_with_agent_id_rejected():
    with pytest.raises(ValidationError, match="must not have agent_id"):
        ActorRef(actor_type="user", user_id="u-1", agent_id="a-1")


def test_agent_actor_ref_with_user_id_rejected():
    with pytest.raises(ValidationError, match="must not have user_id"):
        ActorRef(actor_type="agent", agent_id="a-1", user_id="u-1")


def test_system_actor_ref_with_user_id_rejected():
    with pytest.raises(ValidationError, match="must not have user_id"):
        ActorRef(actor_type="system", user_id="u-1")


def test_system_actor_ref_with_agent_id_rejected():
    with pytest.raises(ValidationError, match="must not have agent_id"):
        ActorRef(actor_type="system", agent_id="a-1")


def test_job_actor_ref_with_user_id_rejected():
    with pytest.raises(ValidationError, match="must not have user_id"):
        ActorRef(actor_type="job", user_id="u-1")


def test_invalid_actor_type_rejected():
    with pytest.raises(ValidationError, match="invalid actor_type"):
        ActorRef(actor_type="superuser", user_id="u-1")


def test_unknown_actor_type_rejected():
    with pytest.raises(ValidationError, match="invalid actor_type"):
        ActorRef(actor_type="default_user")


def test_service_actor_ref_missing_service_name_rejected():
    with pytest.raises(ValidationError, match="requires service_name"):
        ActorRef(actor_type="service")


def test_job_actor_ref_missing_service_name_rejected():
    with pytest.raises(ValidationError, match="requires service_name"):
        ActorRef(actor_type="job")


def test_system_actor_ref_defaults_service_name_to_system():
    """ActorRef(actor_type='system') without service_name must auto-default to 'system'."""
    ref = ActorRef(actor_type="system")
    assert ref.service_name == "system"
    assert ref.user_id is None
    assert ref.agent_id is None


# ---------------------------------------------------------------------------
# Serialization stability
# ---------------------------------------------------------------------------

def test_actor_ref_serializes_to_dict():
    ref = ActorRef(actor_type="user", user_id="u-1", space_id="personal", display_name="Alice")
    d = ref.model_dump()
    assert d["actor_type"] == "user"
    assert d["user_id"] == "u-1"
    assert d["space_id"] == "personal"
    assert d["display_name"] == "Alice"
    assert d["agent_id"] is None
    assert d["actor_id"] is None


def test_actor_ref_round_trips_json():
    ref = ActorRef(actor_type="system", service_name="system", space_id=None)
    json_str = ref.model_dump_json()
    restored = ActorRef.model_validate_json(json_str)
    assert restored.actor_type == "system"
    assert restored.service_name == "system"
    assert restored.user_id is None
    assert restored.agent_id is None


def test_all_declared_actor_types_are_valid():
    """Every type in ACTOR_TYPES must parse without error when given the right identity fields."""
    for atype in ACTOR_TYPES:
        if atype == "user":
            ActorRef(actor_type=atype, user_id="u-test")
        elif atype == "agent":
            ActorRef(actor_type=atype, agent_id="a-test")
        else:
            ActorRef(actor_type=atype, service_name=atype)
