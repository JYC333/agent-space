import { describe, expect, it } from "vitest";
import { getBuiltInProjectPreset } from "../src/modules/projectPresets/registry";

describe("project preset registry", () => {
  it("ships Academic Research as a Project Sources, Corpus, and Graph backed preset", () => {
    const preset = getBuiltInProjectPreset("academic_research");
    expect(preset).toMatchObject({
      key: "academic_research",
      extraction_profile_key: "academic_paper_v1",
      graph_lens_id: "academic_citation_v1",
    });
    expect(preset?.sections).toEqual(["source_monitoring", "corpus", "project_graph"]);
  });
});
