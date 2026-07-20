import { describe, expect, it } from "vitest";
import type { Queryable } from "../src/modules/routeUtils/common";
import { resolveResearchReportReferences } from "../src/modules/projectResearch/reportReferenceResolver";

class ReferenceDb implements Queryable {
  constructor(private readonly sourceRows: Record<string, unknown>[]) {}
  async query<Row = Record<string, unknown>>(sql: string, params: readonly unknown[] = []) {
    expect(sql).toContain("content_access_grants");
    expect(sql).toContain("allowed_reader_user_ids");
    expect(params.slice(1)).toEqual(["space-1", "user-1"]);
    const sourceId = params[0]
    const rows = this.sourceRows.filter(row => row.id === sourceId).map(({ id: _id, ...row }) => row) as Row[]
    return { rows, rowCount: rows.length };
  }
}

const identity = { spaceId: "space-1", userId: "user-1" };

describe("research report reference resolution", () => {
  it("returns readable metadata and replaces private source identifiers with stable references", async () => {
    const result = await resolveResearchReportReferences(new ReferenceDb([{
      id: "item-readable", title: "Readable source", metadata_json: { authors: ["Ada", "Lin"], year: 2025 },
      occurred_at: "2025-04-01T00:00:00.000Z", reference_object_id: "paper-1",
    }]), identity, {
      findings: [{ references: [{ source_item_id: "item-readable" }] }], sources: [], ideas: [],
    });
    expect(result.content).toEqual({ findings: [{ references: [{ reference_id: "ref-1" }] }], sources: [], ideas: [] });
    expect(result.resolved).toEqual([{
      id: "ref-1", availability: "available", title: "Readable source", authors: ["Ada", "Lin"], year: 2025,
      library_path: "/library/items/item-readable", academic_path: "/knowledge/sources?object=paper-1",
    }]);
  });

  it("does not disclose any metadata for an inaccessible source", async () => {
    const result = await resolveResearchReportReferences(new ReferenceDb([]), identity, {
      findings: [], sources: [{ references: [{ source_item_id: "secret-item", title: "Secret title" }] }], ideas: [],
    });
    expect(result.content).toEqual({ findings: [], sources: [{ references: [{ reference_id: "ref-1" }] }], ideas: [] });
    expect(result.resolved).toEqual([{ id: "ref-1", availability: "unavailable" }]);
    expect(JSON.stringify(result)).not.toContain("secret-item");
    expect(JSON.stringify(result)).not.toContain("Secret title");
  });
});
