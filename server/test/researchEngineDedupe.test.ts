import { describe, expect, it } from "vitest";
import { dedupeResearchCandidates } from "../src/modules/research/engine/service";
import type { ResearchCandidate } from "../src/modules/research/engine/types";

function candidate(overrides: Partial<ResearchCandidate>): ResearchCandidate {
  return { candidate_id: "candidate", kind: "academic_paper", title: "A Paper", authors: ["Ada Lovelace"], occurred_at: null, source_uri: null, excerpt: null, doi: null, arxiv_id: null, openalex_id: null, semantic_scholar_id: null, providers: ["arxiv"], trust_level: "normal", metadata: {}, ...overrides };
}

describe("research engine candidate dedupe", () => {
  it("uses DOI before provider-native ids and merges provenance", () => {
    const result = dedupeResearchCandidates([
      candidate({ candidate_id: "oa", doi: "10.1/shared", openalex_id: "W1", providers: ["openalex"] }),
      candidate({ candidate_id: "s2", doi: "10.1/shared", semantic_scholar_id: "S1", providers: ["semantic_scholar"], excerpt: "abstract" }),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ candidate_id: "oa", providers: ["openalex", "semantic_scholar"], openalex_id: "W1", semantic_scholar_id: "S1", excerpt: "abstract" });
  });

  it("falls back to normalized title and first author", () => {
    const result = dedupeResearchCandidates([
      candidate({ candidate_id: "one", title: "Agent-Memory: Systems!" }),
      candidate({ candidate_id: "two", title: "agent memory systems", providers: ["semantic_scholar"] }),
    ]);
    expect(result).toHaveLength(1);
  });

  it("uses a conservative fuzzy title match when the first author is identical", () => {
    const result = dedupeResearchCandidates([
      candidate({ candidate_id: "one", title: "Reliable Agent Memory Systems" }),
      candidate({ candidate_id: "two", title: "Reliable systems agent memory", providers: ["openalex"] }),
    ]);
    expect(result).toHaveLength(1);
  });
});
