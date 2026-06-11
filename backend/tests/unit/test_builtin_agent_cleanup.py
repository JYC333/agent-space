"""Legacy built-in concrete agents are removed; only system templates remain.

Asserts the clean model after migrating `echo-agent` / `memory-curator-agent`
off the old per-space seeding path onto AgentTemplate (factory) + internal service.
"""

from __future__ import annotations

import importlib

import pytest

from app.models import Agent, AgentTemplate
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID

SPACE = PERSONAL_SPACE_ID
USER = DEFAULT_USER_ID


def test_legacy_agent_seeder_module_removed():
    """The old per-space concrete-agent seeder no longer exists."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.agents.seeder")


def test_on_space_created_seeds_no_concrete_agents(db):
    """Space creation seeds memories + execution planes — never concrete agents."""
    from app.spaces.hooks import on_space_created

    before = db.query(Agent).count()
    on_space_created(db, space_id=SPACE, seeded_by_user_id=USER)
    after = db.query(Agent).count()
    assert after == before  # no echo-agent / memory-curator-agent created

    # And specifically, no agent with a legacy hardcoded id exists.
    assert db.query(Agent).filter(Agent.id == "system.echo-agent").count() == 0
    assert db.query(Agent).filter(Agent.id == "system.memory-curator-agent").count() == 0


def test_bootstrap_seeds_templates_not_concrete_agents(db):
    """bootstrap_instance seeds system templates only — zero concrete agents."""
    from app.bootstrap import bootstrap_instance

    bootstrap_instance(db, user_id=USER, seed_execution_planes=False)

    # System templates exist...
    keys = {t.key for t in db.query(AgentTemplate).filter(AgentTemplate.scope == "system").all()}
    assert {"personal_assistant", "activity_reflector", "memory_reflector"} <= keys
    assert "general_chat" not in keys
    # ...but no built-in concrete agents were created.
    assert db.query(Agent).count() == 0


def test_intent_router_memory_reflect_has_no_legacy_agent():
    """/memory reflect routes to the internal service, not a concrete built-in agent."""
    from app.router import RouterService

    decision = RouterService().classify_intent(
        "/memory reflect",
        space_id=SPACE,
        user_id=USER,
    )
    assert decision is not None
    assert decision.capability_id == "memory.reflect"
    # No concrete agent is resolved, and certainly not the legacy key.
    assert decision.agent_id is None
    assert decision.agent_id != "system.memory-curator-agent"


def test_no_source_references_legacy_agent_keys():
    """No production code references the removed legacy concrete-agent ids."""
    import pathlib

    app_root = pathlib.Path(importlib.import_module("app.models").__file__).resolve().parent
    offenders = []
    for path in app_root.rglob("*.py"):
        text = path.read_text()
        if "system.echo-agent" in text or "system.memory-curator-agent" in text:
            offenders.append(str(path.relative_to(app_root)))
    assert offenders == [], f"legacy agent ids still referenced in: {offenders}"
