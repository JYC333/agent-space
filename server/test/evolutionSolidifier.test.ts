import { describe, expect, it, vi } from "vitest";
import { EvolutionSolidifier } from "../src/modules/evolution/solidifier";
import type { EvolutionExperienceRow } from "../src/modules/evolution/types";

describe("EvolutionSolidifier", () => {
  it("persists an experience and updates selected strategy counters", async () => {
    const experience = experienceRow();
    const repository = {
      createExperience: vi.fn().mockResolvedValue(experience),
      updateStrategyExperienceStats: vi.fn().mockResolvedValue(undefined),
    };
    const solidifier = new EvolutionSolidifier(repository);

    await expect(solidifier.solidifyExperience({
      spaceId: "space-1",
      strategyAssetId: "strategy-1",
      targetId: "target-1",
      sourceRunId: "run-1",
      experienceKey: "repair.runtime_failure/run-1",
      summary: "Validated repair experience.",
      outcomeStatus: "success",
      provenanceType: "run_observed",
    })).resolves.toBe(experience);

    expect(repository.createExperience).toHaveBeenCalledWith(expect.objectContaining({
      strategyAssetId: "strategy-1",
      outcomeStatus: "success",
    }));
    expect(repository.updateStrategyExperienceStats).toHaveBeenCalledWith("strategy-1", "success");
  });

  it("does not update strategy counters when no strategy is linked", async () => {
    const repository = {
      createExperience: vi.fn().mockResolvedValue(experienceRow({ strategy_asset_id: null })),
      updateStrategyExperienceStats: vi.fn().mockResolvedValue(undefined),
    };
    const solidifier = new EvolutionSolidifier(repository);

    await solidifier.solidifyExperience({
      spaceId: "space-1",
      experienceKey: "manual/no-strategy",
      summary: "Manual observation.",
      outcomeStatus: "unknown",
      provenanceType: "user_authored",
    });

    expect(repository.updateStrategyExperienceStats).not.toHaveBeenCalled();
  });

  it("solidifies a run evaluation through the selected evolution decision", async () => {
    const experience = experienceRow({ outcome_status: "success" });
    const repository = {
      getRunExperienceContext: vi.fn().mockResolvedValue({
        spaceId: "space-1",
        runId: "run-1",
        targetId: "target-1",
        targetName: "Runtime target",
        strategyAssetId: "strategy-1",
        strategyKey: "repair.runtime_failure",
        strategyName: "Repair runtime failure",
        inputSignalIds: ["signal-1"],
        decisionReason: "matched runtime failure",
      }),
      getExperienceByKey: vi.fn().mockResolvedValue(null),
      createExperience: vi.fn().mockResolvedValue(experience),
      updateStrategyExperienceStats: vi.fn().mockResolvedValue(undefined),
    };
    const solidifier = new EvolutionSolidifier(repository);

    await expect(solidifier.solidifyFromRunEvaluation({
      id: "evaluation-1",
      space_id: "space-1",
      run_id: "run-1",
      evaluator_version: "post_run_finalization.v1",
      outcome_status: "passed",
      trajectory_status: "acceptable",
      evidence_json: { run_status: "succeeded" },
      rule_trace_json: [{ rule: "test" }],
    })).resolves.toBe(experience);

    expect(repository.createExperience).toHaveBeenCalledWith(expect.objectContaining({
      spaceId: "space-1",
      strategyAssetId: "strategy-1",
      sourceRunId: "run-1",
      experienceKey: "repair.runtime_failure/run/run-1/post_run_finalization.v1",
      outcomeStatus: "success",
      triggerSignals: ["signal-1"],
      provenanceType: "run_observed",
    }));
    expect(repository.updateStrategyExperienceStats).toHaveBeenCalledWith("strategy-1", "success");
  });

  it("does not duplicate an existing experience key", async () => {
    const experience = experienceRow();
    const repository = {
      getExperienceByKey: vi.fn().mockResolvedValue(experience),
      createExperience: vi.fn(),
      updateStrategyExperienceStats: vi.fn(),
    };
    const solidifier = new EvolutionSolidifier(repository);

    await expect(solidifier.solidifyExperience({
      spaceId: "space-1",
      strategyAssetId: "strategy-1",
      experienceKey: "repair.runtime_failure/run/run-1/post_run_finalization.v1",
      summary: "Existing experience.",
      outcomeStatus: "success",
      provenanceType: "run_observed",
    })).resolves.toBe(experience);

    expect(repository.createExperience).not.toHaveBeenCalled();
    expect(repository.updateStrategyExperienceStats).not.toHaveBeenCalled();
  });
});

function experienceRow(overrides: Partial<EvolutionExperienceRow> = {}): EvolutionExperienceRow {
  return {
    id: "experience-1",
    space_id: "space-1",
    strategy_asset_id: "strategy-1",
    strategy_key: "repair.runtime_failure",
    strategy_name: "Repair runtime failure",
    target_id: "target-1",
    target_name: "Target",
    source_run_id: "run-1",
    source_proposal_id: null,
    experience_key: "repair.runtime_failure/run-1",
    summary: "Validated repair experience.",
    trigger_signals_json: [],
    outcome_status: "success",
    confidence_score: 0.7,
    blast_radius_json: {},
    validation_trace_json: {},
    execution_trace_json: {},
    lessons_json: [],
    anti_patterns_json: [],
    environment_fingerprint_json: {},
    provenance_type: "run_observed",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
