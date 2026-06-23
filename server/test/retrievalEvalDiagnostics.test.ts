import { describe, expect, it } from "vitest";
import {
  buildRetrievalEvalDiagnosticsReportFromArtifactMetadata,
  buildRetrievalEvalDiagnosticsReportFromMetadata,
} from "../src/modules/retrieval";

describe("retrieval eval diagnostics", () => {
  it("turns brief gap metadata into aggregate-only eval diagnostics", () => {
    const report = buildRetrievalEvalDiagnosticsReportFromMetadata(
      [
        {
          kind: "retrieval_brief",
          surface: "knowledge_brief",
          synthesized: true,
          source_count: 1,
          gap_analysis: {
            low_coverage: true,
            stale: [{ object_id: "secret-k1", title: "Secret Source" }],
            thin: [],
            uncited_claims: ["private uncited claim"],
            contradictions: ["private contradiction"],
            missing_topics: ["private topic"],
          },
          item_refs: [
            {
              object_type: "knowledge_item",
              object_id: "secret-k1",
              title: "Secret Source",
              score: 0.8,
              matched_fields: ["title"],
            },
          ],
        },
      ],
      {
        spaceId: "space-1",
        ownerUserId: "user-1",
        windowDays: 30,
        limit: 200,
      },
    );

    expect(report).toMatchObject({
      source: "product_diagnostic",
      suite: "retrieval_quality_feedback_loop",
      counts: {
        briefs_total: 1,
        low_coverage_briefs: 1,
        uncited_claims_total: 1,
        contradictions_total: 1,
        missing_topics_total: 1,
        stale_refs_total: 1,
        "object_type.knowledge_item": 1,
      },
      diagnostic_codes: [
        "low_coverage",
        "uncited_claims",
        "contradictions",
        "missing_topics",
        "stale_sources",
      ],
    });
    expect(report.rank_attribution.matched_field_counts).toEqual({ title: 1 });
    expect(JSON.stringify(report)).not.toContain("secret-k1");
    expect(JSON.stringify(report)).not.toContain("Secret Source");
    expect(JSON.stringify(report)).not.toContain("private uncited claim");
  });

  it("merges maintenance reports and previous-window trends without object details", () => {
    const report = buildRetrievalEvalDiagnosticsReportFromArtifactMetadata(
      [
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: true, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: false, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
        {
          artifactType: "retrieval_maintenance_report",
          metadata: {
            kind: "retrieval_maintenance_report",
            counts: { duplicate: 1, thin: 2 },
            findings: [
              { objects: [{ object_id: "secret-item", title: "Secret Item" }] },
            ],
          },
        },
        {
          artifactType: "retrieval_maintenance_report",
          metadata: {
            kind: "retrieval_maintenance_report",
            counts: { stale: 1 },
          },
        },
      ],
      {
        spaceId: "space-1",
        ownerUserId: "user-1",
        windowDays: 7,
        limit: 50,
      },
      [
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: false, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: false, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
        {
          artifactType: "retrieval_maintenance_report",
          metadata: {
            kind: "retrieval_maintenance_report",
            counts: { duplicate: 1 },
          },
        },
        {
          artifactType: "retrieval_maintenance_report",
          metadata: {
            kind: "retrieval_maintenance_report",
            counts: { thin: 1 },
          },
        },
      ],
    );

    expect(report.counts).toMatchObject({
      briefs_total: 2,
      maintenance_reports_total: 2,
      maintenance_findings_total: 4,
      "maintenance.duplicate": 1,
      "maintenance.thin": 2,
      previous_briefs_total: 2,
      previous_maintenance_reports_total: 2,
      "trend.brief_sample_sufficient": 1,
      "trend.maintenance_sample_sufficient": 1,
      "trend.maintenance_findings_delta": 2,
    });
    expect(report.metrics).toMatchObject({
      "trend.low_coverage_rate_delta": 0.5,
      "trend.maintenance_findings_per_report_delta": 1,
    });
    expect(report.diagnostic_codes).toEqual(expect.arrayContaining([
      "low_coverage",
      "maintenance_findings_present",
      "trend_low_coverage_worse",
      "trend_maintenance_findings_worse",
    ]));
    expect(JSON.stringify(report)).not.toContain("secret-item");
    expect(JSON.stringify(report)).not.toContain("Secret Item");
  });

  it("excludes prior product diagnostics reports from eval aggregation", () => {
    const report = buildRetrievalEvalDiagnosticsReportFromArtifactMetadata(
      [
        {
          artifactType: "retrieval_eval_report",
          metadata: {
            source: "product_diagnostic",
            suite: "retrieval_quality_feedback_loop",
            metrics: { low_coverage_rate: 1 },
            diagnostic_codes: ["low_coverage"],
          },
        },
        {
          artifactType: "retrieval_eval_report",
          metadata: {
            source: "retrieval_bench",
            suite: "golden",
            metrics: { recall: 0.75 },
            diagnostic_codes: ["top_ranked"],
          },
        },
      ],
      {
        spaceId: "space-1",
        ownerUserId: "user-1",
        windowDays: 30,
        limit: 200,
      },
    );

    expect(report.counts).toMatchObject({
      eval_reports_total: 1,
      "eval_code.top_ranked": 1,
    });
    expect(report.counts).not.toHaveProperty("eval_code.low_coverage");
    expect(report.metrics).toMatchObject({
      "eval_avg.recall": 0.75,
    });
    expect(report.metrics).not.toHaveProperty("eval_avg.low_coverage_rate");
  });

  it("marks trend samples insufficient instead of emitting worse trend codes", () => {
    const report = buildRetrievalEvalDiagnosticsReportFromArtifactMetadata(
      [
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: true, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
      ],
      {
        spaceId: "space-1",
        ownerUserId: "user-1",
        windowDays: 7,
        limit: 50,
      },
      [
        {
          artifactType: "retrieval_brief",
          metadata: {
            kind: "retrieval_brief",
            synthesized: true,
            source_count: 1,
            gap_analysis: { low_coverage: false, stale: [], thin: [], uncited_claims: [], contradictions: [], missing_topics: [] },
            item_refs: [],
          },
        },
      ],
    );

    expect(report.counts).toMatchObject({
      "trend.brief_sample_sufficient": 0,
      "trend.min_briefs": 2,
    });
    expect(report.diagnostic_codes).toContain("insufficient_trend_sample");
    expect(report.diagnostic_codes).not.toContain("trend_low_coverage_worse");
    expect(report.metrics).not.toHaveProperty("trend.low_coverage_rate_delta");
  });
});
