"""
Canonical model surface checks: removed execution hooks, naming,
and deferred ORM names (deferred features use explicit HTTP gates).
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect

import app.models as models
from app.models import Agent, Job

pytestmark = pytest.mark.canonical

_WS = "".join(("Workspace", "Session"))
_SS = "".join(("Session", "Summary"))

_REMOVED_PLACEHOLDER_NAMES = frozenset(
    {
        "WorkspaceMembership",
        "WorkspaceSpaceAccess",
        _SS,
        "Capability",
        "ToolCall",
        "UsageEvent",
        "Approval",
        "ApprovalEvent",
        "ProposalArtifact",
        "ContextAttachment",
        "RunMetrics",
        "UserFeedback",
        "FailureEvent",
        "ValidationResult",
        "CapabilityVersion",
        "CapabilityTest",
        "CredentialAccessLog",
        "CliCredentialEvent",
        "ApiKey",
        "DeploymentJob",
        _WS,
    }
)


def test_models_module_has_no_removed_phantom_marker():
    phantom = "".join(("_Legacy", "Only"))
    assert not hasattr(models, phantom)


def test_models_does_not_export_removed_row_placeholders():
    for name in _REMOVED_PLACEHOLDER_NAMES:
        assert not hasattr(models, name), f"unexpected deferred export: {name!r}"


def test_importing_main_app_succeeds():
    from app.main import app  # noqa: F401 — startup import smoke

    assert app.title


def test_runner_module_has_no_execute_pending_run():
    import app.agents.runner as runner

    assert not hasattr(runner, "execute_pending_run")


def test_agents_orm_has_no_model_config_json_column():
    """Executable config belongs on AgentVersion, not Agent."""
    cols = {c.key for c in sa_inspect(Agent).mapper.column_attrs}
    assert "model_config_json" not in cols
    assert "runtime_policy_json" not in cols


def test_jobs_table_mapped_for_infrastructure_queue():
    assert Job.__tablename__ == "jobs"


def test_handle_agent_run_handler_registered():
    from app.jobs.handlers import get_handler

    assert get_handler("agent_run") is not None


def test_run_status_includes_queued():
    from app.models import Run

    ck = next(
        c for c in Run.__table__.constraints if getattr(c, "name", None) == "ck_runs_status"
    )
    sql = str(ck.sqltext).lower()
    assert "queued" in sql


def test_context_builder_accepts_session_id_without_session_summary_table(db):
    from app.memory.context_builder import ContextBuilder
    from tests.conftest import SPACE, USER

    builder = ContextBuilder(db)
    pkg = builder.build(space_id=SPACE, user_id=USER, session_id="sess_01")
    assert pkg.recent_session_summary == []


def test_deployment_jobs_explicit_unpersisted_behavior(client):
    from tests.conftest import SPACE, USER

    qs = f"space_id={SPACE}&user_id={USER}"
    r = client.post(f"/api/v1/deployments/jobs?{qs}", json={"job_type": "health_check"})
    assert r.status_code == 501
    r2 = client.get(f"/api/v1/deployments/jobs?{qs}")
    assert r2.status_code == 200
    assert r2.json() == []
    r3 = client.get(f"/api/v1/deployments/jobs/some-id?{qs}")
    assert r3.status_code == 501


def test_workspace_console_sessions_explicit_unpersisted_behavior(client):
    from tests.conftest import SPACE, USER

    qs = f"space_id={SPACE}&user_id={USER}"
    r = client.get(f"/api/v1/workspace-console/sessions?{qs}")
    assert r.status_code == 200
    assert r.json() == {"items": []}
    r2 = client.post(
        f"/api/v1/workspace-console/sessions?{qs}",
        json={
            "prompt": "hi",
            "runtime_adapter": "claude_code",
        },
    )
    assert r2.status_code == 501


def test_auth_api_keys_list_returns_501(client):
    from tests.conftest import SPACE, USER

    qs = f"space_id={SPACE}&user_id={USER}"
    r = client.get(f"/api/v1/auth/keys?{qs}")
    assert r.status_code == 501


def test_bearer_ask_token_triggers_api_key_storage_not_implemented(client):
    from tests.conftest import SPACE, USER

    qs = f"space_id={SPACE}&user_id={USER}"
    raw = "ask_" + "ab" * 32
    r = client.get(f"/api/v1/auth/keys?{qs}", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 501
