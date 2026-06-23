/**
 * Brain Ops read-model contracts.
 *
 * These schemas describe aggregate, UI-facing brain health summaries. They do
 * not expose raw retrieval candidates, snippets, private memory text, or hidden
 * object counts.
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema, SecretResponseGuards } from "./common.js";

export const BrainOpsCountMapSchema = z.record(z.number().int().nonnegative());
export type BrainOpsCountMap = z.infer<typeof BrainOpsCountMapSchema>;

export const BrainOpsTimestampSchema = ISODateTimeSchema.nullable();

export const BrainOpsIndexFreshnessSchema = z
  .object({
    object_counts: BrainOpsCountMapSchema,
    stale_projection_count: z.number().int().nonnegative(),
    source_connected_object_count: z.number().int().nonnegative(),
    oldest_indexed_at: BrainOpsTimestampSchema,
    newest_indexed_at: BrainOpsTimestampSchema,
    newest_source_updated_at: BrainOpsTimestampSchema,
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsIndexFreshness = z.infer<typeof BrainOpsIndexFreshnessSchema>;

export const BrainOpsEmbeddingBacklogSchema = z
  .object({
    total_chunks: z.number().int().nonnegative(),
    embedded_chunks: z.number().int().nonnegative(),
    missing_embedding_chunks: z.number().int().nonnegative(),
    claimed_chunks: z.number().int().nonnegative(),
    attempted_chunks: z.number().int().nonnegative(),
    missing_by_object_type: BrainOpsCountMapSchema,
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsEmbeddingBacklog = z.infer<typeof BrainOpsEmbeddingBacklogSchema>;

export const BrainOpsSourcePolicyWarningsSchema = z
  .object({
    active_source_connections: z.number().int().nonnegative(),
    missing_consent_version_count: z.number().int().nonnegative(),
    reader_restricted_source_count: z.number().int().nonnegative(),
    external_egress_disabled_source_count: z.number().int().nonnegative(),
    derived_writes_disabled_source_count: z.number().int().nonnegative(),
    warning_counts: BrainOpsCountMapSchema,
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsSourcePolicyWarnings = z.infer<typeof BrainOpsSourcePolicyWarningsSchema>;

export const BrainOpsArtifactSummarySchema = z
  .object({
    artifact_id: IdSchema,
    artifact_type: z.string(),
    title: z.string(),
    created_at: ISODateTimeSchema,
    surface: z.string().nullable(),
    diagnostic_codes: z.array(z.string()).default([]),
    finding_count: z.number().int().nonnegative().nullable(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsArtifactSummary = z.infer<typeof BrainOpsArtifactSummarySchema>;

export const BrainOpsPacketSummarySchema = z
  .object({
    proposal_id: IdSchema,
    proposal_type: z.string(),
    status: z.string(),
    title: z.string(),
    created_at: ISODateTimeSchema,
    report_artifact_id: IdSchema.nullable(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsPacketSummary = z.infer<typeof BrainOpsPacketSummarySchema>;

export const BrainOpsMaintenanceSummarySchema = z
  .object({
    recent_report_count: z.number().int().nonnegative(),
    finding_counts: BrainOpsCountMapSchema,
    pending_packet_count: z.number().int().nonnegative(),
    recent_packets: z.array(BrainOpsPacketSummarySchema),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsMaintenanceSummary = z.infer<typeof BrainOpsMaintenanceSummarySchema>;

export const BrainOpsDiagnosticsSummarySchema = z
  .object({
    recent_report_count: z.number().int().nonnegative(),
    diagnostic_code_counts: BrainOpsCountMapSchema,
    latest_report_artifact_id: IdSchema.nullable(),
    latest_generated_at: BrainOpsTimestampSchema,
    trend_metric_deltas: z.record(z.number()),
    insufficient_trend_sample: z.boolean(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsDiagnosticsSummary = z.infer<typeof BrainOpsDiagnosticsSummarySchema>;

export const BrainOpsRetrievalFeedbackSummarySchema = z
  .object({
    recent_event_count: z.number().int().nonnegative(),
    signal_counts: BrainOpsCountMapSchema,
    surface_counts: BrainOpsCountMapSchema,
    window_days: z.number().int().positive(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsRetrievalFeedbackSummary = z.infer<typeof BrainOpsRetrievalFeedbackSummarySchema>;

export const BrainOpsMemoryProvenanceSummarySchema = z
  .object({
    recent_access_count: z.number().int().nonnegative(),
    context_injection_count: z.number().int().nonnegative(),
    maintenance_scan_count: z.number().int().nonnegative(),
    inspector_available: z.boolean(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsMemoryProvenanceSummary = z.infer<typeof BrainOpsMemoryProvenanceSummarySchema>;

export const BrainOpsSummarySchema = z
  .object({
    generated_at: ISODateTimeSchema,
    space_id: IdSchema,
    owner_user_id: IdSchema,
    window_days: z.number().int().positive(),
    index_freshness: BrainOpsIndexFreshnessSchema,
    embedding_backlog: BrainOpsEmbeddingBacklogSchema,
    source_policy_warnings: BrainOpsSourcePolicyWarningsSchema,
    maintenance: BrainOpsMaintenanceSummarySchema,
    diagnostics: BrainOpsDiagnosticsSummarySchema,
    recent_context_briefs: z.array(BrainOpsArtifactSummarySchema),
    retrieval_feedback: BrainOpsRetrievalFeedbackSummarySchema,
    memory_provenance: BrainOpsMemoryProvenanceSummarySchema,
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsSummary = z.infer<typeof BrainOpsSummarySchema>;

/**
 * Brain Ops drill-down contracts (Slice 3).
 *
 * Drill-downs turn an aggregate summary section into a bounded, access-safe
 * detail list. Object-level sections (`index_freshness`, `embedding_backlog`)
 * carry only live-revalidated, viewer-readable objects — title is the
 * authoritative revalidated title, never a projection snippet. The
 * `source_warnings` section carries source connections the viewer owns (or, for
 * owners/admins, all active connections) with policy warning labels only — never
 * consent/credential payloads. No raw retrieval internals, snippets, hidden
 * object ids, or dropped candidate ids cross this boundary.
 */
