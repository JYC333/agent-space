"""HTTP contract: run trace aggregates replay-safe run evidence in one response."""

from __future__ import annotations

import hashlib

from app.models import AgentVersion
from app.runs.events import RunEventService
from tests.support import factories


def _params(space_id: str, user_id: str) -> dict[str, str]:
    del user_id
    return {"space_id": space_id}


def test_run_trace_aggregates_failed_run_replay_spine(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    ua = cross_space_pair["user_a"]
    client = cross_space_pair["client_a"]

    provider = factories.create_test_model_provider(db, space_id=a, name="Trace Provider")
    adapter = factories.create_test_runtime_adapter(
        db,
        space_id=a,
        name="Trace Runtime",
        adapter_type="echo",
        provider_id=provider.id,
    )
    agent = factories.create_test_agent(db, space_id=a, owner_user_id=ua.id, name="Trace Agent")
    version = db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()
    version.model_provider_id = provider.id
    version.model_name = "trace-model"
    version.runtime_adapter_id = adapter.id
    version.system_prompt = "hidden trace prompt"

    parent = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent)
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent)
    run.parent_run_id = parent.id
    run.status = "failed"
    run.error_message = "adapter failed"
    run.model_provider_id = provider.id
    run.runtime_adapter_id = adapter.id
    run.context_snapshot.retrieval_trace_json = [{"stage": "test"}]
    run.context_snapshot.compiled_prefix_text = "raw compiled context must not be in trace"
    child = factories.create_test_run(db, space_id=a, user_id=ua.id, agent=agent)
    child.parent_run_id = run.id

    actor = factories.create_test_actor(db, actor_type="user", space_id=a, user_id=ua.id)
    step = factories.create_test_run_step(
        db,
        run=run,
        actor_id=actor.id,
        step_type="failed",
        status="failed",
        error_message="adapter failed",
    )
    artifact = factories.create_test_artifact(
        db,
        space_id=a,
        run_id=run.id,
        title="trace artifact",
        content="artifact body must not be in trace",
    )
    proposal = factories.create_test_proposal(
        db,
        space_id=a,
        run_id=run.id,
        proposal_type="follow_up_task",
        title="trace proposal",
        payload_json={"task_title": "follow up"},
    )
    RunEventService(db).append_event(
        run_id=run.id,
        space_id=a,
        event_type="adapter_completed",
        status="failed",
        step_id=step.id,
        runtime_adapter_id=adapter.id,
        artifact_id=artifact.id,
        proposal_id=proposal.id,
        error_message="adapter failed",
    )
    db.commit()

    r = client.get(f"/api/v1/runs/{run.id}/trace", params=_params(a, ua.id))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run"]["id"] == run.id
    assert body["run"]["status"] == "failed"
    assert body["agent"]["id"] == agent.id
    assert body["agent_version"]["id"] == version.id
    assert body["agent_version"]["system_prompt_present"] is True
    assert body["agent_version"]["system_prompt_sha256"] == hashlib.sha256(
        b"hidden trace prompt"
    ).hexdigest()
    assert body["runtime_adapter"]["id"] == adapter.id
    assert body["model_provider"]["id"] == provider.id
    assert body["context_snapshot"]["id"] == run.context_snapshot_id
    assert body["context_snapshot"]["has_compiled_prefix_text"] is True
    assert body["steps"][0]["id"] == step.id
    assert body["events"][0]["id"]
    assert body["artifacts"][0]["id"] == artifact.id
    assert "content" not in body["artifacts"][0]
    assert body["proposals"][0]["id"] == proposal.id
    assert body["parent"]["id"] == parent.id
    assert [c["id"] for c in body["children"]] == [child.id]
    assert "hidden trace prompt" not in r.text
    assert "raw compiled context" not in r.text
    assert "artifact body" not in r.text


def test_run_trace_is_space_scoped(api_client, db, cross_space_pair):
    a = cross_space_pair["space_a_id"]
    b = cross_space_pair["space_b_id"]
    ua = cross_space_pair["user_a"]
    ub = cross_space_pair["user_b"]
    run = factories.create_test_run(db, space_id=a, user_id=ua.id, commit=True)

    r = cross_space_pair["client_b"].get(
        f"/api/v1/runs/{run.id}/trace",
        params=_params(b, ub.id),
    )

    assert r.status_code == 404
    assert run.id not in r.text
