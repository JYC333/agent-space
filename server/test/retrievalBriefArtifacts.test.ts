import { describe, expect, it } from "vitest";
import {
  buildRetrievalBriefArtifactSpec,
  persistRetrievalBriefArtifact,
} from "../src/modules/retrieval";

describe("retrieval brief artifacts", () => {
  it("builds structured retrieval_brief artifact content and metadata", () => {
    const spec = buildRetrievalBriefArtifactSpec({
      spaceId: "space-1",
      ownerUserId: "user-1",
      runId: "run-1",
      projectId: "project-1",
      query: "widget plan",
      objectTypes: ["knowledge_item"],
      maxResults: 5,
      mode: "lexical",
      includeTrace: true,
      surface: "knowledge_brief",
      egressPolicySnapshot: { external_egress_enabled: false },
      settingsSnapshot: { embedding_dimensions: 2560 },
      response: {
        brief: {
          answer: "Use the staged widget plan.",
          synthesized: true,
          citations: [{ object_type: "knowledge_item", object_id: "k1", title: "Widget Plan" }],
          gap_analysis: {
            stale: [],
            thin: [],
            low_coverage: false,
            uncited_claims: [],
            contradictions: [],
            missing_topics: ["budget"],
          },
        },
        items: [
          {
            object_type: "knowledge_item",
            object_id: "k1",
            title: "Widget Plan",
            snippet: "staged rollout",
            score: 0.9,
            evidence: { kind: "lexical_match" },
            matched_fields: ["title"],
          },
        ],
        total: 1,
        trace: { arms: { lexical: 1 } },
      },
    });

    expect(spec.artifact_type).toBe("retrieval_brief");
    expect(spec.visibility).toBe("private");
    expect(spec.title).toBe("Context Brief: widget plan");
    expect(spec.mime_type).toBe("application/json; charset=utf-8");
    expect(spec.metadata_json).toMatchObject({
      query: "widget plan",
      visibility: "private",
      run_id: "run-1",
      owner_user_id: "user-1",
      egress_policy_snapshot: { external_egress_enabled: false },
      item_refs: [{ object_type: "knowledge_item", object_id: "k1", title: "Widget Plan" }],
      gap_analysis: { missing_topics: ["budget"] },
    });
    expect(JSON.parse(spec.content)).toMatchObject(spec.metadata_json);
  });

  it("aggregates the distinct source connection ids from item source_refs (G3)", () => {
    const spec = buildRetrievalBriefArtifactSpec({
      spaceId: "space-1",
      ownerUserId: "user-1",
      runId: null,
      projectId: null,
      query: "widget plan",
      maxResults: 5,
      mode: "hybrid",
      includeTrace: false,
      surface: "knowledge_brief",
      egressPolicySnapshot: { external_egress_enabled: false },
      response: {
        brief: {
          answer: "From the connected sources.",
          synthesized: true,
          citations: [],
          gap_analysis: {
            stale: [], thin: [], low_coverage: false,
            uncited_claims: [], contradictions: [], missing_topics: [],
          },
        },
        items: [
          {
            object_type: "knowledge_item", object_id: "k1", title: "A", snippet: null,
            score: 0.9, evidence: { kind: "lexical_match" }, matched_fields: ["title"],
            source_refs: [{ source_connection_id: "src-1" }],
          },
          {
            object_type: "knowledge_item", object_id: "k2", title: "B", snippet: null,
            score: 0.8, evidence: { kind: "lexical_match" }, matched_fields: ["title"],
            source_refs: [{ source_connection_id: "src-1" }, { source_connection_id: "src-2" }],
          },
          {
            object_type: "knowledge_item", object_id: "k3", title: "C", snippet: null,
            score: 0.7, evidence: { kind: "lexical_match" }, matched_fields: ["title"],
          },
        ],
        total: 3,
      },
    });

    expect((spec.metadata_json as { source_connection_ids: string[] }).source_connection_ids.sort())
      .toEqual(["src-1", "src-2"]);
  });

  it("persists retrieval_brief artifacts into the existing artifacts table shape", async () => {
    const calls: unknown[][] = [];
    const db = {
      async query(_sql: string, params?: readonly unknown[]) {
        calls.push([_sql, params]);
        return { rows: [], rowCount: 1 };
      },
    };

    const id = await persistRetrievalBriefArtifact(db, {
      spaceId: "space-1",
      ownerUserId: "user-1",
      runId: null,
      projectId: null,
      query: "alpha",
      maxResults: 3,
      mode: "hybrid",
      includeTrace: false,
      surface: "knowledge_brief",
      egressPolicySnapshot: { external_egress_enabled: true },
      response: {
        brief: {
          answer: null,
          synthesized: false,
          citations: [],
          gap_analysis: {
            stale: [],
            thin: [],
            low_coverage: true,
            uncited_claims: [],
            contradictions: [],
            missing_topics: [],
          },
        },
        items: [],
        total: 0,
      },
    });

    expect(id).toEqual(expect.any(String));
    const params = calls[0]?.[1] as unknown[];
    expect(params[1]).toBe("space-1");
    expect(params[2]).toBeNull();
    expect(params[4]).toBe("retrieval_brief");
    expect(params[5]).toBe("Context Brief: alpha");
    expect(params[14]).toBe("private");
    expect(params[15]).toBe("user-1");
    expect(JSON.parse(String(params[13]))).toMatchObject({
      query: "alpha",
      visibility: "private",
      egress_policy_snapshot: { external_egress_enabled: true },
    });
  });

  it("keeps Memory and Project brief artifacts private without copying snippets or traces", () => {
    const memorySpec = buildRetrievalBriefArtifactSpec({
      spaceId: "space-1",
      ownerUserId: "user-1",
      runId: null,
      projectId: null,
      query: "alpha",
      objectTypes: ["memory_entry"],
      maxResults: 3,
      mode: "hybrid",
      includeTrace: true,
      surface: "memory_retrieval_brief",
      persistTrace: false,
      egressPolicySnapshot: { external_egress_enabled: false },
      response: {
        brief: {
          answer: null,
          synthesized: false,
          citations: [{ object_type: "memory_entry", object_id: "m1", title: "Visible title" }],
          gap_analysis: {
            stale: [],
            thin: [],
            low_coverage: false,
            uncited_claims: [],
            contradictions: [],
            missing_topics: [],
          },
        },
        items: [
          {
            object_type: "memory_entry",
            object_id: "m1",
            title: "Visible title",
            snippet: "private detail that must not persist",
            score: 0.7,
            evidence: { kind: "lexical_match" },
            matched_fields: ["title"],
            source_refs: [{ source_type: "memory_entry", source_id: "m1" }],
          },
        ],
        total: 1,
        trace: { raw: "trace detail that should not persist" },
      },
    });
    const memoryPayload = JSON.parse(memorySpec.content);

    expect(memoryPayload).toMatchObject({
      visibility: "private",
      owner_user_id: "user-1",
      surface: "memory_retrieval_brief",
      object_types: ["memory_entry"],
      trace: null,
      item_refs: [
        {
          object_type: "memory_entry",
          object_id: "m1",
          title: "Visible title",
        },
      ],
    });
    expect(memoryPayload.item_refs[0]).not.toHaveProperty("snippet");
    expect(JSON.stringify(memoryPayload)).not.toContain("private detail that must not persist");
    expect(JSON.stringify(memoryPayload)).not.toContain("trace detail that should not persist");

    const projectSpec = buildRetrievalBriefArtifactSpec({
      spaceId: "space-1",
      ownerUserId: "user-1",
      runId: null,
      projectId: null,
      query: "roadmap",
      objectTypes: ["project_public_summary"],
      maxResults: 3,
      mode: "hybrid",
      includeTrace: true,
      surface: "project_public_summary_brief",
      persistTrace: false,
      egressPolicySnapshot: { external_egress_enabled: true },
      response: {
        brief: {
          answer: null,
          synthesized: false,
          citations: [],
          gap_analysis: {
            stale: [],
            thin: [],
            low_coverage: true,
            uncited_claims: [],
            contradictions: [],
            missing_topics: [],
          },
        },
        items: [],
        total: 0,
        trace: { raw: "project trace" },
      },
    });
    const projectPayload = JSON.parse(projectSpec.content);

    expect(projectPayload).toMatchObject({
      visibility: "private",
      surface: "project_public_summary_brief",
      object_types: ["project_public_summary"],
      trace: null,
    });
  });

  it("requires an owner for owner-private retrieval_brief artifacts", () => {
    expect(() =>
      buildRetrievalBriefArtifactSpec({
        spaceId: "space-1",
        ownerUserId: "",
        runId: null,
        projectId: null,
        query: "alpha",
        maxResults: 3,
        mode: "hybrid",
        includeTrace: false,
        surface: "knowledge_brief",
        egressPolicySnapshot: { external_egress_enabled: true },
        response: {
          brief: {
            answer: null,
            synthesized: false,
            citations: [],
            gap_analysis: {
              stale: [],
              thin: [],
              low_coverage: true,
              uncited_claims: [],
              contradictions: [],
              missing_topics: [],
            },
          },
          items: [],
          total: 0,
        },
      }),
    ).toThrow("owner_user_id");
  });
});
