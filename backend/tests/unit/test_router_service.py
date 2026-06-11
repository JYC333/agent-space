from __future__ import annotations

import pytest

from app.router import (
    AdapterResolutionError,
    RoutingDecision,
    RouterService,
    TaskClassification,
)
from tests.support import factories


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        (TaskClassification(task_type="summarize"), False),
        (TaskClassification(task_type="code_modify"), True),
        (TaskClassification(task_type="generic", requires_filesystem=True), True),
        (TaskClassification(task_type="generic", requires_terminal=True), True),
        (TaskClassification(task_type="generic", requires_git=True), True),
        (TaskClassification(task_type="generic", requires_long_reasoning=True), True),
    ],
)
def test_task_classification_needs_cli_matches_legacy_behavior(classification, expected):
    assert classification.needs_cli is expected


def test_route_task_preserves_requested_adapter_without_downgrade():
    decision = RouterService().route_task(
        requested_adapter="claude_code",
        task_type="summarize",
        risk_level="low",
        requires_filesystem=False,
        requires_terminal=False,
        requires_git=False,
        requires_long_reasoning=False,
    )

    assert decision.adapter_type == "claude_code"
    assert decision.needs_cli is False


def test_router_service_classifies_slash_commands():
    service = RouterService()

    cases = [
        (
            "/memory reflect now",
            RoutingDecision(
                capability_id="memory.reflect",
                space_id="space-1",
                workspace_id="workspace-1",
                action="memory.reflect",
            ),
        ),
        (
            "/agent run planner with notes",
            RoutingDecision(
                agent_id="planner",
                space_id="space-1",
                workspace_id="workspace-1",
                action="runtime.execute",
                params={"extra": ["with", "notes"]},
            ),
        ),
        (
            "/capabilities list",
            RoutingDecision(space_id="space-1", action="capabilities.list"),
        ),
        ("plain chat message", None),
        ("/unknown command", None),
    ]
    for message, expected in cases:
        assert service.classify_intent(
            message,
            space_id="space-1",
            user_id="user-1",
            workspace_id="workspace-1",
        ) == expected


def _version(db, agent):
    from app.models import AgentVersion

    return db.query(AgentVersion).filter(AgentVersion.id == agent.current_version_id).one()


def test_runtime_adapter_resolution_priority_matches_execution_order(db, test_space, test_user):
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
    )
    version = _version(db, agent)
    version.runtime_config_json = {"adapter_type": "model_api"}
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "default_adapter_type": "codex_cli",
    }
    run_row = factories.create_test_runtime_adapter(
        db,
        space_id=test_space.id,
        adapter_type="echo",
    )
    version_row = factories.create_test_runtime_adapter(
        db,
        space_id=test_space.id,
        adapter_type="capability",
    )
    version.runtime_adapter_id = version_row.id
    run = factories.create_test_run(
        db,
        space_id=test_space.id,
        user_id=test_user.id,
        agent=agent,
    )
    run.runtime_adapter_id = run_row.id
    run.adapter_type = "claude_code"
    db.flush()

    service = RouterService(db)
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "echo"
    assert resolved.runtime_adapter_row.id == run_row.id

    run.runtime_adapter_id = None
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "capability"
    assert resolved.runtime_adapter_row.id == version_row.id


def test_run_create_adapter_preview_uses_execution_priority(db, test_space, test_user):
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
    )
    version = _version(db, agent)
    version.runtime_config_json = {"adapter_type": "model_api"}
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "default_adapter_type": "codex_cli",
    }
    run_row = factories.create_test_runtime_adapter(
        db,
        space_id=test_space.id,
        adapter_type="echo",
    )
    version_row = factories.create_test_runtime_adapter(
        db,
        space_id=test_space.id,
        adapter_type="capability",
    )
    version.runtime_adapter_id = version_row.id
    db.flush()

    service = RouterService(db)
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        runtime_adapter_id=run_row.id,
        requested_adapter_type="claude_code",
    ) == "echo"
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        requested_adapter_type="claude_code",
    ) == "capability"

    version.runtime_adapter_id = None
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        requested_adapter_type="claude_code",
    ) == "claude_code"
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        requested_adapter_type=None,
    ) == "model_api"

    version.runtime_config_json = {}
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        requested_adapter_type=None,
    ) == "codex_cli"

    version.runtime_policy_json = {}
    assert service.preview_run_adapter_type(
        space_id=test_space.id,
        version=version,
        requested_adapter_type=None,
    ) == "echo"


