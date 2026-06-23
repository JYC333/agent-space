import { describe, expect, it } from "vitest";
import {
  buildRetrievalEvalReportArtifactSpec,
  persistRetrievalEvalReportArtifact,
  RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE,
} from "../src/modules/retrieval/evalArtifacts";
import type { Queryable } from "../src/modules/routeUtils/common";

interface CapturedQuery {
  sql: string;
  params: readonly unknown[];
}

function fakeDb(): Queryable & { calls: CapturedQuery[] } {
  const calls: CapturedQuery[] = [];
  return {
    calls,
    async query(sql: string, params: readonly unknown[] = []) {
      calls.push({ sql, params });
      return { rows: [], rowCount: 1 };
    },
  };
}

const report = {
  source: "retrieval_bench",
  suite: "golden-recall",
  report_label: "Nightly retrieval eval",
  k: 5,
  metrics: { recall: 1, mrr: 0.95, ndcg: 0.98 },
  counts: { cases: 3, misses: 0 },
  cases: [
    {
      case_label: "named-entity",
      object_type: "knowledge_item" as const,
      mode: "lexical" as const,
      k: 5,
      metrics: { recall: 1, rr: 1 },
      expected_count: 1,
      returned_count: 5,
      hit_count: 1,
      first_relevant_rank: 1,
      diagnostic_codes: [],
    },
  ],
  rank_attribution: {
    evidence_kind_counts: { lexical_match: 2, graph_neighbor: 1 },
    matched_field_counts: { title: 2, content: 1 },
    score_buckets: { top_1: 1, top_5: 3 },
  },
  diagnostic_codes: ["all_cases_passed"],
};

describe("retrieval eval report artifacts", () => {
  it("builds an aggregate-only owner-private eval report artifact", () => {
    const spec = buildRetrievalEvalReportArtifactSpec({
      spaceId: "space-1",
      ownerUserId: "user-1",
      report,
      settingsSnapshot: { default_search_mode: "hybrid" },
    });

    expect(spec).toMatchObject({
      artifact_type: RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE,
      visibility: "private",
      title: "Retrieval Eval Report: Nightly retrieval eval",
      mime_type: "application/json; charset=utf-8",
    });
    expect(spec.metadata_json).toMatchObject({
      kind: RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE,
      visibility: "private",
      owner_user_id: "user-1",
      metrics: { recall: 1, mrr: 0.95, ndcg: 0.98 },
      access_safety: {
        aggregate_only: true,
        candidate_ids_included: false,
        content_included: false,
      },
    });
    expect(JSON.stringify(spec.metadata_json)).not.toContain("object_id");
    expect(JSON.stringify(spec.metadata_json)).not.toContain("snippet");
  });

  it("persists eval reports as private artifacts", async () => {
    const db = fakeDb();
    const artifactId = await persistRetrievalEvalReportArtifact(db, {
      spaceId: "space-1",
      ownerUserId: "user-1",
      report,
    });

    expect(artifactId).toMatch(/[0-9a-f-]{36}/);
    expect(db.calls).toHaveLength(1);
    const params = db.calls[0]!.params;
    expect(params[1]).toBe("space-1");
    expect(params[4]).toBe(RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE);
    expect(params[14]).toBe("private");
    expect(params[15]).toBe("user-1");
    const metadata = JSON.parse(String(params[13]));
    expect(metadata).toMatchObject({
      kind: RETRIEVAL_EVAL_REPORT_ARTIFACT_TYPE,
      source: "retrieval_bench",
      suite: "golden-recall",
    });
  });
});
