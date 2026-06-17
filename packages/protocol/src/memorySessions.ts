/**
 * Memory + sessions contracts.
 *
 * Schemas only. These contracts describe public wire shapes. They do not create
 * route handlers or move authority.
 */

import { z } from "zod";
import { IdSchema, ISODateTimeSchema, SecretResponseGuards } from "./common.js";
import { TraceSafeJsonSchema } from "./runOrchestration.js";

const JsonObjectSchema = z.record(z.unknown());
const TraceSafeObjectSchema = TraceSafeJsonSchema.refine(
  (value) => value !== null && typeof value === "object" && !Array.isArray(value),
  "Expected trace-safe object",
);
const TraceSafeArraySchema = z.array(TraceSafeJsonSchema);
const RawContextResponseGuards = {
  compiled_prefix_text: z.never().optional(),
  compiled_tail_text: z.never().optional(),
  rendered_context_text: z.never().optional(),
};

export const SessionOutSchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    user_id: IdSchema,
    workspace_id: IdSchema.nullish(),
    title: z.string().nullish(),
    status: z.string(),
    created_at: ISODateTimeSchema,
    updated_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type SessionOut = z.infer<typeof SessionOutSchema>;

export const MessageOutSchema = z
  .object({
    id: IdSchema,
    session_id: IdSchema,
    space_id: IdSchema,
    user_id: IdSchema,
    role: z.string(),
    content: z.string(),
    metadata_json: JsonObjectSchema.nullish(),
    created_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type MessageOut = z.infer<typeof MessageOutSchema>;

export const SessionPageSchema = z
  .object({
    items: z.array(SessionOutSchema),
    total: z.number().int().nonnegative(),
    limit: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type SessionPage = z.infer<typeof SessionPageSchema>;

export const SessionCreateRequestSchema = z
  .object({
    space_id: IdSchema.nullish(),
    user_id: IdSchema.nullish(),
    workspace_id: IdSchema.nullish(),
    title: z.string().nullish(),
    metadata: JsonObjectSchema.nullish(),
  })
  .passthrough();
export type SessionCreateRequest = z.infer<typeof SessionCreateRequestSchema>;

export const MessageCreateRequestSchema = z
  .object({
    role: z.string(),
    content: z.string().min(1),
    metadata: JsonObjectSchema.nullish(),
  })
  .passthrough();
export type MessageCreateRequest = z.infer<typeof MessageCreateRequestSchema>;

export const SessionSummaryForContextSchema = z
  .object({
    id: IdSchema,
    session_id: IdSchema,
    version: z.number().int().positive(),
    summary_text: z.string(),
    condenser_version: z.string(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type SessionSummaryForContext = z.infer<
  typeof SessionSummaryForContextSchema
>;

export const SessionSummaryGetLatestRequestSchema = z.object({
  session_id: IdSchema,
  space_id: IdSchema,
});
export type SessionSummaryGetLatestRequest = z.infer<
  typeof SessionSummaryGetLatestRequestSchema
>;

export const SessionSummaryGetLatestResultSchema = z
  .object({
    summary: SessionSummaryForContextSchema.nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type SessionSummaryGetLatestResult = z.infer<
  typeof SessionSummaryGetLatestResultSchema
>;

export const ChatTurnRequestSchema = z
  .object({
    message: z.string().trim().min(1).max(8000),
    session_id: IdSchema.nullish(),
  })
  .passthrough();
export type ChatTurnRequest = z.infer<typeof ChatTurnRequestSchema>;

export const ChatTurnResultSchema = z
  .object({
    session_id: IdSchema,
    run_id: IdSchema,
    ok: z.boolean(),
    reply: z.string().nullish(),
    error: z.string().nullish(),
    error_code: z.string().nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ChatTurnResult = z.infer<typeof ChatTurnResultSchema>;

export const ChatTurnPrepareRunRequestSchema = z.object({
  agent_id: IdSchema,
  space_id: IdSchema,
  user_id: IdSchema,
  session_id: IdSchema,
  message: z.string().min(1).max(8000),
});
export type ChatTurnPrepareRunRequest = z.infer<
  typeof ChatTurnPrepareRunRequestSchema
>;

export const ChatTurnPrepareRunResultSchema = z
  .object({
    session_id: IdSchema,
    run_id: IdSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type ChatTurnPrepareRunResult = z.infer<
  typeof ChatTurnPrepareRunResultSchema
>;

/**
 * Context assembly for the chat path. The server chat turn owns the
 * `ChatContextBuilder` selection/budget loop, candidate reads, and
 * `context_snapshots` / `context_snapshot_items` persistence.
 */
export const ChatContextCandidateItemSchema = z
  .object({
    item_type: z.string(),
    item_id: IdSchema.nullish(),
    title: z.string().nullish(),
    excerpt: z.string().nullish(),
    score: z.number().nullish(),
    reason: z.string().nullish(),
    token_count: z.number().int().nonnegative().nullish(),
    metadata: TraceSafeObjectSchema.default({}),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ChatContextCandidateItem = z.infer<
  typeof ChatContextCandidateItemSchema
>;

export const ChatContextCandidatesRequestSchema = z.object({
  agent_id: IdSchema,
  space_id: IdSchema,
  user_id: IdSchema,
  session_id: IdSchema,
  message: z.string().min(1).max(8000),
});
export type ChatContextCandidatesRequest = z.infer<
  typeof ChatContextCandidatesRequestSchema
>;

export const ChatContextCandidatesResultSchema = z
  .object({
    allowed_sources: z.array(z.string()).default([]),
    max_tokens: z.number().int().positive(),
    max_items: z.number().int().positive(),
    context_policy_applied: z.boolean(),
    items: z.array(ChatContextCandidateItemSchema).default([]),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ChatContextCandidatesResult = z.infer<
  typeof ChatContextCandidatesResultSchema
>;

export const ChatRunCreateRequestSchema = z.object({
  agent_id: IdSchema,
  space_id: IdSchema,
  user_id: IdSchema,
  session_id: IdSchema,
  prompt: z.string().min(1),
});
export type ChatRunCreateRequest = z.infer<typeof ChatRunCreateRequestSchema>;

export const ChatRunCreateResultSchema = z
  .object({
    run_id: IdSchema,
    context_snapshot_id: IdSchema.nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ChatRunCreateResult = z.infer<typeof ChatRunCreateResultSchema>;

export const MemoryOutSchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    subject_user_id: IdSchema.nullish(),
    owner_user_id: IdSchema.nullish(),
    workspace_id: IdSchema.nullish(),
    scope: z.string(),
    namespace: z.string().nullish(),
    type: z.string(),
    title: z.string().nullish(),
    content: z.string().nullish(),
    status: z.string(),
    visibility: z.string(),
    sensitivity_level: z.string(),
    selected_user_ids: z.array(z.unknown()).nullish(),
    last_confirmed_at: ISODateTimeSchema.nullish(),
    confidence: z.number(),
    importance: z.number(),
    source_id: IdSchema.nullish(),
    created_by: IdSchema.nullish(),
    created_at: ISODateTimeSchema,
    updated_at: ISODateTimeSchema,
    deleted_at: ISODateTimeSchema.nullish(),
    version: z.number().int(),
    tags: z.array(z.unknown()).nullish(),
    memory_layer: z.string().nullish(),
    memory_kind: z.string().nullish(),
    source_trust: z.string().nullish(),
    created_from_proposal_id: IdSchema.nullish(),
    root_memory_id: IdSchema.nullish(),
    supersedes_memory_id: IdSchema.nullish(),
    project_id: IdSchema.nullish(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type MemoryOut = z.infer<typeof MemoryOutSchema>;

export const MemoryProposalOperationSchema = z.enum([
  "create",
  "update",
  "archive",
]);
export type MemoryProposalOperation = z.infer<
  typeof MemoryProposalOperationSchema
>;

const MemoryCreateFieldsSchema = z.object({
  title: z.string(),
  content: z.string(),
  type: z.string(),
  scope: z.string().default("user"),
  namespace: z.string().default("user.default"),
  visibility: z.string().default("private"),
  sensitivity_level: z.string().default("normal"),
  confidence: z.number().default(1),
  importance: z.number().default(0.5),
  tags: z.array(z.string()).nullish(),
  source_id: IdSchema.nullish(),
  space_id: IdSchema.nullish(),
  subject_user_id: IdSchema.nullish(),
  owner_user_id: IdSchema.nullish(),
  selected_user_ids: z.array(IdSchema).nullish(),
  last_confirmed_at: ISODateTimeSchema.nullish(),
  source_proposal_id: IdSchema.nullish(),
  workspace_id: IdSchema.nullish(),
  memory_layer: z.string().nullish(),
  memory_kind: z.string().nullish(),
});

const MemoryUpdateFieldsSchema = z.object({
  title: z.string().nullish(),
  content: z.string().nullish(),
  type: z.string().nullish(),
  scope: z.string().nullish(),
  namespace: z.string().nullish(),
  visibility: z.string().nullish(),
  sensitivity_level: z.string().nullish(),
  confidence: z.number().nullish(),
  importance: z.number().nullish(),
  tags: z.array(z.string()).nullish(),
  subject_user_id: IdSchema.nullish(),
  owner_user_id: IdSchema.nullish(),
  selected_user_ids: z.array(IdSchema).nullish(),
  workspace_id: IdSchema.nullish(),
  memory_layer: z.string().nullish(),
  memory_kind: z.string().nullish(),
});

export const MemoryProposalCreateCommandSchema = MemoryCreateFieldsSchema.extend({
  operation: z.literal("create"),
  actor_user_id: IdSchema.nullish(),
  provenance_entries: z.array(TraceSafeObjectSchema).default([]),
});
export type MemoryProposalCreateCommand = z.infer<
  typeof MemoryProposalCreateCommandSchema
>;

export const MemoryProposalUpdateCommandSchema = MemoryUpdateFieldsSchema.extend({
  operation: z.literal("update"),
  target_memory_id: IdSchema,
  actor_user_id: IdSchema.nullish(),
  provenance_entries: z.array(TraceSafeObjectSchema).default([]),
});
export type MemoryProposalUpdateCommand = z.infer<
  typeof MemoryProposalUpdateCommandSchema
>;

export const MemoryProposalArchiveCommandSchema = z.object({
  operation: z.literal("archive"),
  target_memory_id: IdSchema,
  workspace_id: IdSchema.nullish(),
  actor_user_id: IdSchema.nullish(),
  provenance_entries: z.array(TraceSafeObjectSchema).default([]),
});
export type MemoryProposalArchiveCommand = z.infer<
  typeof MemoryProposalArchiveCommandSchema
>;

export const MemoryProposalCommandSchema = z.discriminatedUnion("operation", [
  MemoryProposalCreateCommandSchema,
  MemoryProposalUpdateCommandSchema,
  MemoryProposalArchiveCommandSchema,
]);
export type MemoryProposalCommand = z.infer<
  typeof MemoryProposalCommandSchema
>;

export const MemoryProposalCreateResultSchema = z
  .object({
    proposal_id: IdSchema,
    proposal_type: z.enum([
      "memory_create",
      "memory_update",
      "memory_archive",
    ]),
    status: z.string(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type MemoryProposalCreateResult = z.infer<
  typeof MemoryProposalCreateResultSchema
>;

/**
 * Public `POST /memory/search` body. `space_id`/
 * `user_id` override the caller's identity; `type` is the wire name for
 * `memory_type`. `include_system` is an opt-in: by default the user-facing
 * search hides `scope=system` seed memories (system policy rows) so they do not
 * appear as user memory hits; pass it (or an explicit `scope=system`) to include
 * them.
 */
export const MemorySearchRequestSchema = z
  .object({
    query: z.string(),
    scope: z.string().nullish(),
    namespace: z.string().nullish(),
    type: z.string().nullish(),
    limit: z.number().int().nonnegative().default(10),
    space_id: IdSchema.nullish(),
    user_id: IdSchema.nullish(),
    workspace_id: IdSchema.nullish(),
    include_system: z.boolean().default(false),
  })
  .passthrough();
export type MemorySearchRequest = z.infer<typeof MemorySearchRequestSchema>;

export const MemoryReadRequestSchema = z.object({
  space_id: IdSchema,
  user_id: IdSchema.nullish(),
  agent_id: IdSchema.nullish(),
  run_id: IdSchema.nullish(),
  workspace_id: IdSchema.nullish(),
  project_id: IdSchema.nullish(),
  memory_id: IdSchema.nullish(),
  query: z.string().nullish(),
  limit: z.number().int().nonnegative().default(50),
  offset: z.number().int().nonnegative().default(0),
  include_system_scope: z.boolean().default(false),
  reason: z.string().nullish(),
});
export type MemoryReadRequest = z.infer<typeof MemoryReadRequestSchema>;

export const MemoryPageSchema = z
  .object({
    items: z.array(MemoryOutSchema),
    total: z.number().int().nonnegative(),
    limit: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative(),
    ...SecretResponseGuards,
  })
  .passthrough();
export type MemoryPage = z.infer<typeof MemoryPageSchema>;

export const MemoryReadTraceSchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    memory_id: IdSchema,
    user_id: IdSchema.nullish(),
    agent_id: IdSchema.nullish(),
    run_id: IdSchema.nullish(),
    access_type: z.string(),
    reason: z.string().nullish(),
    accessed_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type MemoryReadTrace = z.infer<typeof MemoryReadTraceSchema>;

export const ContextSourceRefSchema = z
  .object({
    source_type: z.string(),
    source_id: IdSchema.nullish(),
    section: z.string().nullish(),
    title: z.string().nullish(),
    ...SecretResponseGuards,
  })
  .catchall(TraceSafeJsonSchema);
export type ContextSourceRef = z.infer<typeof ContextSourceRefSchema>;

export const ContextBuildRequestSchema = z.object({
  space_id: IdSchema,
  user_id: IdSchema.nullish(),
  workspace_id: IdSchema.nullish(),
  project_id: IdSchema.nullish(),
  task_type: z.string().nullish(),
  capability_id: z.string().nullish(),
  session_id: IdSchema.nullish(),
  run_id: IdSchema.nullish(),
  query: z.string().nullish(),
  agent_id: IdSchema.nullish(),
});
export type ContextBuildRequest = z.infer<typeof ContextBuildRequestSchema>;

export const ContextPackageSchema = z
  .object({
    user_memory: z.array(MemoryOutSchema).default([]),
    workspace_memory: z.array(MemoryOutSchema).default([]),
    capability_memory: z.array(MemoryOutSchema).default([]),
    agent_memory: z.array(MemoryOutSchema).default([]),
    system_policy: z.array(MemoryOutSchema).default([]),
    recent_session_summary: z.array(SessionSummaryForContextSchema).default([]),
    relevant_episodes: z.array(MemoryOutSchema).default([]),
    evidence_items: z.array(TraceSafeObjectSchema).default([]),
    attachments: z.array(TraceSafeObjectSchema).default([]),
    active_policies: z.array(TraceSafeObjectSchema).default([]),
    stable_prefix_refs: z.array(ContextSourceRefSchema).default([]),
    dynamic_tail_refs: z.array(ContextSourceRefSchema).default([]),
    source_refs: z.array(ContextSourceRefSchema).default([]),
    retrieval_trace: TraceSafeObjectSchema.default({}),
    token_budget: TraceSafeObjectSchema.default({}),
    personal_context_block: z.string().default(""),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextPackage = z.infer<typeof ContextPackageSchema>;

export const ContextBuildResultSchema = z
  .object({
    package: ContextPackageSchema,
    context_snapshot_id: IdSchema.nullish(),
    memory_read_traces: z.array(MemoryReadTraceSchema).default([]),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextBuildResult = z.infer<typeof ContextBuildResultSchema>;

export const ContextCompileTargetSchema = z.enum([
  "claude",
  "codex_cli",
  "cursor",
  "generic",
  "soul",
  "prompt",
]);
export type ContextCompileTarget = z.infer<typeof ContextCompileTargetSchema>;

export const ContextCompileRequestSchema = z.object({
  space_id: IdSchema,
  target: ContextCompileTargetSchema,
  task_goal: z.string(),
  context_package: ContextPackageSchema,
  workspace_path: z.string().nullish(),
  budget_chars: z.number().int().positive().nullish(),
});
export type ContextCompileRequest = z.infer<typeof ContextCompileRequestSchema>;

export const ContextCompileResultSchema = z
  .object({
    target: ContextCompileTargetSchema,
    task_prompt: z.string(),
    instruction_file_path: z.string().nullish(),
    total_chars: z.number().int().nonnegative(),
    budget_chars: z.number().int().positive(),
    dropped_sections: z.array(z.string()).default([]),
    budget_trace: TraceSafeObjectSchema.default({}),
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextCompileResult = z.infer<
  typeof ContextCompileResultSchema
>;

export const ContextSnapshotAuditSchema = z
  .object({
    id: IdSchema,
    space_id: IdSchema,
    source_refs_json: z.array(ContextSourceRefSchema).default([]),
    token_estimate: z.number().int().nonnegative().nullish(),
    relevant_period_start: ISODateTimeSchema.nullish(),
    relevant_period_end: ISODateTimeSchema.nullish(),
    prefix_hash: z.string().nullish(),
    tail_hash: z.string().nullish(),
    compiler_version: z.string().nullish(),
    retrieval_trace_json: TraceSafeArraySchema.nullish(),
    token_budget_json: TraceSafeObjectSchema.nullish(),
    policy_bundle_version: z.string().nullish(),
    memory_digest_version: z.string().nullish(),
    workspace_digest_version: z.string().nullish(),
    execution_plane_id: IdSchema.nullish(),
    included_memory_refs_json: z.array(ContextSourceRefSchema).nullish(),
    included_evidence_refs_json: z.array(ContextSourceRefSchema).nullish(),
    included_file_refs_json: z.array(ContextSourceRefSchema).nullish(),
    included_doc_refs_json: z.array(ContextSourceRefSchema).nullish(),
    redactions_json: TraceSafeObjectSchema.nullish(),
    data_exposure_level: z.string().nullish(),
    rendered_context_uri: z.string().nullish(),
    has_compiled_prefix_text: z.boolean().default(false),
    has_compiled_tail_text: z.boolean().default(false),
    has_rendered_context_text: z.boolean().default(false),
    created_at: ISODateTimeSchema,
    ...RawContextResponseGuards,
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextSnapshotAudit = z.infer<
  typeof ContextSnapshotAuditSchema
>;

export const ContextSnapshotItemAuditSchema = z
  .object({
    id: IdSchema,
    context_snapshot_id: IdSchema,
    item_type: z.string(),
    item_id: IdSchema.nullish(),
    title: z.string().nullish(),
    excerpt: z.string().nullish(),
    score: z.number().nullish(),
    reason: z.string().nullish(),
    token_count: z.number().int().nonnegative().nullish(),
    metadata_json: TraceSafeObjectSchema.default({}),
    created_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextSnapshotItemAudit = z.infer<
  typeof ContextSnapshotItemAuditSchema
>;

export const ContextEngineEventTypeSchema = z.enum([
  "context.build_started",
  "context.session_summary_loaded",
  "context.memory_selected",
  "context.evidence_selected",
  "context.compaction_applied",
  "context.overflow_recovered",
  "context.snapshot_persisted",
  "context.build_completed",
  "context.build_failed",
]);
export type ContextEngineEventType = z.infer<
  typeof ContextEngineEventTypeSchema
>;

export const ContextEngineEventSchema = z
  .object({
    event_type: ContextEngineEventTypeSchema,
    space_id: IdSchema,
    session_id: IdSchema.nullish(),
    run_id: IdSchema.nullish(),
    context_snapshot_id: IdSchema.nullish(),
    status: z.enum(["started", "succeeded", "failed", "skipped", "warning"]),
    message: z.string().nullish(),
    metadata_json: TraceSafeObjectSchema.default({}),
    created_at: ISODateTimeSchema,
    ...SecretResponseGuards,
  })
  .passthrough();
export type ContextEngineEvent = z.infer<typeof ContextEngineEventSchema>;
