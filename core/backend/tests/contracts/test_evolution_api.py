"""HTTP contract: Evolution product module read APIs and proposal-first runs."""

from __future__ import annotations

from app.auth.session import SESSION_COOKIE, UserSessionService
from app.evolution.constants import DEFAULT_CAPTURE_CAPABILITY_KEY
from app.main import app as _app
from app.models import CapabilityOverlay, CapabilityVersion, Proposal
from app.providers.invocation import CompletionResult
from starlette.testclient import TestClient
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _params() -> dict[str, str]:
    return {"space_id": PERSONAL_SPACE_ID}


def _authed_client(db):
    _, raw = UserSessionService(db).create(DEFAULT_USER_ID)
    return TestClient(_app, cookies={SESSION_COOKIE: raw}, raise_server_exceptions=True)


def test_evolution_summary_targets_and_empty_lists(db):
    client = _authed_client(db)
    summary = client.get("/api/v1/evolution/summary", params=_params())
    assert summary.status_code == 200
    assert summary.json() == {
        "active_targets": 1,
        "signals_collected": 0,
        "pending_proposals": 0,
        "recent_runs": 0,
    }

    targets = client.get("/api/v1/evolution/targets", params=_params())
    assert targets.status_code == 200
    rows = targets.json()
    assert len(rows) == 1
    target = rows[0]
    assert target["target_name"] == "Capture Memory Extraction"
    assert target["target_type"] == "prompt"
    assert target["risk_level"] == "medium"
    assert target["recent_signal_count"] == 0
    assert target["last_run_at"] is None

    for path in ("signals", "runs", "proposals"):
        r = client.get(f"/api/v1/evolution/{path}", params=_params())
        assert r.status_code == 200
        assert r.json() == []

    validation = client.get("/api/v1/evolution/validation", params=_params())
    assert validation.status_code == 200
    metric_ids = {row["metric_id"] for row in validation.json()}
    assert "memory_candidate_reject_rate" in metric_ids


