import { describe, expect, it } from "vitest";
import { validatePath } from "../src/modules/workspaces/pathPolicy";

describe("workspace PathPolicy", () => {
  it("rejects traversal and secret-like paths", () => {
    expect(() =>
      validatePath({ path: "/workspace/../secret.txt", allowedRoot: "/workspace" }),
    ).toThrow(/Path traversal denied/);
    expect(() =>
      validatePath({ path: "/workspace/.env", allowedRoot: "/workspace" }),
    ).toThrow(/forbidden/);
    expect(() =>
      validatePath({ path: "/workspace/config/secrets/token.txt", allowedRoot: "/workspace" }),
    ).toThrow(/config\/secrets/);
  });

  it("allows env templates and requires code_patch for direct script writes", () => {
    expect(
      validatePath({ path: "/workspace/.env.example", allowedRoot: "/workspace" }),
    ).toBe("/workspace/.env.example");
    expect(() =>
      validatePath({ path: "/workspace/tool.sh", allowedRoot: "/workspace", mode: "write" }),
    ).toThrow(/code_patch Proposal/);
    expect(
      validatePath({
        path: "/workspace/tool.sh",
        allowedRoot: "/workspace",
        mode: "write",
        forTrustedCodePatchApply: true,
      }),
    ).toBe("/workspace/tool.sh");
  });

  it("blocks direct .git access in system_core workspaces", () => {
    expect(() =>
      validatePath({
        path: "/workspace/.git/config",
        allowedRoot: "/workspace",
        workspaceType: "system_core",
      }),
    ).toThrow(/\.git/);
  });
});
