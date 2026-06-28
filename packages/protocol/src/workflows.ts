/**
 * Workflow framework contracts.
 *
 * Workflow templates compose capabilities. Project workflow profiles are saved
 * project-scoped presets; callers may also build run drafts directly from a
 * template without saving a preset.
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema } from "./common.js";
import { JsonObjectSchema } from "./capabilities.js";

export const WorkflowTemplateSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    description: z.string(),
    category: z.string().min(1),
    capability_ids: z.array(z.string().min(1)),
    input_schema_json: JsonObjectSchema,
    default_config_json: JsonObjectSchema,
    output_artifact_types: z.array(z.string().min(1)),
    proposal_policy: JsonObjectSchema,
    recommended_runtime_adapters: z.array(z.string().min(1)),
  })
  .passthrough();
export type WorkflowTemplate = z.infer<typeof WorkflowTemplateSchema>;

export const ProjectWorkflowProfileSchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    project_id: IdSchema,
    workflow_template_id: z.string().min(1),
    name: z.string().min(1),
    enabled: z.boolean(),
    config_json: JsonObjectSchema,
    created_by_user_id: IdSchema.nullish(),
    created_at: ISODateTimeSchema,
    updated_at: ISODateTimeSchema,
  })
  .passthrough();
export type ProjectWorkflowProfile = z.infer<
  typeof ProjectWorkflowProfileSchema
>;

export const WorkflowRunDraftRequestSchema = z
  .object({
    // The agent that will own the run. A workflow preset does not bind an
    // agent, so the caller chooses one; when omitted the draft is not directly
    // executable and emits the `agent_required_to_execute_run_draft` warning.
    agent_id: IdSchema.nullish(),
    runtime_profile_id: IdSchema.nullish(),
    prompt: z.string().nullish(),
    instruction: z.string().nullish(),
    workspace_id: IdSchema.nullish(),
    session_id: IdSchema.nullish(),
    config_json: JsonObjectSchema.optional(),
  })
  .strict();
export type WorkflowRunDraftRequest = z.infer<
  typeof WorkflowRunDraftRequestSchema
>;

export const WorkflowRunCreateBodyDraftSchema = z
  .object({
    mode: z.literal("live"),
    run_type: z.literal("agent"),
    trigger_origin: z.literal("manual"),
    project_id: IdSchema,
    // Target agent for `POST /api/v1/agents/:agentId/runs`; null until the
    // caller selects one.
    agent_id: IdSchema.nullable(),
    runtime_profile_id: IdSchema.nullish(),
    workspace_id: IdSchema.nullish(),
    session_id: IdSchema.nullish(),
    prompt: z.string().min(1),
    instruction: z.string().nullish(),
    capability_id: z.string().min(1).nullish(),
    capabilities_json: z.array(z.string().min(1)).default([]),
  })
  .passthrough();
export type WorkflowRunCreateBodyDraft = z.infer<
  typeof WorkflowRunCreateBodyDraftSchema
>;

export const WorkflowRunDraftResponseSchema = z
  .object({
    workflow_template: WorkflowTemplateSchema,
    workflow_profile: ProjectWorkflowProfileSchema.nullable(),
    capability_ids: z.array(z.string().min(1)),
    output_artifact_types: z.array(z.string().min(1)),
    config_json: JsonObjectSchema,
    run_create_body: WorkflowRunCreateBodyDraftSchema,
    warnings: z.array(z.string().min(1)),
  })
  .passthrough();
export type WorkflowRunDraftResponse = z.infer<
  typeof WorkflowRunDraftResponseSchema
>;
