import { describe, expect, it } from "vitest";
import { DeterministicRouteSelector, mergeRouteHints } from "../src/modules/routing/router";
import type { RouteCandidate } from "../src/modules/routing/types";
import { SERVER_MODULES } from "../src/gateway/routeRegistry";

function candidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    runtime_profile_id: "profile-1",
    profile_name: "Primary",
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    model_name: "model-1",
    credential_profile_id: null,
    runtime_config_json: {},
    runtime_policy_json: {},
    enabled: true,
    is_default: true,
    credential_available: true,
    capabilities: ["research"],
    tools: ["browser"],
    minimum_sandbox_level: "none",
    supports_workspace: false,
    supports_one_shot_docker: false,
    supports_live: true,
    supports_dry_run: true,
    trust_level: "high",
    estimated_cost_usd: 1,
    estimated_latency_ms: 500,
    historical_verification_pass_rate: 0.9,
    ...overrides,
  };
}

describe("deterministic route selector", () => {
  it("registers the durable run route-decision read surface", () => {
    expect(SERVER_MODULES.find((module) => module.name === "routing")).toBeDefined();
  });

  it("hard-filters credentials, capabilities, sandbox, and trust before scoring", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "worktree",
      execution_mode: "live",
      risk_level: "high",
      workspace_available: true,
      required_capabilities: ["code"],
      required_tools: ["shell"],
    }, [candidate({ credential_available: false, trust_level: "low" })]);
    expect(result.selected).toBeNull();
    expect(result.rejected[0]?.reasons).toEqual(expect.arrayContaining([
      "credential_unavailable",
      "required_capability_missing",
      "required_tool_missing",
      "trust_level_too_low",
    ]));
  });

  it("rejects a weaker sandbox instead of confusing it with a stronger candidate", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "one_shot_docker",
      execution_mode: "live",
      risk_level: "critical",
      workspace_available: true,
    }, [
      candidate({ minimum_sandbox_level: "worktree" }),
      candidate({ runtime_profile_id: "docker", minimum_sandbox_level: "one_shot_docker", supports_one_shot_docker: true }),
    ]);
    expect(result.selected?.candidate.runtime_profile_id).toBe("docker");
    expect(result.rejected).toEqual(expect.arrayContaining([
      expect.objectContaining({ runtime_profile_id: "profile-1", reasons: expect.arrayContaining(["sandbox_requirement_not_supported"]) }),
    ]));
  });

  it("filters critical local CLI candidates by Docker capability even when the initial adapter is managed API", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "none",
      execution_mode: "live",
      risk_level: "critical",
      workspace_available: true,
    }, [
      candidate({
        runtime_profile_id: "local-unsafe",
        adapter_type: "codex_cli",
        minimum_sandbox_level: "worktree",
        supports_workspace: true,
        supports_one_shot_docker: false,
        trust_level: "high",
      }),
      candidate({ runtime_profile_id: "managed-safe", adapter_type: "model_api" }),
    ]);
    expect(result.selected?.candidate.runtime_profile_id).toBe("managed-safe");
    expect(result.rejected).toEqual(expect.arrayContaining([
      expect.objectContaining({
        runtime_profile_id: "local-unsafe",
        reasons: expect.arrayContaining(["sandbox_requirement_not_supported"]),
      }),
    ]));
  });

  it("selects the highest deterministic score and keeps the rest as fallback chain", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "worktree",
      execution_mode: "live",
      risk_level: "low",
      workspace_available: true,
      hints: { ...mergeRouteHints([{ source: "task_contract", value: { preferred_adapters: ["claude_code"] } }]) },
    }, [
      candidate({ runtime_profile_id: "model", profile_name: "Model", adapter_type: "model_api", minimum_sandbox_level: "worktree", supports_workspace: true, is_default: true }),
      candidate({ runtime_profile_id: "claude", profile_name: "Claude", adapter_type: "claude_code", minimum_sandbox_level: "worktree", supports_workspace: true, is_default: false, historical_verification_pass_rate: 0.8 }),
    ]);
    expect(result.selected?.candidate.runtime_profile_id).toBe("claude");
    expect(result.fallback_chain).toEqual(["claude", "model"]);
  });

  it("merges task, workflow, and evolution hints with source trace", () => {
    const hints = mergeRouteHints([
      { source: "task_contract", value: { required_capabilities: ["research"], cost_budget_usd: 2 } },
      { source: "workflow_node", value: { required_tools: ["browser"], preferred_adapter_types: ["model_api"] } },
      { source: "evolution_strategy", value: { minimum_trust_level: "high", latency_budget_ms: 1000 } },
    ]);
    expect(hints).toMatchObject({
      required_capabilities: ["research"],
      required_tools: ["browser"],
      preferred_adapter_types: ["model_api"],
      minimum_trust_level: "high",
      cost_budget_usd: 2,
      latency_budget_ms: 1000,
    });
    expect(hints.sources).toEqual(["task_contract", "workflow_node", "evolution_strategy"]);
  });

  it("never lets a route hint lower risk-derived sandbox or trust requirements", () => {
    const hints = mergeRouteHints([{
      source: "workflow_node",
      value: { required_sandbox_level: "none", minimum_trust_level: "low" },
    }]);
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "worktree",
      execution_mode: "live",
      risk_level: "high",
      workspace_available: true,
      hints,
    }, [candidate({ minimum_sandbox_level: "none", trust_level: "medium" })]);
    expect(result.selected).toBeNull();
    expect(result.rejected[0]?.reasons).toEqual(expect.arrayContaining([
      "trust_level_too_low",
    ]));
  });

  it("treats a manually selected runtime profile as a hard constraint", () => {
    const result = new DeterministicRouteSelector().select({
      runtime_profile_id: "profile-1",
      runtime_profile_is_explicit: true,
      required_sandbox_level: "none",
      execution_mode: "live",
      risk_level: "low",
      workspace_available: false,
    }, [
      candidate({ runtime_profile_id: "profile-1", historical_verification_pass_rate: 0.1 }),
      candidate({ runtime_profile_id: "profile-2", historical_verification_pass_rate: 1, is_default: false }),
    ]);
    expect(result.selected?.candidate.runtime_profile_id).toBe("profile-1");
    expect(result.rejected).toEqual(expect.arrayContaining([
      expect.objectContaining({ runtime_profile_id: "profile-2", reasons: ["explicit_profile_not_selected"] }),
    ]));
  });

  it("selects the next eligible profile when a retry excludes the prior route", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "none",
      execution_mode: "live",
      risk_level: "low",
      workspace_available: false,
      excluded_runtime_profile_ids: ["profile-1"],
      fallback_runtime_profile_ids: ["profile-1", "profile-2"],
    }, [
      candidate({ runtime_profile_id: "profile-1" }),
      candidate({ runtime_profile_id: "profile-2", is_default: false }),
    ]);
    expect(result.selected?.candidate.runtime_profile_id).toBe("profile-2");
    expect(result.rejected).toEqual(expect.arrayContaining([
      expect.objectContaining({
        runtime_profile_id: "profile-1",
        reasons: expect.arrayContaining(["runtime_profile_excluded_for_retry"]),
      }),
    ]));
  });

  it("requires conformance evidence before OpenCode can serve non-low-risk work", () => {
    const result = new DeterministicRouteSelector().select({
      required_sandbox_level: "worktree",
      execution_mode: "live",
      risk_level: "medium",
      workspace_available: true,
    }, [candidate({
      adapter_type: "opencode",
      minimum_sandbox_level: "worktree",
      supports_workspace: true,
      trust_level: "medium",
      conformance_status: null,
    })]);
    expect(result.selected).toBeNull();
    expect(result.rejected[0]?.reasons).toContain("runtime_conformance_required");

    const passed = new DeterministicRouteSelector().select({
      required_sandbox_level: "worktree",
      execution_mode: "live",
      risk_level: "medium",
      workspace_available: true,
    }, [candidate({
      adapter_type: "opencode",
      minimum_sandbox_level: "worktree",
      supports_workspace: true,
      trust_level: "medium",
      conformance_status: "passed",
    })]);
    expect(passed.selected?.candidate.adapter_type).toBe("opencode");
  });
});
