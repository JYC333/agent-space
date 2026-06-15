"""Invariant: model providers stay separate from runtime adapter type routing."""

from __future__ import annotations

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models import AgentVersion
from app.runs.adapter_resolution import AdapterResolutionError, resolve_runtime_adapter
from tests.support import factories


def test_model_provider_allowlist_rejects_disallowed_version_provider(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mp = factories.create_test_model_provider(db, space_id=a, commit=False)
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    v.model_provider_id = mp.id
    pol = dict(v.runtime_policy_json or {})
    pol["allowed_model_providers"] = ["some-other-id"]
    v.runtime_policy_json = pol
    flag_modified(v, "runtime_policy_json")
    db.flush()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    db.flush()
    with pytest.raises(AdapterResolutionError) as ei:
        resolve_runtime_adapter(db, run=run, version=v, policy=pol)
    assert "model_provider" in ei.value.message.lower()
