import { describe, expect, it } from "vitest";
import { buildResearchReportReaderProjection } from "../src/modules/projectResearch/reportProjection";

const report = {
  research_question: "Does X improve Y?", summary: "The evidence is mixed.",
  findings: [{ claim: "X helps.", support: "Two papers agree.", references: [{ arxiv_id: "1" }] }],
  sources: [{ title: "Paper", authors: ["A"], year: 2025, relevance: "relevant", summary: "Evidence.", references: [{ doi: "10/x" }] }],
  limitations: ["Small corpus"],
  ideas: [{ title: "Test X", problem: "Uncertainty", novelty: "New sample", testability: "Run benchmark", references: [{ source_item_id: "item-1" }] }],
};

describe("research report reader projection", () => {
  it("is stable and includes every user-facing section", () => {
    const first = buildResearchReportReaderProjection(report);
    const second = buildResearchReportReaderProjection(report);
    expect(second).toEqual(first);
    expect(first.contentHash).toMatch(/^[a-f0-9]{64}$/);
    expect(first.normalizedText).toContain("Executive summary");
    expect(first.normalizedText).toContain("Two papers agree.");
    expect(first.normalizedText).toContain("Small corpus");
    expect(first.normalizedText).toContain("Run benchmark");
  });

  it("rewrites inline raw-id citation groups to the References panel labels", () => {
    const projection = buildResearchReportReaderProjection({
      ...report,
      summary: "Adaptive players converge faster [fc880096, 8fa13ba8]. Fixed weighting lags [9e9e9e9e].",
      findings: [
        { claim: "X helps.", support: "Truncated prefix cite [fc880096].", references: [{ evidence_id: "fc880096-79a8-4765-ae1f-0c282463691e" }] },
        { claim: "Y helps.", support: "Second cite.", references: [{ evidence_id: "8fa13ba8-9b59-46b8-8db3-8c54ba666903" }] },
      ],
    });
    expect(projection.normalizedText).toContain("Adaptive players converge faster [ref-1, ref-2].");
    // Unknown ids stay verbatim rather than being guessed into a wrong reference.
    expect(projection.normalizedText).toContain("Fixed weighting lags [9e9e9e9e].");
    expect(projection.normalizedText).toContain("Truncated prefix cite [ref-1].");
  });

  it("uses persisted two-level reference ids for labels and inline citations", () => {
    const projection = buildResearchReportReaderProjection({
      ...report,
      summary: "Cited inline [fc880096, 25919d08].",
      findings: [{
        claim: "X helps.", support: "Support.",
        references: [
          { evidence_id: "fc880096-79a8-4765-ae1f-0c282463691e", reference_id: "ref-1a" },
          { evidence_id: "25919d08-16eb-4c61-ac8b-9f4180d5a34b", reference_id: "ref-1b" },
          { evidence_id: "fc880096-79a8-4765-ae1f-0c282463691e", reference_id: "ref-1a" },
        ],
      }],
    });
    expect(projection.normalizedText).toContain("Cited inline [ref-1a, ref-1b].");
    expect(projection.normalizedText).toContain("References: [ref-1a]; [ref-1b]");
  });

  it("leaves ordinary bracketed prose and the reference list untouched", () => {
    const projection = buildResearchReportReaderProjection({
      ...report,
      summary: "Bracketed prose [not a citation] and a year [2025] survive.",
    });
    expect(projection.normalizedText).toContain("Bracketed prose [not a citation] and a year [2025] survive.");
    expect(projection.normalizedText).toContain("References: [ref-1]");
  });
});
