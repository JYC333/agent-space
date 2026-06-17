import { describe, expect, it } from "vitest";
import { createDefaultProposalApplierRegistry } from "../src/modules/proposals/applierRegistry";

describe("proposal applier registry", () => {
  it("registers the code_patch proposal applier", () => {
    expect(createDefaultProposalApplierRegistry().registeredTypes()).toContain("code_patch");
  });
});
