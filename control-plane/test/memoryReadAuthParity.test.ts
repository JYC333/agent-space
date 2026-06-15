import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  canReadMemory,
  summaryOnlyRedactContent,
  type MemoryAuthFields,
} from "../src/modules/memory/memoryReadAuth";

/**
 * Cross-language memory read-authorization parity (Stage 6 slice 5 flip gate).
 *
 * The fixture is generated from the real Python `can_read_memory` +
 * `summary_only_redact_content` over a matrix covering every visibility,
 * sensitivity, owner/scope, workspace, and selected-user branch
 * (`backend/tests/support/gen_memory_read_auth_parity.py`). This runs the TS
 * implementation over the same inputs and asserts identical decisions. Because
 * this is the read-leak boundary, any divergence fails the build.
 */

const fixturePath = join(__dirname, "fixtures", "memory_read_auth_parity.json");

interface ParityCase {
  memory: MemoryAuthFields;
  ctx: {
    userId: string;
    spaceId: string;
    workspaceId: string | null;
    includeSystemScope: boolean;
    includePublicTemplates: boolean;
  };
  expected: { can_read: boolean; redact_content: boolean };
}

const cases: ParityCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("memory read auth parity (TS vs Python)", () => {
  it("matches Python can_read_memory + redaction over every fixture case", () => {
    expect(cases.length).toBeGreaterThan(0);
    for (const { memory, ctx, expected } of cases) {
      expect({
        can_read: canReadMemory(memory, ctx),
        redact_content: summaryOnlyRedactContent(memory, ctx.userId),
      }).toEqual(expected);
    }
  });
});