def test_create_user_configured_evolution_target_with_validation(db):
    client = _authed_client(db)
    created = client.post(
        "/api/v1/evolution/targets",
        params=_params(),
        json={
            "target_type": "prompt",
            "target_ref_type": "capability",
            "target_ref_id": "custom-capture",
            "capability_key": "custom-capture",
            "target_name": "Custom Capture",
            "purpose": "User configured target.",
            "metadata_json": {
                "validation": {
                    "window": "7d",
                    "metrics": [{
                        "id": "custom_error_count",
                        "label": "Custom error count",
                        "evaluator": "count_signals",
                        "source": "signals",
                        "signal_type": "run_validation_failed",
                        "goal": {"direction": "decrease", "threshold": 0},
                    }],
                },
            },
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["space_id"] == PERSONAL_SPACE_ID
    assert body["target_name"] == "Custom Capture"
    assert body["metadata_json"]["validation"]["metrics"][0]["evaluator"] == "count_signals"
    assert body["metadata_json"]["origin"]["type"] == "clone"


def test_clone_target_does_not_hide_system_default_or_get_used_as_override(db):
    client = _authed_client(db)
    system_target = client.get("/api/v1/evolution/targets", params=_params()).json()[0]
    assert system_target["space_id"] is None

    cloned = client.post(
        "/api/v1/evolution/targets",
        params=_params(),
        json={
            "target_type": system_target["target_type"],
            "target_ref_type": system_target["target_ref_type"],
            "target_ref_id": system_target["target_ref_id"],
            "capability_key": system_target["capability_key"],
            "target_name": "Capture Memory Extraction copy",
            "purpose": "Independent validation experiment.",
            "metadata_json": {
                "origin": {
                    "type": "clone",
                    "source_target_id": system_target["id"],
                },
            },
        },
    )
    assert cloned.status_code == 201
    clone_body = cloned.json()
    assert clone_body["space_id"] == PERSONAL_SPACE_ID
    assert clone_body["id"] != system_target["id"]
    assert clone_body["metadata_json"]["origin"]["type"] == "clone"

    rows = client.get("/api/v1/evolution/targets", params=_params()).json()
    assert {row["id"] for row in rows} == {system_target["id"], clone_body["id"]}

    updated = client.patch(
        f"/api/v1/evolution/targets/{system_target['id']}",
        params=_params(),
        json={"enabled": False, "target_name": "Disabled Capture"},
    )
    assert updated.status_code == 200
    override = updated.json()
    assert override["id"] != clone_body["id"]
    assert override["metadata_json"]["origin"] == {
        "type": "system_override",
        "source_target_id": system_target["id"],
    }

    rows = client.get("/api/v1/evolution/targets", params=_params()).json()
    assert {row["id"] for row in rows} == {clone_body["id"], override["id"]}
    assert all(row["id"] != system_target["id"] for row in rows)


def test_system_default_target_update_creates_space_override(db):
    client = _authed_client(db)
    target = client.get("/api/v1/evolution/targets", params=_params()).json()[0]
    assert target["space_id"] is None
    assert target["enabled"] is True

    updated = client.patch(
        f"/api/v1/evolution/targets/{target['id']}",
        params=_params(),
        json={"enabled": False, "target_name": "Disabled Capture"},
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["space_id"] == PERSONAL_SPACE_ID
    assert body["enabled"] is False
    assert body["target_name"] == "Disabled Capture"
    assert body["metadata_json"]["origin"] == {
        "type": "system_override",
        "source_target_id": target["id"],
    }
    assert body["capability_key"] == DEFAULT_CAPTURE_CAPABILITY_KEY

    rows = client.get("/api/v1/evolution/targets", params=_params()).json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]
    assert rows[0]["space_id"] == PERSONAL_SPACE_ID
    assert rows[0]["enabled"] is False


def test_evolution_run_requires_signal(db):
    client = _authed_client(db)
    target = client.get("/api/v1/evolution/targets", params=_params()).json()[0]

    run = client.post(
        f"/api/v1/evolution/targets/{target['id']}/run",
        params=_params(),
        json={"engine": "llm_prompt_review"},
    )
    assert run.status_code == 422
    assert "requires at least one signal" in run.json()["detail"]
    assert db.query(Proposal).count() == 0


def test_evolution_run_requires_default_model_provider(db):
    client = _authed_client(db)
    target = client.get("/api/v1/evolution/targets", params=_params()).json()[0]
    signal = client.post(
        f"/api/v1/evolution/targets/{target['id']}/signals",
        params=_params(),
        json={
            "signal_type": "exploration_misclassified_as_decision",
            "source_type": "proposal",
            "source_id": "proposal-test",
            "severity": "medium",
            "summary": "Exploration was saved as a stable decision.",
            "payload_json": {},
        },
    )
    assert signal.status_code == 201

    run = client.post(
        f"/api/v1/evolution/targets/{target['id']}/run",
        params=_params(),
        json={"engine": "llm_prompt_review"},
    )
    assert run.status_code == 422
    assert "No default provider configured" in run.json()["detail"]
    assert db.query(Proposal).count() == 0


def test_evolution_run_creates_artifacts_and_pending_proposal_only(db, monkeypatch):
    factories.create_test_model_provider(
        db,
        space_id=PERSONAL_SPACE_ID,
        with_api_key=True,
        is_default=True,
        default_model="gpt-test",
    )
    monkeypatch.setattr(
        "app.evolution.engines.complete_text",
        lambda *args, **kwargs: CompletionResult(
            text=(
                '{"report":{"summary":"Prompt should distinguish exploration from decisions.",'
                '"signal_analysis":["Exploration was saved as a stable decision."],'
                '"risk_notes":["Review the wording before approval."],'
                '"expected_improvement":"Fewer false stable memories."},'
                '"prompt_revision":{"revision_format":"prompt_revision.v1",'
                '"capability_key":"capture-memory-extraction",'
                '"prompt":"Revised prompt: treat exploratory notes as Activity evidence unless the user explicitly accepts a memory proposal.",'
                '"change_summary":["Clarified exploration handling."],'
                '"evidence_signal_ids":[]}}'
            ),
            model="gpt-test",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        ),
    )
    client = _authed_client(db)
    target = client.get("/api/v1/evolution/targets", params=_params()).json()[0]
    signal = client.post(
        f"/api/v1/evolution/targets/{target['id']}/signals",
        params=_params(),
        json={
            "signal_type": "exploration_misclassified_as_decision",
            "source_type": "proposal",
            "source_id": "proposal-test",
            "severity": "medium",
            "summary": "Exploration was saved as a stable decision.",
            "payload_json": {},
        },
    )
    assert signal.status_code == 201
    assert signal.json()["target_name"] == "Capture Memory Extraction"

    run = client.post(
        f"/api/v1/evolution/targets/{target['id']}/run",
        params=_params(),
        json={"engine": "llm_prompt_review"},
    )
    assert run.status_code == 201
    body = run.json()
    assert body["run_status"] == "succeeded"
    assert body["proposal_type"] == "prompt_update"
    assert "revision_artifact_id" in body

    summary = client.get("/api/v1/evolution/summary", params=_params()).json()
    assert summary["signals_collected"] == 1
    assert summary["pending_proposals"] == 1
    assert summary["recent_runs"] == 1

    runs = client.get("/api/v1/evolution/runs", params=_params()).json()
    assert runs[0]["run_id"] == body["run_id"]
    assert runs[0]["engine"] == "llm_prompt_review"
    assert runs[0]["artifact_count"] >= 3
    assert runs[0]["proposal_id"] == body["proposal_id"]

    proposals = client.get("/api/v1/evolution/proposals", params=_params()).json()
    assert proposals[0]["id"] == body["proposal_id"]
    assert proposals[0]["proposal_type"] == "prompt_update"
    assert proposals[0]["target_name"] == "Capture Memory Extraction"

    validation = client.get("/api/v1/evolution/validation", params=_params()).json()
    result = next(row for row in validation if row["metric_id"] == "exploration_misclassified_as_decision_count")
    assert result["value"] == 1
    assert result["evaluator"] == "count_signals"

    assert db.query(CapabilityVersion).count() == 0
    assert db.query(CapabilityOverlay).count() == 0
    proposal = db.query(Proposal).filter(Proposal.id == body["proposal_id"]).first()
    assert proposal is not None
    assert proposal.status == "pending"
