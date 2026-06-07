from __future__ import annotations

import json
from pathlib import Path

from app.evolution.constants import DEFAULT_CAPTURE_CAPABILITY_KEY
from app.evolution.services import (
    CapabilityVersioningService,
    EvolutionContextBuilder,
    EvolutionRunService,
    EvolutionSignalService,
    EvolutionTargetRegistry,
)
from app.evolution.validation import evaluate_target_validation
from app.memory.proposals import ProposalService
from app.models import Artifact, CapabilityOverlay, CapabilityVersion, EvolutionSignal, Proposal
from app.providers.invocation import CompletionResult
from tests.support import factories
from tests.support.ids import DEFAULT_USER_ID, PERSONAL_SPACE_ID


def _default_target(db):
    return EvolutionTargetRegistry(db).ensure_default_target_for_capture_memory_extraction()


def _add_signal(db, target_id: str):
    return EvolutionSignalService(db).create_signal(
        space_id=PERSONAL_SPACE_ID,
        target_id=target_id,
        signal_type="exploration_misclassified_as_decision",
        source_type="proposal",
        source_id="proposal-test",
        severity="medium",
        summary="Exploration was saved as a stable decision.",
        payload_json={"review_outcome": "rejected"},
    )


def _add_typed_signal(db, target_id: str, signal_type: str):
    return EvolutionSignalService(db).create_signal(
        space_id=PERSONAL_SPACE_ID,
        target_id=target_id,
        signal_type=signal_type,
        source_type="proposal",
        source_id=f"{signal_type}-test",
        severity="medium",
        summary=signal_type,
        payload_json={},
    )


def _install_llm_review(monkeypatch, db):
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
            text=json.dumps({
                "report": {
                    "summary": "Prompt should distinguish exploration from decisions.",
                    "signal_analysis": ["Exploration was saved as a stable decision."],
                    "risk_notes": ["Review before approval."],
                    "expected_improvement": "Fewer false stable memories.",
                },
                "prompt_revision": {
                    "revision_format": "prompt_revision.v1",
                    "capability_key": DEFAULT_CAPTURE_CAPABILITY_KEY,
                    "prompt": (
                        "Revised prompt: treat exploratory notes as Activity evidence "
                        "unless the user explicitly accepts a memory proposal."
                    ),
                    "change_summary": ["Clarified exploration handling."],
                    "evidence_signal_ids": [],
                },
            }),
            model="gpt-test",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        ),
    )


def test_default_capture_memory_extraction_target_registration(db):
    target = _default_target(db)

    assert target.space_id is None
    assert target.target_type == "prompt"
    assert target.capability_key == DEFAULT_CAPTURE_CAPABILITY_KEY
    assert target.risk_level == "medium"
    assert target.enabled is True
    assert "prompt_update" in target.engine_policy_json["allowed_proposal_types"]
    metric_ids = {row["id"] for row in target.metadata_json["validation"]["metrics"]}
    assert "stable_preference_missed_count" in metric_ids
    assert "memory_candidate_reject_rate" in metric_ids


def test_create_and_list_evolution_signals(db):
    target = _default_target(db)
    created = _add_signal(db, target.id)

    rows = EvolutionSignalService(db).list_signals(
        target_id=target.id,
        space_id=PERSONAL_SPACE_ID,
    )

    assert rows == [created]
    assert rows[0].signal_type == "exploration_misclassified_as_decision"
    assert rows[0].payload_json["review_outcome"] == "rejected"


