"""Invariant: published AgentVersion rows are immutable; execution config changes append a new version."""

from __future__ import annotations

from copy import deepcopy

from app.agents.agent_service import AgentService
from app.models import AgentVersion
from app.schemas import AgentUpdate
from tests.support import factories


def test_execution_config_update_appends_new_version_preserves_old(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, name="v-test", commit=False)
    db.flush()
    v1_id = agent.current_version_id
    v1_before = deepcopy(db.query(AgentVersion).filter(AgentVersion.id == v1_id).one().model_config_json)

    AgentService(db).update(
        agent.id,
        AgentUpdate(model_config_json={"model": "claude-test", "max_tokens": 1234}),
    )
    db.refresh(agent)
    v1_after = db.query(AgentVersion).filter(AgentVersion.id == v1_id).one()
    assert v1_after.model_config_json == v1_before
    assert agent.current_version_id != v1_id
    v2 = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    assert v2.model_config_json.get("model") == "claude-test"


def test_existing_run_keeps_original_agent_version_pointer(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    db.flush()
    v1_id = agent.current_version_id
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    db.flush()
    run_version_id = run.agent_version_id

    AgentService(db).update(agent.id, AgentUpdate(model_config_json={"model": "new", "max_tokens": 99}))
    db.refresh(run)
    db.refresh(agent)
    assert run.agent_version_id == run_version_id == v1_id
    assert agent.current_version_id != v1_id
