import { describe, expect, it } from "vitest";
import {
  assertIncompleteCodePatchConfirmation,
  ProposalApplyHttpError,
} from "../src/modules/proposals/applyService";

describe("proposal apply service guards", () => {
  it("requires explicit confirmation before applying incomplete code patches", () => {
    expect(() => assertIncompleteCodePatchConfirmation(
      "code_patch",
      {
        incomplete_patch: true,
        skipped_changes: [{ path: "binary.dat", reason: "binary" }],
      },
      false,
    )).toThrow(ProposalApplyHttpError);

    try {
      assertIncompleteCodePatchConfirmation(
        "code_patch",
        {
          incomplete_patch: true,
          skipped_changes: [{ path: "binary.dat", reason: "binary" }],
        },
        false,
      );
    } catch (error) {
      expect(error).toBeInstanceOf(ProposalApplyHttpError);
      expect((error as ProposalApplyHttpError).statusCode).toBe(422);
      expect((error as ProposalApplyHttpError).detail).toMatchObject({
        code: "incomplete_patch_requires_confirmation",
        skipped_changes: [{ path: "binary.dat", reason: "binary" }],
      });
    }

    expect(() => assertIncompleteCodePatchConfirmation(
      "code_patch",
      { incomplete_patch: true },
      true,
    )).not.toThrow();
    expect(() => assertIncompleteCodePatchConfirmation(
      "memory_create",
      { incomplete_patch: true },
      false,
    )).not.toThrow();
  });
});
