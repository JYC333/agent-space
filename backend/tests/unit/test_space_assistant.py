"""System-managed default Assistant: seeding, resolution, ownership, preferences.

The default Assistant is the space's Chat identity — a system-managed Agent backed
by a real AgentVersion, minted from the internal ``personal_assistant`` seed spec.
It is not a user-created template instance, there is at most one active per space,
and its hard safety policy lives on the immutable AgentVersion (never on the soft
preferences layer).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.assistant_settings import AssistantSettingsService
from app.agents.personal_assistant import (
    SYSTEM_ASSISTANT_KIND,
    get_default_assistant,
    get_or_create_default_assistant,
)
from app.agents.template_seeder import seed_system_templates
from app.models import Agent, AgentVersion, Space
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

SPACE = PERSONAL_SPACE_ID
USER = DEFAULT_USER_ID


def _current_version(db, agent: Agent) -> AgentVersion:
    return db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()


# 1 + 8. Seeding/resolution is idempotent and returns the same Assistant.
def test_get_or_create_default_assistant_is_idempotent(db):
    seed_system_templates(db)
    assert get_default_assistant(db, space_id=SPACE) is None

    a1 = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    a2 = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    assert a1.id == a2.id
    assert get_default_assistant(db, space_id=SPACE).id == a1.id
    assert a1.agent_kind == SYSTEM_ASSISTANT_KIND


# 2. At most one active default assistant per space (DB partial-unique index).
def test_only_one_active_assistant_per_space(db):
    seed_system_templates(db)
    a1 = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)

    # Only one assistant agent exists after repeated calls.
    get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    count = (
        db.query(Agent)
        .filter(Agent.space_id == SPACE, Agent.agent_kind == SYSTEM_ASSISTANT_KIND, Agent.status == "active")
        .count()
    )
    assert count == 1

    # The DB index rejects a second active system assistant in the same space.
    dup = Agent(
        space_id=SPACE, owner_user_id=None, name="Dup Assistant", status="active",
        agent_kind=SYSTEM_ASSISTANT_KIND, source_template_id=a1.source_template_id,
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# 3. Default assistant has a real AgentVersion (runtime config snapshot).
def test_default_assistant_has_real_agent_version(db):
    seed_system_templates(db)
    a = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    assert a.current_version_id is not None
    version = _current_version(db, a)
    assert version.agent_id == a.id
    assert version.space_id == SPACE


# 4. System/space-owned, not ordinary user-owned; carries template provenance.
def test_default_assistant_is_system_owned(db):
    seed_system_templates(db)
    # Even when a user id is passed, the assistant stays system-managed (owner NULL).
    a = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=USER)
    assert a.owner_user_id is None
    assert a.source_template_id is not None  # internal provenance retained


# Naming follows space type: personal -> Personal Assistant, shared -> Space Assistant.
def test_assistant_name_follows_space_type(db):
    seed_system_templates(db)
    personal = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    assert personal.name == "Personal Assistant"

    team = Space(name="Team", type="team", created_by_user_id=USER)
    db.add(team)
    db.flush()
    team_assistant = get_or_create_default_assistant(db, space_id=team.id, owner_user_id=None)
    assert team_assistant.name == "Space Assistant"


# Hard-safety policy is on the AgentVersion: deny writes, proposal-only outputs.
def test_assistant_version_carries_hard_safety_policy(db):
    seed_system_templates(db)
    a = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    v = _current_version(db, a)

    assert v.memory_policy_json.get("writable_scopes") == []
    assert v.memory_policy_json.get("requires_proposal") is True
    assert v.output_policy_json.get("proposal_only") is True
    assert v.tool_policy_json.get("shell") is False
    assert v.tool_policy_json.get("file_write") is False
    assert v.tool_policy_json.get("credential_access") is False
    allowed_outputs = set(v.output_policy_json.get("allowed_output_types", []))
    assert {"chat_message", "task_create_proposal", "noop"} <= allowed_outputs
    # No durable direct-write output is allowed.
    assert "memory_write" not in allowed_outputs
    assert "task_create" not in allowed_outputs


# 9 + 10 + 12. Preferences update never mints a new AgentVersion or loosens policy.
def test_preferences_do_not_mutate_agent_version_or_policy(db):
    seed_system_templates(db)
    a = get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    version_id_before = a.current_version_id
    policy_before = dict(_current_version(db, a).output_policy_json)

    svc = AssistantSettingsService(db)
    settings = svc.update(
        SPACE,
        {
            "response_style": "friendly",
            "verbosity": "concise",
            "proposal_style": "proactive",
            "default_context_toggles_json": {"memory": True, "wiki": False},
            # Attempts to smuggle policy fields are ignored (not in the allow-list).
            "tool_policy_json": {"shell": True},
            "output_policy_json": {"proposal_only": False},
        },
    )
    assert settings.response_style == "friendly"
    assert settings.verbosity == "concise"
    assert settings.assistant_agent_id == a.id

    # No new AgentVersion; hard policy unchanged.
    db.refresh(a)
    assert a.current_version_id == version_id_before
    assert _current_version(db, a).output_policy_json == policy_before
    assert _current_version(db, a).tool_policy_json.get("shell") is False


def test_preferences_get_or_create_is_idempotent(db):
    seed_system_templates(db)
    get_or_create_default_assistant(db, space_id=SPACE, owner_user_id=None)
    svc = AssistantSettingsService(db)
    s1 = svc.get_or_create(SPACE)
    s2 = svc.get_or_create(SPACE)
    assert s1.id == s2.id
