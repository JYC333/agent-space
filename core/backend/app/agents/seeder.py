from __future__ import annotations
"""
Built-in agent seeder.

Seeds the two system agents that every deployment starts with:
  - echo-agent          — deterministic test/echo agent
  - memory-curator-agent — reflects on sessions and proposes memory updates

Both agents are idempotent: re-seeding never duplicates them. New installs
attribute them to the space owner's ``user_id`` (no sentinel ``system`` user).

System agents are created WITH initial v1 AgentVersion records.
Agent.current_version_id is set to the v1 version. All executable config lives
in AgentVersion, not on the Agent record (except role_instruction which is
display/profile text and intentionally remains on Agent).
"""

from sqlalchemy.orm import Session

from ..models import Agent, AgentVersion
from ..schemas import DEFAULT_MODEL_CONFIG, DEFAULT_MEMORY_POLICY, DEFAULT_RUNTIME_POLICY


_BUILTIN_AGENTS: list[dict] = [
    {
        "id": "system.echo-agent",
        "name": "echo-agent",
        "description": "Deterministic echo adapter used for testing and capability demos.",
        "visibility": "space_shared",
        "role_instruction": "You are an echo agent. Repeat back what you receive.",
        # system_prompt lives on AgentVersion as the versioned execution field
        "system_prompt": "You are an echo agent. Repeat back what you receive.",
        # Execution config fields → AgentVersion
        "model_config_json": DEFAULT_MODEL_CONFIG,
        "memory_policy_json": {
            "readable_scopes": ["system", "user"],
            "writable_scopes": [],
            "readable_types": ["preference", "semantic"],
        },
        "capabilities_json": ["agent.echo"],
        "tool_permissions_json": {},
        "runtime_policy_json": {
            "risk_level": "low",
            "can_delegate": False,
            "max_delegation_depth": 0,
            "max_run_time_seconds": 30,
            "allowed_adapter_types": ["echo"],
            "default_adapter_type": "echo",
        },
    },
    {
        "id": "system.memory-curator-agent",
        "name": "memory-curator-agent",
        "description": "Reflects on sessions and proposes long-term memory updates for user approval.",
        "visibility": "space_shared",
        "role_instruction": (
            "You are the memory curator. Analyze the session and identify facts, preferences, "
            "and patterns worth preserving. Always propose; never write directly."
        ),
        # system_prompt lives on AgentVersion as the versioned execution field
        "system_prompt": (
            "You are the memory curator. Analyze the session and identify facts, preferences, "
            "and patterns worth preserving. Always propose; never write directly."
        ),
        # Execution config fields → AgentVersion
        "model_config_json": DEFAULT_MODEL_CONFIG,
        "memory_policy_json": {
            "readable_scopes": ["system", "user"],
            "writable_scopes": ["user"],
            "readable_types": ["preference", "semantic", "episodic", "procedural"],
            "requires_proposal": True,
        },
        "capabilities_json": ["memory.reflect"],
        "tool_permissions_json": {},
        "runtime_policy_json": {
            "can_delegate": False,
            "max_delegation_depth": 0,
            "max_run_time_seconds": 120,
            "allowed_adapter_types": ["echo", "claude_cli"],
        },
    },
]


def seed_builtin_agents(db: Session, space_id: str, owner_user_id: str) -> None:
    """
    Idempotently ensure all built-in system agents exist with v1 AgentVersion.

    ``owner_user_id`` must be a real ``users.id`` (typically the space owner);
    it is stored as ``Agent.owner_user_id`` / ``created_by_user_id``.

    - Creates the Agent record if it doesn't exist (idempotent)
    - Creates v1 AgentVersion if the agent has no current_version_id
    - Sets Agent.current_version_id to the v1 version
    - All executable config lives on AgentVersion; Agent.role_instruction is
      display/profile text only and is NOT used for runtime prompt construction
    """
    from .version_service import AgentVersionService

    version_svc = AgentVersionService(db)

    for spec in _BUILTIN_AGENTS:
        agent_id = spec["id"]

        # Create or get Agent
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            agent = Agent(
                id=agent_id,
                space_id=space_id,
                created_by_user_id=owner_user_id,
                name=spec["name"],
                description=spec["description"],
                visibility=spec["visibility"],
                role_instruction=spec["role_instruction"],
                status="active",
            )
            db.add(agent)
            db.flush()  # get agent.id

        # Create v1 AgentVersion if no current_version_id
        if not agent.current_version_id:
            from ..schemas import AgentVersionCreate
            version_data = AgentVersionCreate(
                system_prompt=spec["system_prompt"],
                model_config_json=spec["model_config_json"],
                memory_policy_json=spec["memory_policy_json"],
                capabilities_json=spec["capabilities_json"],
                tool_permissions_json=spec["tool_permissions_json"],
                runtime_policy_json=spec["runtime_policy_json"],
            )
            version = version_svc.create(
                agent_id=agent.id,
                space_id=space_id,
                data=version_data,
                label="v1",
            )
            agent.current_version_id = version.id

    db.commit()