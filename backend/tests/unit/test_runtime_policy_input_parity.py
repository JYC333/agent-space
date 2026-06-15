from __future__ import annotations

from app.automation.policy_preflight import AutomationPolicyPreflightService
from app.models import AgentVersion
from app.runs.adapter_resolution import ResolvedRuntimeAdapter
from app.runs.policy_inputs import (
    CredentialPolicyMetadataError,
    build_runtime_execute_policy_request,
    build_runtime_use_credential_policy_request,
    resolve_runtime_credential_policy_metadata,
)
from app.runs.runtime_policy import compute_runtime_policy_decision
from app.runtimes.requirements import get_runtime_requirements
from tests.support import factories


def _version(db, run):
    return db.query(AgentVersion).filter(AgentVersion.id == run.agent_version_id).first()


def _set_adapter(version, adapter_type: str) -> None:
    version.runtime_config_json = {**(version.runtime_config_json or {}), "adapter_type": adapter_type}
    allowed = set((version.runtime_policy_json or {}).get("allowed_adapter_types") or [])
    allowed.add(adapter_type)
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "allowed_adapter_types": sorted(allowed),
    }


def _request_shape(req):
    return {
        "action": req.action,
        "actor_type": req.actor_type,
        "space_id": req.space_id,
        "resource_type": req.resource_type,
        "context": req.context,
        "metadata_json": req.metadata_json,
    }


def test_preflight_and_execution_runtime_execute_inputs_are_equivalent(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent)
    run.trigger_origin = "automation"
    version = _version(db, run)
    _set_adapter(version, "model_api")
    decision = compute_runtime_policy_decision(run=run, version=version)
    resolved = ResolvedRuntimeAdapter(adapter_type="model_api", merged_config={})

    execution_req = build_runtime_execute_policy_request(
        run, version, resolved, decision, agent.status
    )
    preflight_req = build_runtime_execute_policy_request(
        run, version, resolved, decision, agent.status
    )

    assert _request_shape(preflight_req) == _request_shape(execution_req)


def test_cli_runtime_does_not_build_model_provider_credential_policy_subject(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent)
    run.trigger_origin = "automation"
    version = _version(db, run)
    _set_adapter(version, "claude_code")
    provider = factories.create_test_model_provider(db, space_id=space_id, with_api_key=True)
    version.model_provider_id = provider.id
    decision = compute_runtime_policy_decision(run=run, version=version)
    resolved = ResolvedRuntimeAdapter(adapter_type="claude_code", merged_config={})
    subject = resolve_runtime_credential_policy_metadata(
        db, run, version, resolved, get_runtime_requirements("claude_code")
    )

    assert subject is None


def test_credential_metadata_resolver_does_not_expose_secret_ref(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent)
    version = _version(db, run)
    provider = factories.create_test_model_provider(db, space_id=space_id, with_api_key=True)
    version.model_provider_id = provider.id
    resolved = ResolvedRuntimeAdapter(adapter_type="claude_code", merged_config={})

    subject = resolve_runtime_credential_policy_metadata(
        db, run, version, resolved, get_runtime_requirements("claude_code")
    )

    assert subject is None


def test_cli_runtime_credential_metadata_ignores_model_provider_rows(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    other_space = cross_space_pair_db["space_b_id"]
    user_id = cross_space_pair_db["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    run = factories.create_test_run(db, space_id=space_id, user_id=user_id, agent=agent)
    version = _version(db, run)
    _set_adapter(version, "claude_code")
    provider = factories.create_test_model_provider(db, space_id=other_space, with_api_key=True)
    version.model_provider_id = provider.id
    resolved = ResolvedRuntimeAdapter(adapter_type="claude_code", merged_config={})

    subject = resolve_runtime_credential_policy_metadata(
        db, run, version, resolved, get_runtime_requirements("claude_code")
    )
    assert subject is None


def test_preflight_still_uses_context_for_decision_inputs_and_metadata_for_audit(db, cross_space_pair_db):
    space_id = cross_space_pair_db["space_a_id"]
    user_id = cross_space_pair_db["user_a"].id
    agent = factories.create_test_agent(db, space_id=space_id, owner_user_id=user_id)
    result = AutomationPolicyPreflightService(db).check(
        space_id=space_id,
        agent_id=agent.id,
        workspace_id="workspace-1",
        trigger_origin="automation",
    )

    runtime_execute = next(c for c in result.checks if c.action == "runtime.execute")
    context_render = next(c for c in result.checks if c.action == "context.render_for_runtime")
    assert runtime_execute.metadata_json["trigger_origin"] == "automation"
    assert context_render.metadata_json["workspace_id"] == "workspace-1"
