from __future__ import annotations
"""
Built-in agent seeder.

Seeds the two system agents that every deployment starts with:
  - echo-agent          — deterministic test/echo agent
  - memory-curator-agent — reflects on sessions and proposes memory updates

Both agents are idempotent: re-seeding never duplicates them. They live in
every space with created_by_user_id="system" and are never soft-deleted by the seeder.
"""

from sqlalchemy.orm import Session

from ..models import Agent
from ..schemas import DEFAULT_MODEL_CONFIG, DEFAULT_RUNTIME_POLICY


_BUILTIN_AGENTS: list[dict] = [
    {
        "id": "system.echo-agent",
        "name": "echo-agent",
        "description": "Deterministic echo adapter used for testing and capability demos.",
        "created_by_user_id": "system",
        "visibility": "space_shared",
        "role_instruction": "You are an echo agent. Repeat back what you receive.",
        "model_config_json": DEFAULT_MODEL_CONFIG,
        "memory_policy_json": {
            "readable_scopes": ["system", "user"],
            "writable_scopes": [],
            "readable_types": ["preference", "semantic"],
        },
        "capabilities_json": ["agent.echo"],
        "tool_policy_json": [],
        "runtime_policy_json": {
            "can_delegate": False,
            "max_delegation_depth": 0,
            "max_run_time_seconds": 30,
            "allowed_adapter_types": ["echo"],
        },
    },
    {
        "id": "system.memory-curator-agent",
        "name": "memory-curator-agent",
        "description": "Reflects on sessions and proposes long-term memory updates for user approval.",
        "created_by_user_id": "system",
        "visibility": "space_shared",
        "role_instruction": (
            "You are the memory curator. Analyze the session and identify facts, preferences, "
            "and patterns worth preserving. Always propose; never write directly."
        ),
        "model_config_json": DEFAULT_MODEL_CONFIG,
        "memory_policy_json": {
            "readable_scopes": ["system", "user"],
            "writable_scopes": ["user"],
            "readable_types": ["preference", "semantic", "episodic", "procedural"],
            "requires_proposal": True,
        },
        "capabilities_json": ["memory.reflect"],
        "tool_policy_json": [],
        "runtime_policy_json": {
            "can_delegate": False,
            "max_delegation_depth": 0,
            "max_run_time_seconds": 120,
            "allowed_adapter_types": ["echo", "claude_cli"],
        },
    },
]


def seed_builtin_agents(db: Session, space_id: str = "personal") -> None:
    """Idempotently ensure all built-in system agents exist in the given space."""
    for spec in _BUILTIN_AGENTS:
        agent_id = spec["id"]
        existing = db.query(Agent).filter(Agent.id == agent_id).first()
        if existing:
            continue
        agent = Agent(
            id=agent_id,
            space_id=space_id,
            created_by_user_id=spec["created_by_user_id"],
            name=spec["name"],
            description=spec["description"],
            visibility=spec["visibility"],
            role_instruction=spec["role_instruction"],
            model_config_json=spec["model_config_json"],
            memory_policy_json=spec["memory_policy_json"],
            capabilities_json=spec["capabilities_json"],
            tool_policy_json=spec["tool_policy_json"],
            runtime_policy_json=spec["runtime_policy_json"],
            status="active",
        )
        db.add(agent)
    db.commit()