def test_context_builder_creates_compact_evolution_context_artifact(db):
    target = _default_target(db)
    _add_signal(db, target.id)

    result = EvolutionContextBuilder(db).build(
        target=target,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    assert result.artifact.artifact_type == "evolution_context"
    assert result.artifact.run_id is None
    assert result.payload["target"]["capability_key"] == DEFAULT_CAPTURE_CAPABILITY_KEY
    assert result.payload["capability"]["found"] is True
    assert result.payload["recent_signals"][0]["signal_type"] == "exploration_misclassified_as_decision"
    validation_result = next(
        row for row in result.payload["validation_results"]
        if row["metric_id"] == "exploration_misclassified_as_decision_count"
    )
    assert validation_result["value"] == 1
    assert validation_result["evaluator"] == "count_signals"
    assert ".agent" not in result.artifact.content


def test_validation_rate_evaluator_counts_configured_signals(db):
    target = _default_target(db)
    _add_typed_signal(db, target.id, "memory_candidate_proposed")
    _add_typed_signal(db, target.id, "memory_candidate_proposed")
    _add_typed_signal(db, target.id, "memory_candidate_rejected")

    results = evaluate_target_validation(db, target, space_id=PERSONAL_SPACE_ID)
    reject_rate = next(row for row in results if row.metric_id == "memory_candidate_reject_rate")

    assert reject_rate.evaluator == "rate"
    assert reject_rate.value == 0.5
    assert reject_rate.numerator_count == 1
    assert reject_rate.denominator_count == 2


def test_llm_evolution_run_creates_artifacts_and_pending_proposal_without_apply(db, monkeypatch):
    _install_llm_review(monkeypatch, db)
    target = _default_target(db)
    _add_signal(db, target.id)

    result = EvolutionRunService(db).run(
        target_id=target.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    assert result.run.run_type == "evolution"
    assert result.run.status == "succeeded"
    assert result.context_artifact.artifact_type == "evolution_context"
    assert result.report_artifact.artifact_type == "evolution_report"
    assert result.revision_artifact.artifact_type == "prompt_revision"
    assert result.proposal.proposal_type == "prompt_update"
    assert result.proposal.status == "pending"
    assert db.query(CapabilityVersion).count() == 0
    assert db.query(CapabilityOverlay).count() == 0


def test_approved_prompt_update_creates_scoped_capability_version_and_overlay(db, monkeypatch):
    _install_llm_review(monkeypatch, db)
    target = _default_target(db)
    _add_signal(db, target.id)
    run_result = EvolutionRunService(db).run(
        target_id=target.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    accept_result = ProposalService(db).accept(
        run_result.proposal.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    assert accept_result is not None
    assert accept_result.proposal.status == "accepted"
    assert accept_result.capability_version is not None
    assert accept_result.capability_overlay is not None
    assert accept_result.capability_version.scope_type == "space"
    assert accept_result.capability_version.scope_id == PERSONAL_SPACE_ID
    assert accept_result.capability_overlay.overlay_type == "prompt_revision"
    assert "Revised prompt" in accept_result.capability_overlay.patch_json["prompt"]


def test_runtime_resolution_prefers_scoped_overlay_and_keeps_core_default_separate(db, monkeypatch):
    _install_llm_review(monkeypatch, db)
    target = _default_target(db)
    before = CapabilityVersioningService(db).resolve(
        DEFAULT_CAPTURE_CAPABILITY_KEY,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )
    assert before.source_scope_type == "core"
    assert before.core_manifest is not None

    _add_signal(db, target.id)
    run_result = EvolutionRunService(db).run(
        target_id=target.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )
    ProposalService(db).accept(
        run_result.proposal.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    after = CapabilityVersioningService(db).resolve(
        DEFAULT_CAPTURE_CAPABILITY_KEY,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )
    assert after.source_scope_type == "space"
    assert after.source_scope_id == PERSONAL_SPACE_ID
    assert after.version is not None
    assert after.overlays

    core_prompt = (
        Path(__file__).resolve().parents[3]
        / "capabilities"
        / "capture-memory-extraction"
        / "prompts"
        / "main.md"
    ).read_text()
    assert "avoid-promoting-exploration" not in core_prompt


def test_evolution_runtime_data_does_not_require_agent_directory(db, monkeypatch):
    _install_llm_review(monkeypatch, db)
    target = _default_target(db)
    _add_signal(db, target.id)
    run_result = EvolutionRunService(db).run(
        target_id=target.id,
        space_id=PERSONAL_SPACE_ID,
        user_id=DEFAULT_USER_ID,
    )

    runtime_rows = [
        target.metadata_json,
        target.engine_policy_json,
        run_result.context_artifact.content,
        run_result.report_artifact.content,
        run_result.revision_artifact.content,
        run_result.proposal.payload_json,
    ]
    serialized = json.dumps(runtime_rows, sort_keys=True)

    assert ".agent" not in serialized
    assert db.query(EvolutionSignal).count() == 1
    assert db.query(Artifact).filter(Artifact.artifact_type == "evolution_context").count() == 1
    assert db.query(Proposal).filter(Proposal.proposal_type == "prompt_update").count() == 1
