from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.policy import Decision, PolicyDecision, RiskLevel
from app.runs import artifact_persistence as artifact_persistence_module
from app.runs import internal_api as runs_internal_api
from tests.support import factories


HEADER = {"x-agent-space-internal-token": "internal-token"}


class _FakePolicyPort:
    def enforce(self, req):
        context = getattr(req, "context", None) or {}
        if req.action == "runtime.execute" and context.get("agent_status") == "disabled":
            return PolicyDecision(
                decision=Decision.DENY,
                message="Agent is disabled",
                risk_level=RiskLevel.HIGH,
                reason_code="agent_disabled",
            )
        return PolicyDecision(
            decision=Decision.ALLOW,
            message="Allowed by test fake",
            risk_level=RiskLevel.LOW,
        )


def _install_policy_fake(monkeypatch) -> None:
    fake = _FakePolicyPort()
    monkeypatch.setattr(runs_internal_api, "get_policy_port", lambda _db: fake)
    monkeypatch.setattr(artifact_persistence_module, "get_policy_port", lambda _db: fake)


def test_internal_runs_context_ports_require_service_token(api_client, monkeypatch):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.get("/api/v1/internal/runs-context/ports")

    assert response.status_code == 401
    assert response.json().get("error") == "unauthorized"


def test_internal_runs_context_ports_manifest_declares_owner_auth_and_errors(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")

    response = api_client.get(
        "/api/v1/internal/runs-context/ports",
        headers=HEADER,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "python_runs_context_ports"
    ports = {item["operation"]: item for item in body["ports"]}
    assert set(ports) == {
        "policy.enforce",
        "context.prepare",
        "artifact.persist",
        "proposal.create",
        "workspace.prepare",
        "workspace.cleanup",
        "finalization.finalize",
    }
    assert ports["policy.enforce"]["owner"] == "policy"
    assert ports["policy.enforce"]["auth"] == "internal_service_token"
    assert "policy_denied" in ports["policy.enforce"]["error_codes"]
    assert ports["policy.enforce"]["implemented"] is True
    assert ports["context.prepare"]["implemented"] is False
    assert ports["context.prepare"]["writes"] == []
    assert ports["artifact.persist"]["implemented"] is True
    assert "artifacts" in ports["artifact.persist"]["writes"]
    assert ports["proposal.create"]["implemented"] is True
    assert "proposals" in ports["proposal.create"]["writes"]
    assert ports["workspace.prepare"]["implemented"] is True
    assert "runs.sandbox_path" in ports["workspace.prepare"]["writes"]
    assert ports["workspace.cleanup"]["implemented"] is True
    assert ports["finalization.finalize"]["implemented"] is True
    assert "run_finalizations" in ports["finalization.finalize"]["writes"]


def _allow_model_api_adapter(db, run, agent):
    """Point the run/version at the implemented model_api adapter."""
    version = next(v for v in agent.versions if v.id == agent.current_version_id)
    version.runtime_config_json = {
        **(version.runtime_config_json or {}),
        "adapter_type": "model_api",
    }
    version.runtime_policy_json = {
        **(version.runtime_policy_json or {}),
        "allowed_adapter_types": ["model_api"],
    }
    run.adapter_type = "model_api"
    db.commit()
    return version


def test_internal_runs_policy_enforce_allows_and_returns_resolved_config(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    _install_policy_fake(monkeypatch)
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db, space_id=space_id, owner_user_id=user.id, commit=False
    )
    run = factories.create_test_run(
        db, space_id=space_id, user_id=user.id, agent=agent, commit=False
    )
    _allow_model_api_adapter(db, run, agent)

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "policy.enforce",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {"adapter_type": "model_api"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "policy.enforce"
    assert body["owner"] == "policy"
    assert body["status"] == "succeeded"
    result = body["result_json"]
    assert result["decision"] == "allowed"
    assert result["adapter_type"] == "model_api"
    assert result["risk_level"]
    assert result["required_sandbox_level"]
    # The resolved adapter config is server-owned and includes the runtime
    # policy used for permission-bypass checks; TS never takes these from the
    # public request body.
    assert "adapter_config" in result
    assert result["adapter_config"]["runtime_policy_json"]["allowed_adapter_types"] == [
        "model_api"
    ]


def test_internal_runs_policy_enforce_denies_disabled_agent(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    _install_policy_fake(monkeypatch)
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db, space_id=space_id, owner_user_id=user.id, commit=False
    )
    run = factories.create_test_run(
        db, space_id=space_id, user_id=user.id, agent=agent, commit=False
    )
    _allow_model_api_adapter(db, run, agent)
    agent.status = "disabled"
    db.commit()

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "policy.enforce",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {"adapter_type": "model_api"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "policy_denied"
    assert "denied" in (body["message"] or "").lower()


def test_internal_runs_artifact_persist_runtime_output_creates_artifact(
    api_client,
    db,
    monkeypatch,
    tmp_path,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    _install_policy_fake(monkeypatch)
    monkeypatch.setattr(settings, "artifact_storage_root", str(tmp_path / "artifacts"))
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db, space_id=space_id, owner_user_id=user.id, commit=False
    )
    run = factories.create_test_run(
        db, space_id=space_id, user_id=user.id, agent=agent, commit=True
    )

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "artifact.persist",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {
                "artifact_type": "runtime_output",
                "title": "Run output (model_api)",
                "text": "hello from the adapter",
                "preview": False,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "artifact.persist"
    assert body["owner"] == "artifacts"
    assert body["status"] == "succeeded"
    artifact_id = body["result_json"]["artifact_id"]
    assert artifact_id

    from app.models import Artifact

    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).one()
    assert artifact.run_id == run.id
    assert artifact.artifact_type == "runtime_output"


def test_internal_runs_proposal_create_from_adapter_spec(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db, space_id=space_id, owner_user_id=user.id, commit=False
    )
    run = factories.create_test_run(
        db, space_id=space_id, user_id=user.id, agent=agent, commit=False
    )
    run.instructed_by_user_id = user.id
    db.commit()

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "proposal.create",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {
                "source": "adapter_output",
                "spec": {
                    "proposal_type": "memory_update",
                    "summary": "Remember the deploy command",
                    "payload": {
                        "proposed_title": "Deploy command",
                        "proposed_content": "Use ops/scripts/start.sh --dev",
                        "memory_type": "knowledge",
                        "target_scope": "space",
                        "target_namespace": "default",
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "proposal.create"
    assert body["owner"] == "proposals"
    assert body["status"] == "succeeded"
    proposal_id = body["result_json"]["proposal_id"]
    assert proposal_id

    from app.models import Proposal

    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).one()
    assert proposal.status == "pending"
    assert proposal.created_by_run_id == run.id


def test_internal_runs_proposal_create_rejects_invalid_spec(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db, space_id=space_id, owner_user_id=user.id, commit=False
    )
    run = factories.create_test_run(
        db, space_id=space_id, user_id=user.id, agent=agent, commit=False
    )
    run.instructed_by_user_id = user.id
    db.commit()

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "proposal.create",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {
                "source": "adapter_output",
                "spec": {"proposal_type": "unsupported_kind"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "proposal_create_failed"
    assert "unsupported" in (body["message"] or "")


def test_internal_runs_context_prepare_is_retired(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.prompt = "Summarize the current task"
    run.adapter_type = "model_api"
    db.commit()

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "context.prepare",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {"adapter_type": "model_api"},
        },
    )

    assert response.status_code == 410
    assert "context.prepare" in response.text
    assert "run_context_port_not_implemented" in response.text
    assert "TypeScript control plane" in response.text


def test_internal_runs_workspace_prepare_and_cleanup_plain_workdir(
    api_client,
    db,
    monkeypatch,
    tmp_path,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    monkeypatch.setattr(settings, "sandbox_root", str(tmp_path / "sandboxes"))
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.adapter_type = "codex_cli"
    run.required_sandbox_level = "worktree"
    run.workspace_id = None
    db.commit()

    prepare = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "workspace.prepare",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {"required_sandbox_level": "worktree"},
        },
    )

    assert prepare.status_code == 200
    result = prepare.json()["result_json"]
    sandbox_cwd = Path(result["sandbox_cwd"])
    assert result["cleanup_kind"] == "plain_workdir"
    assert sandbox_cwd.exists()
    db.refresh(run)
    assert run.sandbox_path == str(sandbox_cwd)

    cleanup = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "workspace.cleanup",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {
                "cleanup_kind": result["cleanup_kind"],
                "sandbox_cwd": result["sandbox_cwd"],
            },
        },
    )

    assert cleanup.status_code == 200
    assert not sandbox_cwd.exists()
    db.refresh(run)
    assert run.sandbox_path is None


def test_internal_runs_context_finalize_port_calls_python_finalizer(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=False,
    )
    run.status = "succeeded"
    run.started_at = datetime.now(UTC)
    run.ended_at = datetime.now(UTC)
    db.commit()

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "finalization.finalize",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "finalization.finalize"
    assert body["owner"] == "runs_finalization"
    assert body["status"] == "succeeded"
    assert body["result_json"]["run_finalization_id"]
    assert body["result_json"]["status"] in {"completed", "failed"}


def test_internal_runs_context_finalize_rejects_non_terminal_run(
    api_client,
    db,
    monkeypatch,
    cross_space_pair,
):
    monkeypatch.setattr(settings, "control_plane_internal_token", "internal-token")
    space_id = cross_space_pair["space_a_id"]
    user = cross_space_pair["user_a"]
    agent = factories.create_test_agent(
        db,
        space_id=space_id,
        owner_user_id=user.id,
        commit=False,
    )
    run = factories.create_test_run(
        db,
        space_id=space_id,
        user_id=user.id,
        agent=agent,
        commit=True,
    )

    response = api_client.post(
        "/api/v1/internal/runs-context/operations",
        headers=HEADER,
        json={
            "operation": "finalization.finalize",
            "run_id": run.id,
            "space_id": space_id,
            "payload_json": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["message"]["error"] == "run_not_terminal"
