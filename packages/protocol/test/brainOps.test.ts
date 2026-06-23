import { describe, expect, it } from "vitest";
import {
  BrainOpsDreamCycleV2RequestSchema,
  BrainOpsDreamCycleV2ResponseSchema,
  BrainOpsDrilldownSchema,
  BrainOpsSummarySchema,
} from "../src/brainOps";

describe("brain ops contracts", () => {
  it("parses Dream Cycle Lite v2 request and response contracts", () => {
    const request = BrainOpsDreamCycleV2RequestSchema.parse({});
    expect(request.create_packets).toBe(true);
    expect(request.review_scope).toBe("private");

    const response = BrainOpsDreamCycleV2ResponseSchema.parse({
      artifact_id: "artifact-dream",
      review_scope: "private",
      retrieval_maintenance: {
        artifact_id: "artifact-maintenance",
        proposal_id: "proposal-maintenance",
        finding_count: 2,
        counts: { stale: 1, thin: 1 },
        scanned: 10,
        truncated: false,
      },
      diagnostics: {
        artifact_id: "artifact-diagnostics",
        proposal_id: "proposal-diagnostics",
        diagnostic_codes: ["uncited_claims"],
        counts: { uncited_claims_total: 1 },
      },
      memory_maintenance: {
        artifact_id: null,
        proposal_id: null,
        finding_count: 0,
        counts: {},
        scanned: 0,
        truncated: false,
      },
      claim_candidates: {
        artifact_id: "artifact-claim-candidates",
        proposal_id: "proposal-claim-candidates",
        candidate_count: 1,
        generated_child_proposal_count: 0,
      },
      source_health: {
        active_source_connections: 1,
        missing_consent_version_count: 0,
        reader_restricted_source_count: 0,
        external_egress_disabled_source_count: 0,
        derived_writes_disabled_source_count: 0,
        warning_counts: {},
      },
      projection_freshness: {
        object_counts: { claim: 1 },
        stale_projection_count: 0,
        source_connected_object_count: 1,
        oldest_indexed_at: null,
        newest_indexed_at: null,
        newest_source_updated_at: null,
      },
      embedding_backlog: {
        total_chunks: 1,
        embedded_chunks: 1,
        missing_embedding_chunks: 0,
        claimed_chunks: 0,
        attempted_chunks: 0,
        missing_by_object_type: {},
      },
      degraded: false,
      warnings: [],
      canonical_write_performed: false,
    });
    expect(response.claim_candidates.candidate_count).toBe(1);
    expect(response.warnings).toEqual([]);
  });

  it("parses aggregate brain ops summaries", () => {
    const parsed = BrainOpsSummarySchema.parse({
      generated_at: "2026-06-25T12:00:00.000Z",
      space_id: "space-1",
      owner_user_id: "user-1",
      window_days: 14,
      index_freshness: {
        object_counts: { knowledge_item: 2, claim: 1 },
        stale_projection_count: 1,
        source_connected_object_count: 2,
        oldest_indexed_at: "2026-06-01T00:00:00.000Z",
        newest_indexed_at: "2026-06-25T00:00:00.000Z",
        newest_source_updated_at: null,
      },
      embedding_backlog: {
        total_chunks: 10,
        embedded_chunks: 7,
        missing_embedding_chunks: 3,
        claimed_chunks: 1,
        attempted_chunks: 2,
        missing_by_object_type: { claim: 3 },
      },
      source_policy_warnings: {
        active_source_connections: 4,
        missing_consent_version_count: 1,
        reader_restricted_source_count: 2,
        external_egress_disabled_source_count: 3,
        derived_writes_disabled_source_count: 1,
        warning_counts: {
          missing_consent_version: 1,
          reader_restricted_source: 2,
          external_egress_disabled_source: 3,
          derived_writes_disabled_source: 1,
        },
      },
      maintenance: {
        recent_report_count: 1,
        finding_counts: { duplicate: 2 },
        pending_packet_count: 1,
        recent_packets: [
          {
            proposal_id: "proposal-1",
            proposal_type: "memory_maintenance_packet",
            status: "pending",
            title: "Memory maintenance",
            created_at: "2026-06-25T01:00:00.000Z",
            report_artifact_id: "artifact-1",
          },
        ],
      },
      diagnostics: {
        recent_report_count: 1,
        diagnostic_code_counts: { low_coverage: 1 },
        latest_report_artifact_id: "artifact-2",
        latest_generated_at: "2026-06-25T02:00:00.000Z",
        trend_metric_deltas: { recall_delta: -0.2 },
        insufficient_trend_sample: false,
      },
      recent_context_briefs: [
        {
          artifact_id: "artifact-3",
          artifact_type: "retrieval_brief",
          title: "Context Brief",
          created_at: "2026-06-25T03:00:00.000Z",
          surface: "knowledge_brief",
          diagnostic_codes: [],
          finding_count: null,
        },
      ],
      retrieval_feedback: {
        recent_event_count: 3,
        signal_counts: { opened: 2, used: 1 },
        surface_counts: { knowledge_brief: 3 },
        window_days: 14,
      },
      memory_provenance: {
        recent_access_count: 5,
        context_injection_count: 3,
        maintenance_scan_count: 1,
        inspector_available: false,
      },
    });

    expect(parsed.index_freshness.object_counts.claim).toBe(1);
  });

  it("parses object and source drill-downs and rejects unknown sections", () => {
    const objects = BrainOpsDrilldownSchema.parse({
      generated_at: "2026-06-26T00:00:00.000Z",
      space_id: "space-1",
      section: "embedding_backlog",
      limit: 25,
      truncated: false,
      objects: [
        {
          object_type: "knowledge_item",
          object_id: "obj-1",
          title: "Onboarding notes",
          indexed_at: "2026-06-20T00:00:00.000Z",
          source_updated_at: null,
          missing_chunk_count: 4,
        },
      ],
      sources: [],
    });
    expect(objects.objects[0].missing_chunk_count).toBe(4);

    const sources = BrainOpsDrilldownSchema.parse({
      generated_at: "2026-06-26T00:00:00.000Z",
      space_id: "space-1",
      section: "source_warnings",
      limit: 25,
      truncated: true,
      sources: [
        {
          source_connection_id: "src-1",
          name: "Notion",
          owner_user_id: "user-1",
          status: "active",
          warnings: ["external_egress_disabled"],
        },
      ],
    });
    expect(sources.objects).toEqual([]);
    expect(sources.sources[0].warnings).toContain("external_egress_disabled");

    const explain = BrainOpsDrilldownSchema.parse({
      generated_at: "2026-06-26T00:00:00.000Z",
      space_id: "space-1",
      section: "explain_reports",
      limit: 10,
      truncated: false,
      artifacts: [
        {
          artifact_id: "artifact-explain",
          artifact_type: "retrieval_explain_report",
          title: "Retrieval Explain Report",
          created_at: "2026-06-26T00:00:00.000Z",
          surface: null,
          diagnostic_codes: ["target_returned"],
          finding_count: null,
        },
      ],
    });
    expect(explain.section).toBe("explain_reports");

    expect(() =>
      BrainOpsDrilldownSchema.parse({
        generated_at: "2026-06-26T00:00:00.000Z",
        space_id: "space-1",
        section: "raw_dump",
        limit: 25,
        truncated: false,
      }),
    ).toThrow();
  });
});
