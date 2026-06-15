"""AgentService.create resolves adapter_type into the v1 runtime policy (merge, not replace)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.agent_service import AgentService
from app.models import AgentVersion
from app.schemas import AgentCreate
from tests.support import factories


def test_model_api_adapter_merges_into_runtime_policy(db, test_space, test_user):
    provider = factories.create_test_model_provider(
        db, space_id=test_space.id, provider_type="anthropic",
        with_api_key=True, default_model="claude-3-5-sonnet-latest", enabled=True, commit=True,
    )
    agent = AgentService(db).create(AgentCreate(
        name="api-agent", space_id=test_space.id, created_by_user_id=test_user.id,
        adapter_type="model_api",
        default_model_provider_id=provider.id, default_model="claude-3-5-sonnet-latest",
    ))
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    rp = version.runtime_policy_json
    assert rp["default_adapter_type"] == "model_api"
    assert "model_api" in rp["allowed_adapter_types"]
    # Other default policy fields are preserved (merge, not replace).
    assert "risk_level" in rp and "max_run_time_seconds" in rp
    assert version.model_provider_id == provider.id


def test_model_api_adapter_requires_provider(db, test_space, test_user):
    with pytest.raises(HTTPException) as exc:
        AgentService(db).create(AgentCreate(
            name="no-provider", space_id=test_space.id, created_by_user_id=test_user.id,
            adapter_type="model_api",
        ))
    assert exc.value.status_code == 400


def test_unknown_adapter_type_rejected(db, test_space, test_user):
    with pytest.raises(HTTPException) as exc:
        AgentService(db).create(AgentCreate(
            name="bad-adapter", space_id=test_space.id, created_by_user_id=test_user.id,
            adapter_type="totally_unknown",
        ))
    assert exc.value.status_code == 400


def test_no_adapter_type_uses_default_policy(db, test_space, test_user):
    agent = AgentService(db).create(AgentCreate(
        name="default-agent", space_id=test_space.id, created_by_user_id=test_user.id,
    ))
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    assert version.runtime_policy_json["default_adapter_type"] == "model_api"


def test_system_prompt_is_stored_on_version(db, test_space, test_user):
    """The agent's system prompt reaches AgentVersion.system_prompt (used at run time)."""
    agent = AgentService(db).create(AgentCreate(
        name="identity-agent", space_id=test_space.id, created_by_user_id=test_user.id,
        system_prompt="You are a concise daily summarizer.",
    ))
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    assert version.system_prompt == "You are a concise daily summarizer."
