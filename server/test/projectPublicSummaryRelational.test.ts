import { describe, expect, it } from "vitest";
import { projectRetrievalRegistry } from "../src/modules/projects/retrievalAdapter";
import { normalizeAlias, RetrievalSearchService } from "../src/modules/retrieval";
import type { Queryable } from "../src/modules/routeUtils/common";

const SPACE = "11111111-1111-4111-8111-111111111111";
const VIEWER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT = "22222222-2222-4222-8222-222222222222";

class ProjectRelationalFakeDb implements Queryable {
  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    const norm = sql.replace(/\s+/g, " ").trim();
    if (norm.includes("FROM retrieval_aliases ra")) {
      const [spaceId, objectTypes, aliases] = params as [string, string[], string[]];
      const matches = spaceId === SPACE &&
        objectTypes.includes("project_public_summary") &&
        aliases.includes(normalizeAlias("Cross Project Discovery"));
      return result((matches ? [{
        object_type: "project_public_summary",
        object_id: PROJECT,
        title: "Aster",
        snippet: "Redacted project summary for cross-project discovery.",
        matched_text: "Cross Project Discovery",
        matched_field: "alias",
        updated_at: "2026-06-22T00:00:00.000Z",
        rank: 1,
      }] : []) as Row[]);
    }
    if (norm.includes("FROM retrieval_chunks rc")) {
      const [spaceId, objectTypes, like] = params as [string, string[], string];
      const needle = like.replace(/%/g, "").toLowerCase();
      const text = "Redacted project summary for cross-project discovery.";
      const matches = spaceId === SPACE &&
        objectTypes.includes("project_public_summary") &&
        text.toLowerCase().includes(needle);
      return result((matches ? [{
        object_type: "project_public_summary",
        object_id: PROJECT,
        title: "Aster",
        snippet: text,
        matched_text: text,
        matched_field: "plain_text",
        updated_at: "2026-06-22T00:00:00.000Z",
        rank: 1,
      }] : []) as Row[]);
    }
    if (norm.includes("FROM retrieval_edges e")) {
      return result([] as Row[]);
    }
    if (norm.includes("FROM project_public_summaries ps")) {
      return result([{
        project_id: PROJECT,
        name: "Aster",
        description: "Public project description",
        current_focus: "Cross-project discovery",
        owner_user_id: VIEWER,
        status: "active",
        summary_text: "Redacted project summary for cross-project discovery.",
        topics_json: ["Cross Project Discovery"],
        highlights_json: ["Approved public summary only."],
        review_status: "approved",
      }] as Row[]);
    }
    throw new Error(`unexpected SQL: ${norm}`);
  }
}

describe("Project public-summary relational retrieval", () => {
  it("uses projects-related intent as a direct target arm when the registry has no non-project seed type", async () => {
    const out = await new RetrievalSearchService(new ProjectRelationalFakeDb(), projectRetrievalRegistry).search({
      spaceId: SPACE,
      viewerUserId: VIEWER,
      objectTypes: ["project_public_summary"],
      query: "projects related to Cross Project Discovery",
      maxResults: 5,
      includeTrace: true,
    });

    expect(out.items.map((item) => item.object_id)).toContain(PROJECT);
    expect(out.items[0]?.matched_fields).toContain("relational:projects_related");
    expect(out.items[0]?.matched_fields).toContain("relational_direct_target");
    expect(out.trace).toMatchObject({
      arms: { relational: 1 },
      relational: { intent: "projects_related", results: 1, hops: 0 },
    });
  });
});

function result<Row>(rows: Row[]) {
  return { rows, rowCount: rows.length };
}
