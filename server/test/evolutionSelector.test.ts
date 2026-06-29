import { describe, expect, it } from "vitest";
import { EvolutionSelector } from "../src/modules/evolution/selector";
import type {
  EvolutionSignalRow,
  EvolutionStrategyAssetRow,
  EvolutionTargetRow,
} from "../src/modules/evolution/types";

describe("EvolutionSelector", () => {
  it("selects an active matching strategy and excludes disabled strategies", () => {
    const selector = new EvolutionSelector();
    const selected = selector.select({
      target: target({ target_type: "system", risk_level: "medium" }),
      signals: [signal("runtime_failure")],
      strategies: [
        strategy("disabled", {
          status: "disabled",
          signals_match_json: ["runtime_failure"],
          confidence_score: 0.99,
        }),
        strategy("repair.runtime_failure", {
          signals_match_json: ["runtime_failure"],
          confidence_score: 0.55,
        }),
      ],
    });

    expect(selected.selectedStrategy?.strategy_key).toBe("repair.runtime_failure");
    expect(selected.candidateStrategyIds).toEqual(["strategy-repair.runtime_failure"]);
    expect(selected.rejectedReasons).toContainEqual(expect.objectContaining({
      strategy_key: "disabled",
      reason: "strategy_disabled",
    }));
  });

  it("blocks strategies above the target risk policy ceiling", () => {
    const selector = new EvolutionSelector();
    const selected = selector.select({
      target: target({
        target_type: "capability",
        risk_level: "medium",
        engine_policy_json: { max_strategy_risk: "medium" },
      }),
      signals: [signal("capability_gap")],
      strategies: [
        strategy("improve.capability_gap", {
          target_type: "capability",
          risk_level: "high",
          signals_match_json: ["capability_gap"],
        }),
      ],
    });

    expect(selected.selectedStrategy).toBeNull();
    expect(selected.rejectedReasons).toContainEqual(expect.objectContaining({
      strategy_key: "improve.capability_gap",
      reason: "strategy_risk_exceeds_target_policy",
    }));
  });

});

function target(overrides: Partial<EvolutionTargetRow> = {}): EvolutionTargetRow {
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
    engine_policy_json: {},
    metadata_json: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function signal(signalType: string): EvolutionSignalRow {
  return {
    id: `signal-${signalType}`,
    space_id: "space-1",
    target_id: "target-1",
    target_name: "Target",
    target_type: "system",
    capability_key: null,
    signal_type: signalType,
    source_type: "manual",
    source_id: null,
    severity: "medium",
    summary: null,
    payload_json: {},
    created_at: "2026-01-01T00:00:00Z",
  };
}

function strategy(
  strategyKey: string,
  overrides: Partial<EvolutionStrategyAssetRow> = {},
): EvolutionStrategyAssetRow {
  return {
    id: `strategy-${strategyKey}`,
    space_id: null,
    strategy_key: strategyKey,
    name: strategyKey,
    description: null,
    category: "repair",
    target_type: "system",
    status: "active",
    risk_level: "medium",
    signals_match_json: [],
    preconditions_json: {},
    strategy_steps_json: [],
    constraints_json: [],
    validation_policy_json: {},
    tool_policy_json: {},
    routing_hint_json: {},
    provenance_type: "built_in",
    source_ref_json: {},
    success_count: 0,
    failure_count: 0,
    confidence_score: 0.5,
    last_selected_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
