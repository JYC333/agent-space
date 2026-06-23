import { describe, expect, it } from "vitest";
import { scanObjectSchemaSuggestions } from "../src/modules/knowledge/objectSchemaSuggestions";
import type { QueryResult, Queryable } from "../src/modules/routeUtils/common";

class FakeObjectSchemaSuggestionDb implements Queryable {
  async query<Row = Record<string, unknown>>(sql: string): Promise<QueryResult<Row>> {
    if (/\b(?:content|plain_text|raw_text|claim_text|summary)\b/.test(sql)) {
      throw new Error("object schema suggestion scan must not select raw content columns");
    }
    if (/s\.status/.test(sql)) throw new Error("source usage must read status from space_objects, not sources");
    if (/FROM sources s/.test(sql) && /so\.status = 'active'/.test(sql)) {
      throw new Error("source space_object status must use the source lifecycle, not active");
    }
    if (/FROM space_object_kinds/.test(sql)) {
      return {
        rows: [
          {
            id: "kind-decision",
            key: "decision",
            label: "Decision",
            base_object_type: "knowledge_item",
            status: "deprecated",
            version: 2,
          },
          {
            id: "kind-lesson",
            key: "lesson",
            label: "Lesson",
            base_object_type: "knowledge_item",
            status: "active",
            version: 1,
          },
        ] as Row[],
        rowCount: 2,
      };
    }
    if (/FROM knowledge_items ki/.test(sql)) {
      return {
        rows: [
          { object_id: "decision-1", object_kind: "decision" },
          { object_id: "decision-2", object_kind: "decision" },
          { object_id: "decision-3", object_kind: "decision" },
          { object_id: "procedure-1", object_kind: "procedure" },
          { object_id: "procedure-2", object_kind: "procedure" },
          { object_id: "summary-hidden", object_kind: "summary" },
        ] as Row[],
        rowCount: 6,
      };
    }
    if (/FROM provenance_links pl/.test(sql)) {
      return {
        rows: [{ target_id: "summary-hidden", source_connection_id: "source-restricted" }] as Row[],
        rowCount: 1,
      };
    }
    if (/FROM source_connections/.test(sql)) {
      return {
        rows: [{
          id: "source-restricted",
          owner_user_id: "owner-1",
          consent_json: {
            schema_version: 1,
            owner_user_id: "owner-1",
            allowed_reader_user_ids: ["owner-1"],
            allowed_agent_ids: [],
            allow_space_admins: false,
            allow_local_provider_egress: false,
            allow_external_model_egress: false,
          },
          policy_json: {
            schema_version: 1,
            source_egress_class: "internal_only",
            retention_policy: "full_text",
            import_trust_level: "normal",
            derived_write_policy: "proposal_required",
            allowed_import_targets: ["knowledge"],
            revalidation: { required: true, viewer_scoped: true },
          },
        }] as Row[],
        rowCount: 1,
      };
    }
    if (/FROM space_memberships/.test(sql)) {
      return { rows: [{ role: "member" }] as Row[], rowCount: 1 };
    }
    if (/FROM claims c/.test(sql)) {
      return {
        rows: [
          { object_id: "claim-1", object_kind: "fact" },
          { object_id: "claim-hidden", object_kind: "belief" },
        ] as Row[],
        rowCount: 2,
      };
    }
    if (/FROM claim_sources/.test(sql)) {
      return {
        rows: [
          {
            claim_id: "claim-hidden",
            source_connection_id: "source-restricted",
            source_metadata_json: {},
          },
        ] as Row[],
        rowCount: 1,
      };
    }
    if (/FROM sources s/.test(sql)) {
      return {
        rows: [
          { object_id: "source-1", object_kind: "paper", metadata_json: {} },
          {
            object_id: "source-hidden",
            object_kind: "email",
            metadata_json: { source_connection_id: "source-restricted" },
          },
        ] as Row[],
        rowCount: 2,
      };
    }
    if (/FROM intake_items/.test(sql)) {
      return { rows: [] as Row[], rowCount: 0 };
    }
    return { rows: [] as Row[], rowCount: 0 };
  }
}

describe("scanObjectSchemaSuggestions", () => {
  it("creates deterministic review findings from visible kind usage only", async () => {
    const report = await scanObjectSchemaSuggestions(new FakeObjectSchemaSuggestionDb(), {
      spaceId: "space-1",
      userId: "user-1",
      request: {
        base_object_types: ["knowledge_item"],
        limit: 100,
        persist_artifact: false,
        review_scope: "private",
      },
    });

    expect(report.findings.map((finding) => finding.kind).sort()).toEqual([
      "deprecated_kind_usage",
      "missing_object_kind",
      "unused_active_kind",
    ]);
    expect(report.findings.find((finding) => finding.kind === "missing_object_kind")?.proposed_action).toMatchObject({
      proposal_type: "object_kind_create",
      key: "procedure",
      status: "draft",
    });
    expect(report.findings.some((finding) => finding.object_kind === "summary")).toBe(false);
    expect(report.counts).toMatchObject({
      missing_object_kind: 1,
      deprecated_kind_usage: 1,
      unused_active_kind: 1,
    });
    expect(report.access_safety).toEqual({
      only_visible_usage: true,
      raw_content_read: false,
      hidden_counts_included: false,
      provider_call_performed: false,
      canonical_write_performed: false,
    });
  });

  it("default scan covers claim/source SQL without reading raw content", async () => {
    const report = await scanObjectSchemaSuggestions(new FakeObjectSchemaSuggestionDb(), {
      spaceId: "space-1",
      userId: "user-1",
      request: {
        limit: 100,
        persist_artifact: false,
        review_scope: "private",
      },
    });

    const objectKinds = report.findings.map((finding) => finding.object_kind);
    expect(objectKinds).toEqual(expect.arrayContaining(["fact", "paper"]));
    expect(objectKinds).not.toEqual(expect.arrayContaining(["summary", "belief", "email"]));
    expect(report.access_safety.raw_content_read).toBe(false);
  });
});
