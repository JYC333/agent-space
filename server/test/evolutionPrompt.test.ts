import { describe, expect, it } from "vitest";
import {
  EVOLUTION_PLAN_PROMPT_VERSION,
  EVOLUTION_PLAN_REVIEW_SCHEMA,
  buildEvolutionPlanPrompt,
} from "../src/modules/evolution/prompt";
import type {
  EvolutionSelection,
  EvolutionSignalRow,
  EvolutionStrategyAssetRow,
  EvolutionTargetRow,
} from "../src/modules/evolution/types";

describe("buildEvolutionPlanPrompt", () => {
  it("builds an agent-space prompt with proposal and evidence boundaries", () => {
    const prompt = buildEvolutionPlanPrompt({
      target: target(),
      selectedStrategy: strategy(),
      recentSignals: [signal()],
      selection: selection(),
      runId: "run-1",
      selectorDecisionId: "decision-1",
      requestSignalId: "signal-review",
    });

    expect(prompt.prompt_version).toBe(EVOLUTION_PLAN_PROMPT_VERSION);
    expect(prompt.system).toContain("agent-space Evolution planner");
    expect(prompt.system).toContain("ProposalApplierRegistry");
    expect(prompt.system).toContain("Do not apply changes");
    expect(prompt.user).toContain(EVOLUTION_PLAN_REVIEW_SCHEMA);
    expect(prompt.user).toContain("repair.runtime_failure");
    expect(prompt.user).toContain("signal-runtime_failure");
    expect(prompt.user).toContain("signal-review");
    expect(prompt.user).toContain("agent_id");
    expect(prompt.user).toContain("memory_create");
    expect(prompt.user).toContain("prompt_update");
  });
});

function target(): EvolutionTargetRow {
  return {
    id: "target-1",
    space_id: "space-1",
    target_type: "system",
    target_ref_type: null,
    target_ref_id: null,
    capability_key: null,
    current_version_id: null,
    risk_level: "medium",
    status: "active",
    enabled: true,
    engine_policy_json: { max_strategy_risk: "medium" },
    metadata_json: { target_name: "Runtime repair target", agent_id: "agent-1" },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function signal(): EvolutionSignalRow {
  return {
    id: "signal-runtime_failure",
    space_id: "space-1",
    target_id: "target-1",
    target_name: "Runtime repair target",
    target_type: "system",
    capability_key: null,
    signal_type: "runtime_failure",
    source_type: "run",
    source_id: "run-failed",
    severity: "medium",
    summary: "Runtime failed before producing an artifact.",
    payload_json: { error_code: "runtime_error" },
    created_at: "2026-01-01T00:00:00Z",
  };
}

function strategy(): EvolutionStrategyAssetRow {
  return {
    id: "strategy-1",
    space_id: null,
    strategy_key: "repair.runtime_failure",
    name: "Runtime failure repair",
    description: "Diagnose a failed run and produce a reviewable repair plan.",
    category: "repair",
    target_type: "system",
    status: "active",
    risk_level: "medium",
    signals_match_json: ["runtime_failure"],
    preconditions_json: { requires_agent_id: true },
    strategy_steps_json: ["inspect evidence", "draft repair", "define validation"],
    constraints_json: ["no direct apply"],
    validation_policy_json: { required_checks: ["typecheck"] },
    tool_policy_json: { allow: ["read"] },
    routing_hint_json: { proposal_type: null },
    provenance_type: "built_in",
    source_ref_json: {},
    success_count: 1,
    failure_count: 0,
    confidence_score: 0.6,
    last_selected_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function selection(): EvolutionSelection {
  return {
    selectedStrategy: strategy(),
    candidateStrategyIds: ["strategy-1"],
    inputSignalIds: ["signal-runtime_failure", "signal-review"],
    decisionReason: "Selected repair.runtime_failure for matching runtime failure evidence.",
    scoreTrace: { selected_score: 0.82 },
    rejectedReasons: [],
  };
}
