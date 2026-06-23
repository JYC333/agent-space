import { z } from "zod";
import { IdSchema, ISODateTimeSchema, SecretResponseGuards } from "./common.js";

// ---------------------------------------------------------------------------
// Project public summary contracts
//
// The Project Public Summary is the deliberately sanitized, space-public
// discovery layer for a project (see PROJECTS.md / SECURITY_AND_ACCESS_BOUNDARIES.md).
// It is intentionally separate from concrete project memory: it carries only
// high-level redacted fields and pointer-only source refs. These contracts are
// the wire shape for the `/api/v1/projects/.../public-summary*` routes.
// ---------------------------------------------------------------------------

export const ProjectPublicSummaryReviewStatusSchema = z.enum([
  "draft",
  "approved",
  "archived",
]);
export type ProjectPublicSummaryReviewStatus = z.infer<
  typeof ProjectPublicSummaryReviewStatusSchema
>;

/** Pointer-only provenance ref. Must never embed raw source content. */
export const ProjectPublicSummarySourceRefSchema = z
  .object({
    source_type: z.string().min(1),
    source_id: z.string().min(1),
    label: z.string().optional(),
    trust_level: z.string().optional(),
  })
  .passthrough();
export type ProjectPublicSummarySourceRef = z.infer<
  typeof ProjectPublicSummarySourceRefSchema
>;

export const ProjectPublicSummarySchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    project_id: IdSchema,
    project_name: z.string(),
    summary_text: z.string(),
    topics: z.array(z.string()).default([]),
    highlights: z.array(z.string()).default([]),
    source_refs: z.array(z.record(z.unknown())).default([]),
    redaction_version: z.string(),
    review_status: ProjectPublicSummaryReviewStatusSchema,
    updated_by_user_id: IdSchema.nullable(),
    generated_by_run_id: IdSchema.nullable(),
    created_at: ISODateTimeSchema,
    updated_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type ProjectPublicSummary = z.infer<typeof ProjectPublicSummarySchema>;

export const ProjectPublicSummaryListResponseSchema = z
  .object({
    items: z.array(ProjectPublicSummarySchema).default([]),
    total: z.number().int().nonnegative(),
    limit: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ProjectPublicSummaryListResponse = z.infer<
  typeof ProjectPublicSummaryListResponseSchema
>;

/**
 * PUT body. A bare write stages a `draft`; `review_status` other than `draft`
 * is a publish/unpublish action and is gated to project-owner-level authority
 * server-side. Legacy `*_json` aliases are accepted and pass through.
 */
export const ProjectPublicSummaryUpsertRequestSchema = z
  .object({
    summary_text: z.string().trim().min(1).max(4000),
    topics: z.array(z.string()).optional(),
    highlights: z.array(z.string()).optional(),
    source_refs: z.array(ProjectPublicSummarySourceRefSchema).optional(),
    review_status: ProjectPublicSummaryReviewStatusSchema.optional(),
    redaction_version: z.string().optional(),
    generated_by_run_id: IdSchema.optional(),
  })
  .passthrough();
export type ProjectPublicSummaryUpsertRequest = z.infer<
  typeof ProjectPublicSummaryUpsertRequestSchema
>;

/** POST .../public-summary/draft body. All fields optional. */
export const ProjectPublicSummaryDraftRequestSchema = z
  .object({
    model_provider_id: IdSchema.optional(),
    provider_id: IdSchema.optional(),
    model: z.string().optional(),
    max_tokens: z.number().int().positive().max(8000).optional(),
    generated_by_run_id: IdSchema.optional(),
  })
  .passthrough();
export type ProjectPublicSummaryDraftRequest = z.infer<
  typeof ProjectPublicSummaryDraftRequestSchema
>;
