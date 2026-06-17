import { describe, expect, it } from "vitest";
import type { ChatContextCandidateItem } from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  buildChatContext,
  composeChatPrompt,
  renderContextPreamble,
} from "../src/modules/agents/chatContextBuilder";

function item(
  over: Partial<ChatContextCandidateItem> & { item_type: string },
): ChatContextCandidateItem {
  return { token_count: 0, metadata: {}, ...over };
}

describe("renderContextPreamble", () => {
  it("returns empty string for no items", () => {
    expect(renderContextPreamble([])).toBe("");
  });

  it("renders the header plus a bullet per item, with/without excerpt", () => {
    const out = renderContextPreamble([
      item({ item_type: "memory", title: "Mem", excerpt: "content" }),
      item({ item_type: "workspace", title: "WS", excerpt: "" }),
    ]);
    expect(out).toBe(
      "[Context from your space — use it if relevant; do not repeat it verbatim.]\n" +
        "- (memory) Mem: content\n" +
        "- (workspace) WS",
    );
  });

  it("falls back to item_type then 'item' for a missing title", () => {
    expect(
      renderContextPreamble([item({ item_type: "source", title: null, excerpt: "x" })]),
    ).toBe(
      "[Context from your space — use it if relevant; do not repeat it verbatim.]\n" +
        "- (source) source: x",
    );
  });
});

describe("composeChatPrompt", () => {
  it("prepends the preamble with a blank line, or returns the bare message", () => {
    expect(composeChatPrompt("PRE", "hi")).toBe("PRE\n\nhi");
    expect(composeChatPrompt("", "hi")).toBe("hi");
  });
});

describe("buildChatContext", () => {
  it("stops at max_items and flags truncation", () => {
    const bundle = buildChatContext({
      allowed_sources: ["memory"],
      max_tokens: 100000,
      max_items: 2,
      context_policy_applied: true,
      items: [
        item({ item_type: "memory", item_id: "a", token_count: 1 }),
        item({ item_type: "memory", item_id: "b", token_count: 1 }),
        item({ item_type: "memory", item_id: "c", token_count: 1 }),
      ],
    });
    expect(bundle.items.map((i) => i.item_id)).toEqual(["a", "b"]);
    expect(bundle.truncated).toBe(true);
    expect(bundle.retrieval_trace).toMatchObject({ item_count: 2, max_items: 2 });
  });
});
