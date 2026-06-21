/**
 * Open Skill import contracts.
 *
 * External skill packages are untrusted source material. These schemas describe
 * preview, persistence, and conversion request/response shapes only.
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema } from "./common.js";
import { JsonObjectSchema } from "./capabilities.js";
import { ProposalOutSchema } from "./proposals.js";

export const SkillSourceTypeSchema = z.enum([
  "github",
  "registry",
  "local_workspace",
  "upload",
  "builtin",
]);
export type SkillSourceType = z.infer<typeof SkillSourceTypeSchema>;

export const SkillRiskLevelSchema = z.enum(["low", "medium", "high", "critical"]);
export type SkillRiskLevel = z.infer<typeof SkillRiskLevelSchema>;

export const SkillPackageStatusSchema = z.enum([
  "imported",
  "reviewed",
  "rejected",
  "converted",
  "archived",
  "superseded",
]);
export type SkillPackageStatus = z.infer<typeof SkillPackageStatusSchema>;

export const NormalizedSkillResourceSchema = z
  .object({
    path: z.string().min(1),
    kind: z.string().min(1),
    description: z.string().nullish(),
    content_hash: z.string().nullish(),
    content_type: z.string().nullish(),
    byte_length: z.number().int().nonnegative().nullish(),
  })
  .passthrough();
export type NormalizedSkillResource = z.infer<
  typeof NormalizedSkillResourceSchema
>;

export const NormalizedSkillSchema = z
  .object({
    spec_kind: z.string().nullish(),
    spec_version: z.string().nullish(),
    skill_root: z.string().nullish(),
    package_hash: z.string().nullish(),
    diagnostics: z.array(z.string()).optional(),
    name: z.string().min(1),
    description: z.string().min(1),
    version: z.string().min(1),
    license: z.string().nullable(),
    instructions_markdown: z.string(),
    resources: z.array(NormalizedSkillResourceSchema),
    requested_permissions: z.array(z.string()),
    execution_profile: JsonObjectSchema,
    vendor_extensions: JsonObjectSchema,
    trust_analysis: JsonObjectSchema,
  })
  .passthrough();
export type NormalizedSkill = z.infer<typeof NormalizedSkillSchema>;

export const SkillSourceSchema = z
  .object({
    id: IdSchema,
    source_type: SkillSourceTypeSchema,
    url: z.string().nullable(),
    repo: z.string().nullable(),
    path: z.string().nullable(),
    ref: z.string().nullable(),
    commit_sha: z.string().nullable(),
    content_hash: z.string().min(1),
    fetched_at: ISODateTimeSchema,
    metadata_json: JsonObjectSchema,
  })
  .passthrough();
export type SkillSource = z.infer<typeof SkillSourceSchema>;

export const SkillPackageSchema = z
  .object({
    id: IdSchema,
    source_id: IdSchema,
    package_name: z.string().min(1),
    version: z.string().nullable(),
    license: z.string().nullable(),
    raw_storage_ref: z.string().nullable(),
    manifest_json: JsonObjectSchema,
    normalized_json: JsonObjectSchema,
    risk_level: SkillRiskLevelSchema,
    status: SkillPackageStatusSchema,
    created_at: ISODateTimeSchema,
    updated_at: ISODateTimeSchema,
  })
  .passthrough();
export type SkillPackage = z.infer<typeof SkillPackageSchema>;

export const SkillPackageFilePreviewSchema = z
  .object({
    path: z.string().min(1),
    kind: z.string().min(1),
    content_hash: z.string().nullish(),
    content_type: z.string().nullish(),
    byte_length: z.number().int().nonnegative().nullish(),
    included: z.boolean(),
    executable: z.boolean(),
    risk_flags_json: JsonObjectSchema,
  })
  .passthrough();
export type SkillPackageFilePreview = z.infer<
  typeof SkillPackageFilePreviewSchema
>;

export const SkillPackageFileSchema = SkillPackageFilePreviewSchema.extend({
  id: IdSchema,
  skill_package_id: IdSchema,
  storage_ref: z.string().nullable(),
  created_at: ISODateTimeSchema,
}).passthrough();
export type SkillPackageFile = z.infer<typeof SkillPackageFileSchema>;

export const SkillImportPreviewRequestSchema = z.object({
  url: z.string().min(1),
  source_type: SkillSourceTypeSchema.optional(),
});
export type SkillImportPreviewRequest = z.infer<
  typeof SkillImportPreviewRequestSchema
>;

export const SkillImportPreviewResponseSchema = z
  .object({
    source: SkillSourceSchema.omit({
      id: true,
      fetched_at: true,
    }).partial(),
    normalized_skill: NormalizedSkillSchema,
    package_root: z.string(),
    package_hash: z.string().min(1),
    package_files: z.array(SkillPackageFilePreviewSchema),
    risk_level: SkillRiskLevelSchema,
    requested_permissions: z.array(z.string()),
    files_detected: z.array(z.string()),
    warnings: z.array(z.string()),
    persistable: z.boolean(),
  })
  .passthrough();
export type SkillImportPreviewResponse = z.infer<
  typeof SkillImportPreviewResponseSchema
>;

export const SkillImportRequestSchema = z.object({
  url: z.string().min(1),
  source_type: SkillSourceTypeSchema.optional(),
});
export type SkillImportRequest = z.infer<typeof SkillImportRequestSchema>;

export const SkillConvertToCapabilityRequestSchema = z.object({
  capability_id: z.string().min(1).optional(),
  namespace: z.string().min(1).optional(),
  // Reserved for the future proposal-gated enablement flow (ADR 0011).
  // Conversion currently only produces a disabled draft; supplying this field
  // is rejected until capability enablement goes through proposal review.
  enable_for_project_id: IdSchema.nullish(),
  create_runtime_bindings: z.boolean().default(true),
});
export type SkillConvertToCapabilityRequest = z.infer<
  typeof SkillConvertToCapabilityRequestSchema
>;

export const SkillImportApprovalProposalResponseSchema = ProposalOutSchema;
export type SkillImportApprovalProposalResponse = z.infer<
  typeof SkillImportApprovalProposalResponseSchema
>;

export const SkillConvertToCapabilityResponseSchema = ProposalOutSchema;
export type SkillConvertToCapabilityResponse = z.infer<
  typeof SkillConvertToCapabilityResponseSchema
>;
