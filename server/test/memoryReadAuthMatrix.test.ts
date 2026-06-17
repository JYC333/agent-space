import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  canReadMemory,
  summaryOnlyRedactContent,
  type MemoryAuthFields,
} from "../src/modules/memory/memoryReadAuth";

/**
 * Memory read-authorization compatibility fixture.
 *
 * The fixture covers every visibility, sensitivity, owner/scope, workspace,
 * and selected-user branch. Because this is the read-leak boundary, any
 * decision drift fails the build.
 */

const fixturePath = join(__dirname, "fixtures", "memory_read_auth_matrix.json");

interface MatrixCase {
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

const cases: MatrixCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("memory read auth compatibility", () => {
  it("matches the frozen authorization + redaction fixture over every case", () => {
    expect(cases.length).toBeGreaterThan(0);
    for (const { memory, ctx, expected } of cases) {
      expect({
        can_read: canReadMemory(memory, ctx),
        redact_content: summaryOnlyRedactContent(memory, ctx.userId),
      }).toEqual(expected);
    }
  });
});
