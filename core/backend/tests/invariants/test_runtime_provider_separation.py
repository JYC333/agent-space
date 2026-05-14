"""Invariant: ModelProvider rows and RuntimeAdapter rows evolve independently."""

from __future__ import annotations

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models import AgentVersion, ModelProvider, RuntimeAdapter
from app.runs.adapter_resolution import AdapterResolutionError, resolve_runtime_adapter
from app.schemas import CLIAdapterConfigCreate, CLIAdapterConfigUpdate
from app.cli_adapters.service import CLIAdapterService
from tests.support import factories


def test_provider_config_update_does_not_mutate_runtime_adapter_row(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mp = factories.create_test_model_provider(db, space_id=a, commit=False)
    mp.config_json = {"api": "v1"}
    flag_modified(mp, "config_json")
    ra = factories.create_test_runtime_adapter(
        db, space_id=a, provider_id=mp.id, adapter_type="echo", commit=False
    )
    ra.config_json = {"shell": "zsh"}
    flag_modified(ra, "config_json")
    db.flush()
    mp_id, ra_id = mp.id, ra.id

    mp.default_model = "gpt-other"
    mp.config_json = {**(mp.config_json or {}), "api": "v2"}
    flag_modified(mp, "config_json")
    db.flush()

    ra2 = db.query(RuntimeAdapter).filter_by(id=ra_id).one()
    assert ra2.config_json == {"shell": "zsh"}
    assert ra2.provider_id == mp_id


def test_runtime_adapter_update_does_not_mutate_model_provider(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    mp = factories.create_test_model_provider(db, space_id=a, commit=False)
    mp.config_json = {"stable": True}
    flag_modified(mp, "config_json")
    ra = factories.create_test_runtime_adapter(db, space_id=a, provider_id=mp.id, commit=False)
    db.flush()
    ra.config_json = {"note": "a"}
    flag_modified(ra, "config_json")
    db.flush()

    svc = CLIAdapterService(db)
    svc.update(
        ra.id,
        a,
        CLIAdapterConfigUpdate(notes="changed-only-adapter", display_name="new-name"),
    )
    mp2 = db.query(ModelProvider).filter_by(id=mp.id).one()
    assert mp2.config_json == {"stable": True}


def test_disabled_runtime_adapter_cannot_resolve_for_execution(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    v = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    bad = factories.create_test_runtime_adapter(
        db, space_id=a, adapter_type="echo", enabled=False, commit=False,
    )
    v.runtime_adapter_id = bad.id
    db.flush()

    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    db.flush()
    policy = dict(v.runtime_policy_json or {})
    with pytest.raises(AdapterResolutionError) as ei:
        resolve_runtime_adapter(db, run=run, version=v, policy=policy)
    assert ei.value.error_code == "adapter_disabled"


def test_model_provider_allowlist_rejects_disallowed_version_provider(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
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


def test_cli_adapter_create_is_distinct_from_model_provider(db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    mp = factories.create_test_model_provider(db, space_id=a, name="p1", commit=False)
    db.flush()
    ra = CLIAdapterService(db).create(
        CLIAdapterConfigCreate(adapter_id="echo", display_name="Echo cfg", enabled=True),
        space_id=a,
    )
    assert ra.id != mp.id
    assert ra.space_id == mp.space_id
