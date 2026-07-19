import { describe, expect, it } from "vitest";
import { parseMonitorComparisons } from "../src/modules/projectResearch/monitorComparisonService";
import { parseCrossrefIntegrityEvents } from "../src/modules/projectResearch/integrityMonitorService";

describe("Project Research monitoring contracts", () => {
  it("requires one valid comparison for every supplied paper", () => {
    expect(parseMonitorComparisons({ comparisons: [
      { source_item_id: "paper-1", stance: "supports", detail: "Replicates the primary effect.", affected_sections: ["understanding"] },
      { source_item_id: "paper-2", stance: "contradicts", detail: "The effect disappears under the preregistered analysis.", affected_sections: ["understanding", "questions"] },
    ] }, ["paper-1", "paper-2"])).toHaveLength(2);
    expect(() => parseMonitorComparisons({ comparisons: [
      { source_item_id: "paper-1", stance: "supports", detail: "Replicates the effect.", affected_sections: [] },
    ] }, ["paper-1", "paper-2"])).toThrow(/every supplied paper/);
  });

  it("normalizes Crossref Retraction Watch update relations into stable alerts", () => {
    const alerts = parseCrossrefIntegrityEvents("https://doi.org/10.1000/Original", "source-1", {
      message: {
        "updated-by": [
          { DOI: "10.1000/retraction", type: "retraction", source: "retraction-watch" },
          { DOI: "10.1000/correction", type: "expression-of-concern", source: "publisher" },
        ],
      },
    });
    expect(alerts).toMatchObject([
      { doi: "10.1000/original", source_item_id: "source-1", event_type: "retraction", source: "retraction-watch", notice_doi: "10.1000/retraction" },
      { doi: "10.1000/original", event_type: "expression_of_concern", source: "publisher", notice_doi: "10.1000/correction" },
    ]);
    expect(alerts[0]?.event_key).toHaveLength(64);
  });
});
