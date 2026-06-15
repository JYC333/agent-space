"""Unit tests for RunOut resolved_model enrichment."""

from __future__ import annotations

from app.models import AgentVersion
from app.runs.read_model import build_run_resolved_model, run_to_out
from app.runtimes.adapter_metadata import get_adapter_model_config_metadata
from tests.support import factories


def test_adapter_metadata_capability_not_applicable():
    meta = get_adapter_model_config_metadata("capability")
    assert meta.uses_model_config is False
    assert meta.model_config_behavior == "not_applicable"
    assert meta.model_config_note == ""


def test_build_resolved_model_agent_default(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mp = factories.create_test_model_provider(
        db,
        space_id=a,
        name="Run Prov",
        with_api_key=True,
        default_model="gpt-test",
        commit=False,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    version.model_provider_id = mp.id
    version.model_name = "gpt-test"
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.model_provider_id = mp.id
    run.model_override_json = {"model": "gpt-test", "source": "agent_default"}
    run.adapter_type = "capability"
    db.flush()

    resolved = build_run_resolved_model(db, run)
    assert resolved.provider_id == mp.id
    assert resolved.provider_name == "Run Prov"
    assert resolved.model == "gpt-test"
    assert resolved.source == "agent_default"
    assert resolved.used_by_adapter is False
    assert resolved.adapter_model_support == "not_applicable"
    assert resolved.disclosure_note is None


def test_build_resolved_model_unsupported_adapter(db, cross_space_pair_db):
    """A run with an unsupported adapter_type should surface adapter_model_support=unsupported."""
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    mp = factories.create_test_model_provider(
        db, space_id=a, with_api_key=True, commit=False
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=False)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=False)
    run.model_provider_id = mp.id
    run.model_override_json = {"model": "some-model", "source": "request"}
    run.adapter_type = "unknown_adapter_for_test"
    db.flush()

    resolved = build_run_resolved_model(db, run)
    assert resolved.used_by_adapter is False
    assert resolved.adapter_model_support == "unsupported"
    assert resolved.source == "request"


def test_run_to_out_includes_resolved_model(db, cross_space_pair_db):
    a = cross_space_pair_db["space_a_id"]
    ua = cross_space_pair_db["user_a"]
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, commit=True)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent, commit=True)
    out = run_to_out(db, run)
    assert out.resolved_model is not None
    assert out.resolved_model.source == "none"