def test_runtime_adapter_resolution_falls_back_through_run_config_policy_echo(
    db,
    test_space,
    test_user,
):
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
    )
    version = _version(db, agent)
    run = factories.create_test_run(
        db,
        space_id=test_space.id,
        user_id=test_user.id,
        agent=agent,
    )
    service = RouterService(db)

    version.runtime_config_json = {"adapter_type": "capability"}
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "default_adapter_type": "codex_cli",
    }
    run.adapter_type = "echo"
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "echo"

    run.adapter_type = None
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "capability"

    version.runtime_config_json = {}
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "codex_cli"

    version.runtime_policy_json = {}
    resolved = service.resolve_runtime_adapter(
        run=run,
        version=version,
        policy=version.runtime_policy_json,
    )
    assert resolved.adapter_type == "echo"


def test_runtime_adapter_resolution_reports_missing_version_adapter_row(
    db,
    test_space,
    test_user,
):
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
    )
    version = _version(db, agent)
    other_space = factories.create_test_space(
        db,
        space_id="router-service-other-space",
        space_type="team",
    )
    other_adapter = factories.create_test_runtime_adapter(
        db,
        space_id=other_space.id,
        adapter_type="echo",
    )
    version.runtime_adapter_id = other_adapter.id
    run = factories.create_test_run(
        db,
        space_id=test_space.id,
        user_id=test_user.id,
        agent=agent,
    )
    db.flush()

    with pytest.raises(AdapterResolutionError) as exc:
        RouterService(db).resolve_runtime_adapter(
            run=run,
            version=version,
            policy=version.runtime_policy_json,
        )

    assert exc.value.error_code == "adapter_not_configured"
    assert "AgentVersion.runtime_adapter_id" in exc.value.message


def test_runtime_adapter_provider_id_subject_to_allowlist(db, test_space, test_user):
    """A provider pinned on the resolved RuntimeAdapter row is checked against
    runtime_policy_json.allowed_model_providers (run/version carry no provider)."""
    from app.runs.adapter_resolution import resolve_runtime_adapter

    agent = factories.create_test_agent(
        db, space_id=test_space.id, owner_user_id=test_user.id
    )
    version = _version(db, agent)
    provider = factories.create_test_model_provider(db, space_id=test_space.id)
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "allowed_model_providers": ["some-other-allowed-mp"],
    }
    adapter_row = factories.create_test_runtime_adapter(
        db,
        space_id=test_space.id,
        adapter_type="model_api",
        provider_id=provider.id,
    )
    run = factories.create_test_run(
        db, space_id=test_space.id, user_id=test_user.id, agent=agent
    )
    run.runtime_adapter_id = adapter_row.id
    db.flush()

    with pytest.raises(AdapterResolutionError) as exc:
        resolve_runtime_adapter(db, run=run, version=version, policy=version.runtime_policy_json)
    assert exc.value.error_code == "model_provider_disallowed"


def test_preflight_and_automation_resolution_keep_their_distinct_fallbacks(
    db,
    test_space,
    test_user,
):
    agent = factories.create_test_agent(
        db,
        space_id=test_space.id,
        owner_user_id=test_user.id,
    )
    version = _version(db, agent)
    version.runtime_config_json = {}
    version.runtime_policy_json = {}
    db.flush()

    service = RouterService(db)
    preflight = service.resolve_preflight_adapter(
        space_id=test_space.id,
        version=version,
        requested_adapter_type=None,
    )
    automation = service.resolve_automation_adapter(version=version, policy={})

    assert preflight.adapter_type == "echo"
    assert automation.adapter_type == ""
