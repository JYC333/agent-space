import { describe, expect, it } from "vitest";
import { resolveSandboxLevelForRuntime } from "../src/modules/runs/runRepositoryHelpers";

describe("runtime sandbox resolution", () => {
  it("uses an ephemeral run directory for a CLI without a workspace", () => {
    expect(resolveSandboxLevelForRuntime({
      adapterType: "opencode",
      configuredLevel: "none",
      riskLevel: "low",
      workspaceId: null,
    })).toBe("ephemeral");
  });

  it("uses a worktree when a workspace is bound", () => {
    expect(resolveSandboxLevelForRuntime({
      adapterType: "opencode",
      configuredLevel: "none",
      riskLevel: "high",
      workspaceId: "workspace-1",
    })).toBe("worktree");
  });

  it("does not add a workspace requirement to a managed API runtime", () => {
    expect(resolveSandboxLevelForRuntime({
      adapterType: "model_api",
      configuredLevel: "none",
      riskLevel: "low",
      workspaceId: null,
    })).toBe("none");
  });

  it("forces critical local CLI runs into one-shot Docker", () => {
    expect(resolveSandboxLevelForRuntime({
      adapterType: "opencode",
      configuredLevel: "none",
      riskLevel: "critical",
      workspaceId: null,
    })).toBe("one_shot_docker");
  });
});
