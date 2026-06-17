import { describe, expect, it } from "vitest";
import { createDefaultProposalApplierRegistry } from "../src/modules/proposals/applierRegistry";

describe("proposal applier registry", () => {
  it("registers code_patch apply once Phase 9 workspaces are TS-owned", () => {
    expect(createDefaultProposalApplierRegistry().registeredTypes()).toContain("code_patch");
  });
});