// Object/source sections list live-revalidated detail; the artifact sections
// (`maintenance_reports`, `diagnostics_reports`, `recent_briefs`) list the
// viewer's own (or allowed `space_ops`) aggregate-safe report/packet summaries so
// the operator can triage a specific finding instead of a bare count.
export const BrainOpsDrilldownSectionSchema = z.enum([
  "index_freshness",
  "embedding_backlog",
  "source_warnings",
  "maintenance_reports",
  "diagnostics_reports",
  "explain_reports",
  "recent_briefs",
]);
export type BrainOpsDrilldownSection = z.infer<typeof BrainOpsDrilldownSectionSchema>;

export const BrainOpsDrilldownObjectSchema = z
  .object({
    object_type: z.string(),
    object_id: IdSchema,
    title: z.string(),
    indexed_at: BrainOpsTimestampSchema,
    source_updated_at: BrainOpsTimestampSchema,
    missing_chunk_count: z.number().int().nonnegative().nullable(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsDrilldownObject = z.infer<typeof BrainOpsDrilldownObjectSchema>;

export const BrainOpsSourceWarningDetailSchema = z
  .object({
    source_connection_id: IdSchema,
    name: z.string(),
    owner_user_id: IdSchema,
    status: z.string(),
    warnings: z.array(z.string()),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsSourceWarningDetail = z.infer<typeof BrainOpsSourceWarningDetailSchema>;

export const BrainOpsDrilldownSchema = z
  .object({
    generated_at: ISODateTimeSchema,
    space_id: IdSchema,
    section: BrainOpsDrilldownSectionSchema,
    limit: z.number().int().positive(),
    truncated: z.boolean(),
    objects: z.array(BrainOpsDrilldownObjectSchema).default([]),
    sources: z.array(BrainOpsSourceWarningDetailSchema).default([]),
    // Populated only for the artifact sections; aggregate-safe report/packet
    // summaries (ids, types, counts, diagnostic codes), never raw findings.
    artifacts: z.array(BrainOpsArtifactSummarySchema).default([]),
    packets: z.array(BrainOpsPacketSummarySchema).default([]),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsDrilldown = z.infer<typeof BrainOpsDrilldownSchema>;

export const BrainOpsDreamCycleV2RequestSchema = z
  .object({
    window_days: z.number().int().positive().max(90).default(14),
    artifact_limit: z.number().int().positive().max(200).default(50),
    create_packets: z.boolean().default(true),
    review_scope: z.enum(["private", "space_ops"]).default("private"),
    include_memory_maintenance: z.boolean().default(true),
    memory_limit: z.number().int().positive().max(1000).default(500),
    memory_stale_after_days: z.number().int().positive().max(3650).default(180),
    memory_thin_content_chars: z.number().int().positive().max(1000).default(80),
    memory_max_findings: z.number().int().positive().max(200).default(100),
    max_claim_candidates: z.number().int().positive().max(100).default(40),
  })
  .strict();
export type BrainOpsDreamCycleV2Request = z.infer<typeof BrainOpsDreamCycleV2RequestSchema>;

const BrainOpsDreamCycleSectionSchema = z
  .object({
    artifact_id: IdSchema.nullable().optional(),
    proposal_id: IdSchema.nullable().optional(),
    finding_count: z.number().int().nonnegative().optional(),
    candidate_count: z.number().int().nonnegative().optional(),
    generated_child_proposal_count: z.number().int().nonnegative().optional(),
    diagnostic_codes: z.array(z.string()).optional(),
    counts: BrainOpsCountMapSchema.optional(),
    scanned: z.number().int().nonnegative().optional(),
    truncated: z.boolean().optional(),
    error_code: z.string().optional(),
    error_message: z.string().optional(),
    ...SecretResponseGuards,
  })
  .passthrough();

export const BrainOpsDreamCycleWarningSchema = z
  .object({
    stage: z.string(),
    error_code: z.string(),
    message: z.string(),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsDreamCycleWarning = z.infer<typeof BrainOpsDreamCycleWarningSchema>;

export const BrainOpsDreamCycleV2ResponseSchema = z
  .object({
    artifact_id: IdSchema,
    review_scope: z.enum(["private", "space_ops"]),
    retrieval_maintenance: BrainOpsDreamCycleSectionSchema,
    diagnostics: BrainOpsDreamCycleSectionSchema,
    memory_maintenance: BrainOpsDreamCycleSectionSchema,
    claim_candidates: BrainOpsDreamCycleSectionSchema,
    source_health: BrainOpsSourcePolicyWarningsSchema,
    projection_freshness: BrainOpsIndexFreshnessSchema,
    embedding_backlog: BrainOpsEmbeddingBacklogSchema,
    degraded: z.boolean().default(false),
    warnings: z.array(BrainOpsDreamCycleWarningSchema).default([]),
    canonical_write_performed: z.literal(false),
    ...SecretResponseGuards,
  })
  .strict();
export type BrainOpsDreamCycleV2Response = z.infer<typeof BrainOpsDreamCycleV2ResponseSchema>;
