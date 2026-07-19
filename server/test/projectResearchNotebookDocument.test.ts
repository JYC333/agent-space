import { describe, expect, it } from "vitest";
import { applyNotebookOps, markdownToPm, normalizePmText, parseNotebookOps, pmBlocksText } from "../src/modules/projectResearch/notebookDocument";

describe("research notebook document conversion", () => {
  it("preserves headings and lists as editable Tiptap blocks", () => {
    const document = markdownToPm("## Findings\n\n- First result\n- Second result\n\nNext question");
    expect(document.content).toEqual([
      { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Findings" }] },
      { type: "bulletList", content: [
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "First result" }] }] },
        { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "Second result" }] }] },
      ] },
      { type: "paragraph", content: [{ type: "text", text: "Next question" }] },
    ]);
    expect(normalizePmText(document)).toBe("Findings\n\n- First result\n- Second result\n\nNext question");
    expect(pmBlocksText(document)).toEqual(["Findings", "- First result\n- Second result", "Next question"]);
  });

  it("applies block ops without rewriting untouched blocks", () => {
    const document = markdownToPm("Claim one\n\nClaim two\n\nClaim three");
    const ops = parseNotebookOps([
      { op: "replace", index: 1, count: 1, markdown: "Claim two, revised" },
      { op: "delete", index: 2, count: 1, markdown: null },
      { op: "append", index: null, count: null, markdown: "## Update\n\nAppended detail" },
    ], 3);
    const next = applyNotebookOps(document, ops);
    expect(normalizePmText(next)).toBe("Claim one\n\nClaim two, revised\n\nUpdate\n\nAppended detail");
    expect((next.content as unknown[])[0]).toEqual((document.content as unknown[])[0]);
  });

  it("rejects malformed, out-of-range, or overlapping ops as a batch", () => {
    expect(() => parseNotebookOps([{ op: "replace", index: 3, count: 1, markdown: "x" }], 3)).toThrow(/outside the document/);
    expect(() => parseNotebookOps([{ op: "insert", index: 0, markdown: "" }], 3)).toThrow(/insert requires markdown/);
    expect(() => parseNotebookOps([
      { op: "replace", index: 0, count: 2, markdown: "x" },
      { op: "delete", index: 1, count: 1 },
    ], 3)).toThrow(/must not overlap/);
    expect(() => parseNotebookOps([], 3)).toThrow(/non-empty/);
  });
});
