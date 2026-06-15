import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadProtocol } from "../src/modules/providers/protocolRuntime";
import { buildChatContext } from "../src/modules/agents/chatContextBuilder";

/**
 * Cross-language chat context build parity (Stage 6 slice 4 flip gate).
 *
 * The fixture is generated from the real Python `apply_context_budget` over a
 * candidate/cap matrix that exercises empty input, item/token caps, dedup, and
 * null-id non-dedup (`backend/tests/support/gen_chat_context_build_parity.py`).
 * This runs the TS `buildChatContext` over the same inputs and asserts the
 * selection, token_count, truncated flag, and retrieval_trace are identical. If
 * the two engines diverge, this fails — TS must match Python before the route
 * flips.
 */

const fixturePath = join(__dirname, "fixtures", "chat_context_build_parity.json");

interface ParityCase {
  input: Record<string, unknown>;
  expected: {
    items: Record<string, unknown>[];
    token_count: number;
    truncated: boolean;
    retrieval_trace: Record<string, unknown>;
  };
}

const cases: ParityCase[] = JSON.parse(readFileSync(fixturePath, "utf8"));

describe("chat context build parity (TS vs Python)", () => {
  it("matches Python selection over every fixture case", async () => {
    const { ChatContextCandidatesResultSchema } = await loadProtocol();
    expect(cases.length).toBeGreaterThan(0);
    for (const { input, expected } of cases) {
      const candidates = ChatContextCandidatesResultSchema.parse(input);
      const bundle = buildChatContext(candidates);

      // Compare selected items by the candidate fields (defaults applied).
      const actualItems = bundle.items.map((item) => ({
        item_type: item.item_type,
        item_id: item.item_id ?? null,
        title: item.title ?? null,
        excerpt: item.excerpt ?? null,
        score: item.score ?? null,
        reason: item.reason ?? null,
        token_count: item.token_count ?? null,
        metadata: item.metadata ?? {},
      }));
      const expectedItems = expected.items.map((item) => ({
        item_type: item.item_type,
        item_id: item.item_id ?? null,
        title: item.title ?? null,
        excerpt: item.excerpt ?? null,
        score: item.score ?? null,
        reason: item.reason ?? null,
        token_count: item.token_count ?? null,
        metadata: item.metadata ?? {},
      }));

      expect(actualItems).toEqual(expectedItems);
      expect(bundle.token_count).toBe(expected.token_count);
      expect(bundle.truncated).toBe(expected.truncated);
      expect(bundle.retrieval_trace).toEqual(expected.retrieval_trace);
    }
  });
});
