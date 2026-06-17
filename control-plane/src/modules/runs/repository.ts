import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  redactEvidenceText,
  sanitizeErrorJson,
  sanitizeEvidenceJson,
} from "./evidenceRedaction";
import {
  BUILTIN_RUNTIME_ADAPTER_SPECS,
  type RuntimeAdapterType,
} from "../runtimeAdapters/specs";

export interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

export interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

export interface RunRecord {
  id: string;
  space_id: string;
  agent_id: string;
  agent_version_id: string;
  system_prompt?: string | null;
  context_snapshot_id?: string | null;
  run_type?: string;
  status: string;
  mode: string;
  prompt: string | null;
  instruction: string | null;
  workspace_id: string | null;
  session_id: string | null;
  parent_run_id?: string | null;
  project_id: string | null;
  scheduled_at?: string | null;
  adapter_type: string | null;
  capability_id?: string | null;
  model_provider_id: string | null;
  model_override_json?: unknown;
  required_sandbox_level: string;
  trigger_origin: string;
  instructed_by_user_id?: string | null;
  error_message?: string | null;
  error_json?: unknown;
  output_json?: unknown;
  usage_json?: unknown;
  started_at: string | null;
  ended_at: string | null;
  created_at?: string;
  updated_at?: string;
  visibility?: string;
}

export interface RunListFilters {
  space_id: string;
  user_id: string;
  status?: string | null;
  mode?: string | null;
  agent_id?: string | null;
  workspace_id?: string | null;
  project_id?: string | null;
  limit: number;
  offset: number;
}

export interface ModelProviderSummaryRecord {
  id: string;
  name: string;
  provider_type: string;
  default_model: string | null;
  enabled: boolean;
  credential_id?: string | null;
}

export interface RunEvaluationRecord {
  id: string;
  space_id: string;
  run_id: string;
  evaluator_type: string;
  evaluator_version: string;
  outcome_status: string;
  failure_layer: string | null;
  failure_reason_code: string | null;
  trajectory_status: string;
  evidence_json: unknown;
  rule_trace_json: unknown;
  notes: string | null;
  evaluated_at: string;
}

export interface RunFinalizationRecord {
  id: string;
  space_id: string;
  run_id: string;
  finalizer_version: string;
  status: string;
  run_evaluation_id: string | null;
  task_evaluation_id: string | null;
  outcome_status: string | null;
  failure_layer: string | null;
  failure_reason_code: string | null;
  trajectory_status: string | null;
  skipped_reasons_json: unknown;
  error_json: unknown;
  metadata_json: unknown;
  finalized_at: string;
  created_at: string;
}

export interface RunStepDetailRecord {
  id: string;
  space_id: string;
  run_id: string;
  parent_step_id: string | null;
  actor_id: string;
  step_index: number;
  step_type: string;
  status: string;
  title: string | null;
  workspace_id: string | null;
  session_id: string | null;
  task_id: string | null;
  artifact_id: string | null;
  proposal_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  input_summary: string | null;
  output_summary: string | null;
  error_type: string | null;
  error_message: string | null;
  metadata_json: unknown;
  created_at: string;
  updated_at: string;
}

export interface RunEventDetailRecord {
  id: string;
  space_id: string;
  run_id: string;
  step_id: string | null;
  actor_id: string | null;
  event_index: number;
  event_type: string;
  status: string;
  summary: string | null;
  error_code: string | null;
  error_message: string | null;
  workspace_id: string | null;
  artifact_id: string | null;
  proposal_id: string | null;
  data_exposure_level: string | null;
  trust_level: string | null;
  metadata_json: unknown;
  created_at: string;
}

export interface ArtifactSummaryRecord {
  id: string;
  space_id: string;
  run_id: string | null;
  proposal_id: string | null;
  artifact_type: string;
  title: string;
  mime_type: string | null;
  visibility: string;
  created_at: string;
}

export interface ProposalSummaryRecord {
  id: string;
  space_id: string;
  proposal_type: string;
  status: string;
  title: string;
  visibility: string;
  created_at: string;
  preview: boolean;
  urgency: string;
  review_deadline: string | null;
  expires_at: string | null;
  created_by_run_id: string | null;
}

export interface RunCreateInput {
  agent_id: string;
  space_id: string;
  user_id: string;
  mode: string;
  run_type: string;
  trigger_origin: string;
  session_id?: string | null;
  workspace_id?: string | null;
  project_id?: string | null;
  prompt?: string | null;
  instruction?: string | null;
  scheduled_at?: string | null;
  parent_run_id?: string | null;
  adapter_type?: string | null;
  capability_id?: string | null;
  model_provider_id?: string | null;
  model?: string | null;
}

export class RunCreateValidationError extends Error {
  constructor(
    message: string,
    readonly statusCode: number = 422,
  ) {
    super(message);
    this.name = "RunCreateValidationError";
  }
}

export interface RunTerminalUpdate {
  run_id: string;
  space_id: string;
  status: "succeeded" | "failed" | "degraded" | "cancelled";
  output_text?: string | null;
  output_json?: unknown;
  error_json?: unknown;
  exit_code?: number | null;
  completed_at: string;
  usage_json?: unknown;
}

export interface RunEventRecord {
  id: string;
  space_id: string;
  run_id: string;
  event_index: number;
  event_type: string;
  status: string;
}

export interface RunChatResultRecord {
  id: string;
  space_id: string;
  status: string;
  output_json: unknown;
  error_json: unknown;
}

export interface RunEventInput {
  run_id: string;
  space_id: string;
  event_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | "warning" | "cancelled";
  step_id?: string | null;
  actor_id?: string | null;
  summary?: string | null;
  metadata_json?: unknown;
  error_code?: string | null;
  error_message?: string | null;
  workspace_id?: string | null;
  artifact_id?: string | null;
  proposal_id?: string | null;
  data_exposure_level?: string | null;
  trust_level?: string | null;
}

export interface RunStepRecord {
  id: string;
  space_id: string;
  run_id: string;
  step_index: number;
  step_type: string;
  status: string;
}

export interface RunStepInput {
  run_id: string;
  space_id: string;
  actor_id: string;
  step_type: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | "cancelled";
  title?: string | null;
  parent_step_id?: string | null;
  workspace_id?: string | null;
  session_id?: string | null;
  task_id?: string | null;
  artifact_id?: string | null;
  proposal_id?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  input_summary?: string | null;
  output_summary?: string | null;
  error_type?: string | null;
  error_message?: string | null;
  metadata_json?: unknown;
}

export class PgRunRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgRunRepository {
    if (!config.databaseUrl) {
      throw new Error("Run repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgRunRepository(getDbPool(config.databaseUrl));
  }

  async recoverStaleRuns(staleAfterSeconds = 3600, now = new Date()): Promise<number> {
    const cutoff = new Date(
      now.getTime() - Math.max(1, staleAfterSeconds) * 1000,
    ).toISOString();
    const completedAt = now.toISOString();
    const errorMessage = "Run timed out (stale running recovery at TS worker startup)";
    const errorJson = sanitizeErrorJson({
      error_code: "stale_run_recovered",
      error_text: "Run was stuck in running status and was recovered at TS worker startup",
    });
    const result = await this.db.query<{ id: string }>(
      `UPDATE runs
          SET status = 'failed',
              error_message = $3,
              error_json = $4::jsonb,
              ended_at = $2,
              updated_at = $2
        WHERE status = 'running'
          AND started_at IS NOT NULL
          AND started_at < $1
        RETURNING id`,
      [
        cutoff,
        completedAt,
        redactEvidenceText(errorMessage),
        JSON.stringify(errorJson),
      ],
    );
    return result.rowCount ?? result.rows.length;
  }

  async createQueuedRun(input: RunCreateInput): Promise<RunRecord> {
    validateRunCreateInput(input);
    const agent = await this.getAgentForRun(input.space_id, input.agent_id);
    if (!agent) {
      throw new RunCreateValidationError(
        `Agent '${input.agent_id}' not found in this space`,
        404,
      );
    }
    if (agent.status !== "active") {
      throw new RunCreateValidationError(
        `Agent '${input.agent_id}' is not active`,
        409,
      );
    }
    if (!agent.current_version_id) {
      throw new RunCreateValidationError(
        `Agent '${input.agent_id}' has no current version. Create an AgentVersion first.`,
        400,
      );
    }
    const versionOk = await this.agentVersionBelongsToAgent(
      input.space_id,
      input.agent_id,
      agent.current_version_id,
    );
    if (!versionOk) {
      throw new RunCreateValidationError(
        `AgentVersion '${agent.current_version_id}' does not belong to Agent '${input.agent_id}'`,
        400,
      );
    }
    await this.assertOptionalSpaceRef("workspaces", input.workspace_id, input.space_id, "Workspace");
    await this.assertOptionalSpaceRef("sessions", input.session_id, input.space_id, "Session");
    await this.assertOptionalSpaceRef("projects", input.project_id, input.space_id, "Project");
    if (input.parent_run_id) {
      const parent = await this.getRun(input.space_id, input.parent_run_id);
      if (!parent) {
        throw new RunCreateValidationError(
          `Parent run '${input.parent_run_id}' not found`,
          404,
        );
      }
    }
    // Resolve adapter type + model provider from the agent version and space
    // defaults when the caller did not pass them explicitly. Mirrors Python
    // `RunService.create_run` (`preview_run_adapter_type` +
    // `resolve_model_config_for_runtime`): the chat path passes neither, so
    // without this the run is created with a null provider and a `model_api`
    // execution fails closed with `model_provider_required`.
    const resolved = await this.resolveRunModelConfig(
      input.space_id,
      agent.current_version_id,
      input,
    );
    if (resolved.modelProviderId) {
      const provider = await this.getModelProviderSummary(
        input.space_id,
        resolved.modelProviderId,
      );
      if (!provider) {
        throw new RunCreateValidationError(
          `ModelProvider '${resolved.modelProviderId}' not found in this space`,
          400,
        );
      }
      if (!provider.enabled) {
        throw new RunCreateValidationError(
          `ModelProvider '${resolved.modelProviderId}' is disabled`,
          400,
        );
      }
    }

    const now = new Date().toISOString();
    const contextSnapshotId = randomUUID();
    await this.db.query(
      `INSERT INTO context_snapshots (
          id, space_id, source_refs_json, compiled_summary, token_estimate,
          agent_id, session_id, request_json, created_at
       )
       VALUES ($1, $2, '[]'::jsonb, NULL, NULL, $3, $4, $5::jsonb, $6)`,
      [
        contextSnapshotId,
        input.space_id,
        input.agent_id,
        input.session_id ?? null,
        JSON.stringify({
          space_id: input.space_id,
          user_id: input.user_id,
          agent_version_id: agent.current_version_id,
          session_id: input.session_id ?? null,
          workspace_id: input.workspace_id ?? null,
          project_id: input.project_id ?? null,
          user_message: input.prompt ?? input.instruction ?? null,
          manual_context: [],
        }),
        now,
      ],
    );

    const runId = randomUUID();
    const result = await this.db.query<RunRecord>(
      `INSERT INTO runs (
          id, space_id, agent_id, agent_version_id, context_snapshot_id,
          workspace_id, session_id, parent_run_id, instructed_by_user_id,
          run_type, trigger_origin, status, mode, prompt, instruction,
          scheduled_at, created_at, updated_at, adapter_type, capability_id,
          model_provider_id, model_override_json, required_sandbox_level,
          usage_accuracy, visibility, project_id, source
       )
       VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8, $9,
          $10, $11, 'queued', $12, $13, $14, $15, $16, $16,
          $17, $18, $19, $20::jsonb, 'none', 'estimated',
          'space_shared', $21, 'managed'
       )
       RETURNING id, space_id, agent_id, agent_version_id, context_snapshot_id,
                 run_type, status, mode, prompt, instruction, workspace_id,
                 session_id, parent_run_id, project_id, scheduled_at,
                 adapter_type, capability_id, model_provider_id,
                 model_override_json, required_sandbox_level, trigger_origin,
                 instructed_by_user_id, error_message, error_json, output_json,
                 usage_json, started_at, ended_at, created_at, updated_at,
                 visibility`,
      [
        runId,
        input.space_id,
        input.agent_id,
        agent.current_version_id,
        contextSnapshotId,
        input.workspace_id ?? null,
        input.session_id ?? null,
        input.parent_run_id ?? null,
        input.user_id,
        input.run_type,
        input.trigger_origin,
        input.mode,
        input.prompt ?? null,
        input.instruction ?? null,
        input.scheduled_at ?? null,
        now,
        resolved.adapterType,
        input.capability_id ?? null,
        resolved.modelProviderId,
        resolved.modelName || resolved.modelProviderId
          ? JSON.stringify({ model: resolved.modelName, source: resolved.source })
          : null,
        input.project_id ?? null,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("Run insert returned no row");
    await this.db.query(
      `UPDATE context_snapshots SET run_id = $3 WHERE space_id = $1 AND id = $2`,
      [input.space_id, contextSnapshotId, row.id],
    );
    return row;
  }

  private async getAgentForRun(
    spaceId: string,
    agentId: string,
  ): Promise<{ id: string; status: string; current_version_id: string | null } | null> {
    const result = await this.db.query<{
      id: string;
      status: string;
      current_version_id: string | null;
    }>(
      `SELECT id, status, current_version_id
         FROM agents
        WHERE space_id = $1 AND id = $2`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }

  /**
   * Resolve adapter type + model provider + model for a new run, mirroring
   * Python `RunService.create_run`. Priority: explicit request → agent version
   * default → space default provider (for adapters that require a provider).
   */
  private async resolveRunModelConfig(
    spaceId: string,
    versionId: string,
    input: RunCreateInput,
  ): Promise<{
    adapterType: string;
    modelProviderId: string | null;
    modelName: string | null;
    source: string;
  }> {
    const version = await this.loadAgentVersionForResolution(spaceId, versionId);
    const runtimeConfig = recordValue(version?.runtime_config_json);
    const runtimePolicy = recordValue(version?.runtime_policy_json);
    // preview_run_adapter_type: request → runtime_config.adapter_type →
    // runtime_policy.default_adapter_type → model_api.
    const adapterType =
      trimmed(input.adapter_type) ||
      trimmed(runtimeConfig.adapter_type) ||
      trimmed(runtimePolicy.default_adapter_type) ||
      "model_api";
    const mode =
      BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType]?.model
        .model_provider_mode ?? "none";
    const requestModel = trimmed(input.model) || null;
    const versionModel = trimmed(version?.model_name) || null;

    if (input.model_provider_id) {
      return {
        adapterType,
        modelProviderId: input.model_provider_id,
        modelName: requestModel ?? versionModel,
        source: "request",
      };
    }
    if (mode !== "none" && version?.model_provider_id) {
      return {
        adapterType,
        modelProviderId: version.model_provider_id,
        modelName: requestModel ?? versionModel,
        source: "agent_default",
      };
    }
    if (mode === "required") {
      const fallback = await this.resolveDefaultProvider(spaceId, adapterType);
      if (fallback) {
        return {
          adapterType,
          modelProviderId: fallback.id,
          modelName: requestModel ?? versionModel ?? fallback.default_model,
          source: fallback.source,
        };
      }
    }
    return {
      adapterType,
      modelProviderId: null,
      modelName: requestModel,
      source: requestModel ? "request" : "none",
    };
  }

  private async loadAgentVersionForResolution(
    spaceId: string,
    versionId: string,
  ): Promise<{
    runtime_config_json: unknown;
    runtime_policy_json: unknown;
    model_provider_id: string | null;
    model_name: string | null;
  } | null> {
    const result = await this.db.query<{
      runtime_config_json: unknown;
      runtime_policy_json: unknown;
      model_provider_id: string | null;
      model_name: string | null;
    }>(
      `SELECT runtime_config_json, runtime_policy_json, model_provider_id, model_name
         FROM agent_versions
        WHERE id = $1 AND space_id = $2
        LIMIT 1`,
      [versionId, spaceId],
    );
    return result.rows[0] ?? null;
  }

  /**
   * Port of `resolve_default_provider_for_runtime`: a runtime-scoped default
   * ModelProvider is expressed on `config_json` (`runtime_default_for` /
   * `runtime_default_adapter_type(s)` / `runtime_defaults`); otherwise the space
   * default is the enabled provider with `config_json.is_default = true`.
   */
  private async resolveDefaultProvider(
    spaceId: string,
    adapterType: string,
  ): Promise<{ id: string; default_model: string | null; source: string } | null> {
    const result = await this.db.query<{
      id: string;
      default_model: string | null;
      config_json: unknown;
    }>(
      `SELECT id, default_model, config_json
         FROM model_providers
        WHERE space_id = $1 AND enabled = TRUE`,
      [spaceId],
    );
    let spaceDefault: { id: string; default_model: string | null } | null = null;
    for (const row of result.rows) {
      const cfg = recordValue(row.config_json);
      if (cfg.runtime_default_for === adapterType) {
        return { id: row.id, default_model: row.default_model, source: "runtime_default" };
      }
      if (cfg.runtime_default_adapter_type === adapterType) {
        return { id: row.id, default_model: row.default_model, source: "runtime_default" };
      }
      const types = cfg.runtime_default_adapter_types;
      if (Array.isArray(types) && types.includes(adapterType)) {
        return { id: row.id, default_model: row.default_model, source: "runtime_default" };
      }
      const defaults = cfg.runtime_defaults;
      if (defaults && typeof defaults === "object" && (defaults as Record<string, unknown>)[adapterType] === true) {
        return { id: row.id, default_model: row.default_model, source: "runtime_default" };
      }
      if (spaceDefault === null && cfg.is_default === true) {
        spaceDefault = { id: row.id, default_model: row.default_model };
      }
    }
    return spaceDefault
      ? { id: spaceDefault.id, default_model: spaceDefault.default_model, source: "space_default" }
      : null;
  }

  private async agentVersionBelongsToAgent(
    spaceId: string,
    agentId: string,
    versionId: string,
  ): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id
         FROM agent_versions
        WHERE space_id = $1 AND agent_id = $2 AND id = $3`,
      [spaceId, agentId, versionId],
    );
    return result.rows.length > 0;
  }

  private async assertOptionalSpaceRef(
    table: "workspaces" | "sessions" | "projects",
    id: string | null | undefined,
    spaceId: string,
    label: string,
  ): Promise<void> {
    if (!id) return;
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM ${table} WHERE space_id = $1 AND id = $2`,
      [spaceId, id],
    );
    if (result.rows.length === 0) {
      throw new RunCreateValidationError(
        `${label} '${id}' not found in this space`,
        400,
      );
    }
  }

  async getRun(spaceId: string, runId: string): Promise<RunRecord | null> {
    const result = await this.db.query<RunRecord>(
      `SELECT r.id, r.space_id, r.agent_id, r.agent_version_id,
              av.system_prompt AS system_prompt,
              r.context_snapshot_id, r.run_type, r.status, r.mode, r.prompt,
              r.instruction, r.workspace_id, r.session_id, r.parent_run_id,
              r.project_id, r.scheduled_at, r.adapter_type, r.capability_id,
              r.model_provider_id, r.model_override_json, r.required_sandbox_level,
              r.trigger_origin, r.instructed_by_user_id, r.error_message,
              r.error_json, r.output_json, r.usage_json, r.started_at,
              r.ended_at, r.created_at, r.updated_at, r.visibility
         FROM runs r
         LEFT JOIN agent_versions av
           ON av.id = r.agent_version_id
          AND av.space_id = r.space_id
          AND av.agent_id = r.agent_id
        WHERE r.space_id = $1 AND r.id = $2`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async listRuns(filters: RunListFilters): Promise<RunRecord[]> {
    const clauses = [
      "space_id = $1",
      "(visibility = 'space_shared' OR (visibility IN ('private', 'restricted') AND instructed_by_user_id = $2))",
    ];
    const params: unknown[] = [filters.space_id, filters.user_id];
    addOptionalFilter(clauses, params, "status", filters.status);
    addOptionalFilter(clauses, params, "mode", filters.mode);
    addOptionalFilter(clauses, params, "agent_id", filters.agent_id);
    addOptionalFilter(clauses, params, "workspace_id", filters.workspace_id);
    addOptionalFilter(clauses, params, "project_id", filters.project_id);
    params.push(filters.limit, filters.offset);
    const limitIndex = params.length - 1;
    const offsetIndex = params.length;
    const result = await this.db.query<RunRecord>(
      `SELECT id, space_id, agent_id, agent_version_id, context_snapshot_id,
              run_type, status, mode, prompt, instruction, workspace_id,
              session_id, parent_run_id, project_id, scheduled_at, adapter_type,
              capability_id, model_provider_id, model_override_json,
              required_sandbox_level, trigger_origin, instructed_by_user_id,
              error_message, error_json, output_json, usage_json, started_at,
              ended_at, created_at, updated_at, visibility
         FROM runs
        WHERE ${clauses.join(" AND ")}
        ORDER BY created_at DESC, id DESC
        LIMIT $${limitIndex} OFFSET $${offsetIndex}`,
      params,
    );
    return result.rows;
  }

  async getModelProviderSummary(
    spaceId: string,
    providerId: string | null | undefined,
  ): Promise<ModelProviderSummaryRecord | null> {
    if (!providerId) return null;
    const result = await this.db.query<ModelProviderSummaryRecord>(
      `SELECT id, name, provider_type, default_model, enabled, credential_id
         FROM model_providers
        WHERE space_id = $1 AND id = $2`,
      [spaceId, providerId],
    );
    return result.rows[0] ?? null;
  }

  async getChatRunResult(
    spaceId: string,
    runId: string,
  ): Promise<RunChatResultRecord | null> {
    const result = await this.db.query<RunChatResultRecord>(
      `SELECT id, space_id, status, output_json, error_json
         FROM runs
        WHERE space_id = $1 AND id = $2`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async listRunSteps(spaceId: string, runId: string): Promise<RunStepDetailRecord[]> {
    const result = await this.db.query<RunStepDetailRecord>(
      `SELECT id, space_id, run_id, parent_step_id, actor_id, step_index,
              step_type, status, title, workspace_id, session_id, task_id,
              artifact_id, proposal_id, started_at, ended_at, input_summary,
              output_summary, error_type, error_message, metadata_json,
              created_at, updated_at
         FROM run_steps
        WHERE space_id = $1 AND run_id = $2
        ORDER BY step_index ASC, id ASC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async listRunEvents(spaceId: string, runId: string): Promise<RunEventDetailRecord[]> {
    const result = await this.db.query<RunEventDetailRecord>(
      `SELECT id, space_id, run_id, step_id, actor_id, event_index, event_type,
              status, summary, error_code, error_message, workspace_id,
              artifact_id, proposal_id, data_exposure_level, trust_level,
              metadata_json, created_at
         FROM run_events
        WHERE space_id = $1 AND run_id = $2
        ORDER BY event_index ASC, id ASC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async listArtifactSummaries(
    spaceId: string,
    runId: string,
  ): Promise<ArtifactSummaryRecord[]> {
    const result = await this.db.query<ArtifactSummaryRecord>(
      `SELECT id, space_id, run_id, proposal_id, artifact_type, title,
              mime_type, visibility, created_at
         FROM artifacts
        WHERE space_id = $1 AND run_id = $2
        ORDER BY created_at ASC, id ASC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async listProposalSummaries(
    spaceId: string,
    runId: string,
  ): Promise<ProposalSummaryRecord[]> {
    const result = await this.db.query<ProposalSummaryRecord>(
      `SELECT id, space_id, proposal_type, status, title, visibility,
              created_at, preview, urgency, review_deadline, expires_at,
              created_by_run_id
         FROM proposals
        WHERE space_id = $1 AND created_by_run_id = $2
        ORDER BY created_at ASC, id ASC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async listChildRuns(spaceId: string, runId: string): Promise<RunRecord[]> {
    const result = await this.db.query<RunRecord>(
      `SELECT id, space_id, agent_id, agent_version_id, parent_run_id, status,
              run_type, trigger_origin, mode, created_at, started_at, ended_at,
              prompt, instruction, workspace_id, session_id, project_id,
              adapter_type, model_provider_id, required_sandbox_level,
              instructed_by_user_id, error_message, visibility
         FROM runs
        WHERE space_id = $1 AND parent_run_id = $2
        ORDER BY created_at ASC, id ASC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async getLatestRunEvaluation(
    spaceId: string,
    runId: string,
  ): Promise<RunEvaluationRecord | null> {
    const result = await this.db.query<RunEvaluationRecord>(
      `SELECT id, space_id, run_id, evaluator_type, evaluator_version,
              outcome_status, failure_layer, failure_reason_code,
              trajectory_status, evidence_json, rule_trace_json, notes,
              evaluated_at
         FROM run_evaluations
        WHERE space_id = $1 AND run_id = $2
        ORDER BY evaluated_at DESC, id DESC
        LIMIT 1`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async listRunEvaluations(
    spaceId: string,
    runId: string,
  ): Promise<RunEvaluationRecord[]> {
    const result = await this.db.query<RunEvaluationRecord>(
      `SELECT id, space_id, run_id, evaluator_type, evaluator_version,
              outcome_status, failure_layer, failure_reason_code,
              trajectory_status, evidence_json, rule_trace_json, notes,
              evaluated_at
         FROM run_evaluations
        WHERE space_id = $1 AND run_id = $2
        ORDER BY evaluated_at DESC, id DESC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async bridgeTaskEvaluationForRunEvaluation(
    spaceId: string,
    runEvaluation: RunEvaluationRecord,
  ): Promise<{ taskEvaluationId: string | null; skippedReason: string | null }> {
    const existing = await this.db.query<{ id: string }>(
      `SELECT id
         FROM task_evaluations
        WHERE space_id = $1 AND run_evaluation_id = $2
        ORDER BY created_at DESC, id DESC
        LIMIT 1`,
      [spaceId, runEvaluation.id],
    );
    if (existing.rows[0]) {
      return { taskEvaluationId: existing.rows[0].id, skippedReason: null };
    }

    const link = await this.db.query<{ task_id: string; run_id: string }>(
      `SELECT task_id, run_id
         FROM task_runs
        WHERE space_id = $1 AND run_id = $2
        ORDER BY (role = 'primary') DESC, created_at ASC, id ASC
        LIMIT 1`,
      [spaceId, runEvaluation.run_id],
    );
    const taskRun = link.rows[0];
    if (!taskRun) {
      return { taskEvaluationId: null, skippedReason: "no_task_run_link" };
    }

    const task = await this.db.query<{ id: string }>(
      `SELECT id
         FROM tasks
        WHERE space_id = $1 AND id = $2 AND deleted_at IS NULL`,
      [spaceId, taskRun.task_id],
    );
    if (!task.rows[0]) {
      return { taskEvaluationId: null, skippedReason: "no_task_run_link" };
    }

    const artifacts = await this.db.query<{ id: string }>(
      `SELECT id
         FROM artifacts
        WHERE space_id = $1 AND run_id = $2
        ORDER BY created_at DESC, id DESC`,
      [spaceId, runEvaluation.run_id],
    );
    const outcome = runEvaluation.outcome_status;
    const now = new Date().toISOString();
    const inserted = await this.db.query<{ id: string }>(
      `INSERT INTO task_evaluations (
         id, space_id, task_id, run_id, run_evaluation_id, evaluator_type,
         score, confidence, summary, checklist_json, known_issues_json,
         evidence_artifact_ids, recommendation, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, 'run_evaluation_bridge',
         $6::float, $7::float, $8, $9::jsonb, $10::jsonb,
         $11::jsonb, $12, $13
       )
       RETURNING id`,
      [
        randomUUID(),
        spaceId,
        taskRun.task_id,
        runEvaluation.run_id,
        runEvaluation.id,
        taskScoreForOutcome(outcome),
        taskConfidenceForOutcome(outcome),
        taskSummaryFromRunEvaluation(runEvaluation),
        JSON.stringify(taskChecklistFromRunEvaluation(runEvaluation)),
        JSON.stringify(taskKnownIssuesFromRunEvaluation(runEvaluation)),
        JSON.stringify(artifacts.rows.map((row) => row.id)),
        taskRecommendationForOutcome(outcome),
        now,
      ],
    );
    return { taskEvaluationId: inserted.rows[0]?.id ?? null, skippedReason: null };
  }

  async getLatestRunFinalization(
    spaceId: string,
    runId: string,
  ): Promise<RunFinalizationRecord | null> {
    const result = await this.db.query<RunFinalizationRecord>(
      `SELECT id, space_id, run_id, finalizer_version, status,
              run_evaluation_id, task_evaluation_id, outcome_status,
              failure_layer, failure_reason_code, trajectory_status,
              skipped_reasons_json, error_json, metadata_json, finalized_at,
              created_at
         FROM run_finalizations
        WHERE space_id = $1 AND run_id = $2
        ORDER BY finalized_at DESC, id DESC
        LIMIT 1`,
      [spaceId, runId],
    );
    return result.rows[0] ?? null;
  }

  async getRunFinalizationByVersion(
    spaceId: string,
    runId: string,
    finalizerVersion: string,
  ): Promise<RunFinalizationRecord | null> {
    const result = await this.db.query<RunFinalizationRecord>(
      `SELECT id, space_id, run_id, finalizer_version, status,
              run_evaluation_id, task_evaluation_id, outcome_status,
              failure_layer, failure_reason_code, trajectory_status,
              skipped_reasons_json, error_json, metadata_json, finalized_at,
              created_at
         FROM run_finalizations
        WHERE space_id = $1 AND run_id = $2 AND finalizer_version = $3
        LIMIT 1`,
      [spaceId, runId, finalizerVersion],
    );
    return result.rows[0] ?? null;
  }

  async listRunFinalizations(
    spaceId: string,
    runId: string,
  ): Promise<RunFinalizationRecord[]> {
    const result = await this.db.query<RunFinalizationRecord>(
      `SELECT id, space_id, run_id, finalizer_version, status,
              run_evaluation_id, task_evaluation_id, outcome_status,
              failure_layer, failure_reason_code, trajectory_status,
              skipped_reasons_json, error_json, metadata_json, finalized_at,
              created_at
         FROM run_finalizations
        WHERE space_id = $1 AND run_id = $2
        ORDER BY finalized_at DESC, id DESC`,
      [spaceId, runId],
    );
    return result.rows;
  }

  async insertRunEvaluation(input: {
    space_id: string;
    run_id: string;
    outcome_status: string;
    failure_layer?: string | null;
    failure_reason_code?: string | null;
    trajectory_status: string;
    evidence_json?: unknown;
    rule_trace_json?: unknown;
    notes?: string | null;
    evaluated_at: string;
    evaluator_type?: string;
    evaluator_version?: string;
  }): Promise<RunEvaluationRecord> {
    const result = await this.db.query<RunEvaluationRecord>(
      `INSERT INTO run_evaluations (
          id, space_id, run_id, evaluator_type, evaluator_version,
          outcome_status, failure_layer, failure_reason_code,
          trajectory_status, evidence_json, rule_trace_json, notes, evaluated_at
       )
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12, $13)
       RETURNING id, space_id, run_id, evaluator_type, evaluator_version,
                 outcome_status, failure_layer, failure_reason_code,
                 trajectory_status, evidence_json, rule_trace_json, notes,
                 evaluated_at`,
      [
        randomUUID(),
        input.space_id,
        input.run_id,
        input.evaluator_type ?? "deterministic_harness",
        input.evaluator_version ?? "harness_eval.v1",
        input.outcome_status,
        input.failure_layer ?? null,
        input.failure_reason_code ?? null,
        input.trajectory_status,
        JSON.stringify(sanitizeEvidenceJson(input.evidence_json ?? {})),
        JSON.stringify(sanitizeEvidenceJson(input.rule_trace_json ?? [])),
        redactEvidenceText(input.notes),
        input.evaluated_at,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunEvaluation insert returned no row");
    return row;
  }

  async insertRunFinalization(input: {
    space_id: string;
    run_id: string;
    finalizer_version: string;
    status: "completed" | "failed";
    run_evaluation_id?: string | null;
    task_evaluation_id?: string | null;
    outcome_status?: string | null;
    failure_layer?: string | null;
    failure_reason_code?: string | null;
    trajectory_status?: string | null;
    skipped_reasons_json?: unknown;
    error_json?: unknown;
    metadata_json?: unknown;
    finalized_at: string;
    created_at: string;
  }): Promise<RunFinalizationRecord> {
    const result = await this.db.query<RunFinalizationRecord>(
      `INSERT INTO run_finalizations (
          id, space_id, run_id, finalizer_version, status,
          run_evaluation_id, task_evaluation_id, outcome_status,
          failure_layer, failure_reason_code, trajectory_status,
          skipped_reasons_json, error_json, metadata_json, finalized_at, created_at
       )
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
               $12::jsonb, $13::jsonb, $14::jsonb, $15, $16)
       RETURNING id, space_id, run_id, finalizer_version, status,
                 run_evaluation_id, task_evaluation_id, outcome_status,
                 failure_layer, failure_reason_code, trajectory_status,
                 skipped_reasons_json, error_json, metadata_json, finalized_at,
                 created_at`,
      [
        randomUUID(),
        input.space_id,
        input.run_id,
        input.finalizer_version,
        input.status,
        input.run_evaluation_id ?? null,
        input.task_evaluation_id ?? null,
        input.outcome_status ?? null,
        input.failure_layer ?? null,
        input.failure_reason_code ?? null,
        input.trajectory_status ?? null,
        JSON.stringify(sanitizeEvidenceJson(input.skipped_reasons_json ?? null)),
        JSON.stringify(sanitizeErrorJson(input.error_json ?? null)),
        JSON.stringify(sanitizeEvidenceJson(input.metadata_json ?? {})),
        input.finalized_at,
        input.created_at,
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunFinalization insert returned no row");
    return row;
  }

  /**
   * Resolve the Actor row for run evidence, creating it when absent — the
   * TS port of Python `runs.steps.resolve_run_actor`: instructing user actor
   * first, then the `agent_run` job actor for job dispatch, otherwise the
   * `run_execution` system actor. `run_steps.actor_id` is a non-null Actor FK,
   * so worker/request identifiers must never be written there directly.
   */
  async resolveRunActorId(
    run: Pick<RunRecord, "space_id" | "instructed_by_user_id">,
    commandSource: string,
  ): Promise<string> {
    if (run.instructed_by_user_id) {
      const existing = await this.db.query<{ id: string }>(
        `SELECT id FROM actors
          WHERE actor_type = 'user' AND user_id = $1 AND space_id = $2
            AND status = 'active'
          LIMIT 1`,
        [run.instructed_by_user_id, run.space_id],
      );
      if (existing.rows[0]) return existing.rows[0].id;
      const created = await this.db.query<{ id: string }>(
        `INSERT INTO actors (
            id, space_id, actor_type, user_id, agent_id, service_name,
            display_name, status, metadata_json, created_at, updated_at
         )
         VALUES ($1, $2, 'user', $3, NULL, NULL, NULL, 'active', '{}'::jsonb, $4, $4)
         RETURNING id`,
        [
          randomUUID(),
          run.space_id,
          run.instructed_by_user_id,
          new Date().toISOString(),
        ],
      );
      const row = created.rows[0];
      if (!row) throw new Error("user actor insert returned no row");
      return row.id;
    }

    const actorType = commandSource === "job" ? "job" : "system";
    const serviceName = commandSource === "job" ? "agent_run" : "run_execution";
    const existing = await this.db.query<{ id: string }>(
      `SELECT id FROM actors
        WHERE actor_type = $1 AND service_name = $2 AND space_id = $3
          AND status = 'active'
        LIMIT 1`,
      [actorType, serviceName, run.space_id],
    );
    if (existing.rows[0]) return existing.rows[0].id;
    const created = await this.db.query<{ id: string }>(
      `INSERT INTO actors (
          id, space_id, actor_type, user_id, agent_id, service_name,
          display_name, status, metadata_json, created_at, updated_at
       )
       VALUES ($1, $2, $3, NULL, NULL, $4, NULL, 'active', '{}'::jsonb, $5, $5)
       RETURNING id`,
      [randomUUID(), run.space_id, actorType, serviceName, new Date().toISOString()],
    );
    const row = created.rows[0];
    if (!row) throw new Error(`${actorType} actor insert returned no row`);
    return row.id;
  }

  async markRunRunning(input: {
    run_id: string;
    space_id: string;
    started_at: string;
    required_sandbox_level?: string | null;
  }): Promise<RunRecord | null> {
    const result = await this.db.query<RunRecord>(
      `UPDATE runs
          SET status = 'running',
              started_at = $3,
              updated_at = $3,
              required_sandbox_level = COALESCE($4, required_sandbox_level)
        WHERE space_id = $1 AND id = $2 AND status = 'queued'
        RETURNING id, space_id, agent_id, agent_version_id, run_type, status, mode,
                  prompt, instruction, workspace_id, session_id, project_id,
                  adapter_type, model_provider_id,
                  required_sandbox_level, trigger_origin, instructed_by_user_id, error_message, started_at, ended_at`,
      [
        input.space_id,
        input.run_id,
        input.started_at,
        input.required_sandbox_level ?? null,
      ],
    );
    return result.rows[0] ?? null;
  }

  async updateRunSandboxLevel(input: {
    run_id: string;
    space_id: string;
    required_sandbox_level: string;
  }): Promise<void> {
    await this.db.query(
      `UPDATE runs
          SET required_sandbox_level = $3, updated_at = now()
        WHERE space_id = $1 AND id = $2 AND status = 'running'`,
      [input.space_id, input.run_id, input.required_sandbox_level],
    );
  }

  async markRunTerminal(input: RunTerminalUpdate): Promise<RunRecord | null> {
    // The public run read model surfaces output through output_json.output_text
    // (Python parity), so the terminal write folds it in before sanitization.
    const outputJson = sanitizeEvidenceJson({
      ...(recordValue(input.output_json)),
      ...(input.output_text ? { output_text: input.output_text } : {}),
    });
    const errorJson = sanitizeErrorJson(input.error_json ?? {});
    const usageJson = sanitizeEvidenceJson(input.usage_json ?? {});
    const result = await this.db.query<RunRecord>(
      `UPDATE runs
          SET status = $3,
              output_json = $4::jsonb,
              error_json = $5::jsonb,
              exit_code = $6,
              usage_json = $7::jsonb,
              ended_at = $8,
              updated_at = $8,
              error_message = $9
        WHERE space_id = $1 AND id = $2
          AND status NOT IN ('succeeded', 'failed', 'degraded', 'cancelled')
        RETURNING id, space_id, agent_id, agent_version_id, run_type, status, mode,
                  prompt, instruction, workspace_id, session_id, project_id,
                  adapter_type, model_provider_id,
                  required_sandbox_level, trigger_origin, instructed_by_user_id, error_message, started_at, ended_at`,
      [
        input.space_id,
        input.run_id,
        input.status,
        JSON.stringify(outputJson),
        JSON.stringify(errorJson),
        input.exit_code ?? null,
        JSON.stringify(usageJson),
        input.completed_at,
        redactEvidenceText(extractErrorMessage(errorJson)),
      ],
    );
    return result.rows[0] ?? null;
  }

  async appendRunEvent(input: RunEventInput): Promise<RunEventRecord> {
    // $1/$2 appear both as inserted values (deduced as the varchar column
    // type) and in the scalar subquery comparison (deduced as text via the
    // text equality operator). Without the explicit ::varchar casts PostgreSQL
    // fails with "inconsistent types deduced for parameter".
    const result = await this.db.query<RunEventRecord>(
      `INSERT INTO run_events (
          id, space_id, run_id, event_index, step_id, actor_id, event_type,
          status, summary, error_code, error_message, workspace_id,
          artifact_id, proposal_id, data_exposure_level,
          trust_level, metadata_json, created_at
       )
       VALUES ($3, $1, $2,
               (SELECT COALESCE(MAX(event_index) + 1, 0)
                  FROM run_events
                 WHERE space_id = $1::varchar AND run_id = $2::varchar),
               $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
               $16::jsonb, $17)
       RETURNING id, space_id, run_id, event_index, event_type, status`,
      [
        input.space_id,
        input.run_id,
        randomUUID(),
        input.step_id ?? null,
        input.actor_id ?? null,
        input.event_type,
        input.status,
        redactEvidenceText(input.summary),
        input.error_code ?? null,
        redactEvidenceText(input.error_message),
        input.workspace_id ?? null,
        input.artifact_id ?? null,
        input.proposal_id ?? null,
        input.data_exposure_level ?? null,
        input.trust_level ?? null,
        JSON.stringify(sanitizeEvidenceJson(input.metadata_json ?? {})),
        new Date().toISOString(),
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunEvent append returned no row");
    return row;
  }

  async createRunStep(input: RunStepInput): Promise<RunStepRecord> {
    // Same ::varchar casts as appendRunEvent — see the comment there.
    const result = await this.db.query<RunStepRecord>(
      `INSERT INTO run_steps (
          id, space_id, run_id, parent_step_id, actor_id, step_index,
          step_type, status, title, workspace_id, session_id, task_id,
          artifact_id, proposal_id, started_at, ended_at,
          input_summary, output_summary, error_type, error_message,
          metadata_json, created_at, updated_at
       )
       VALUES ($3, $1, $2, $4, $5,
               (SELECT COALESCE(MAX(step_index) + 1, 0)
                  FROM run_steps
                 WHERE space_id = $1::varchar AND run_id = $2::varchar),
               $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
               $17, $18, $19, $20::jsonb, $21, $21)
       RETURNING id, space_id, run_id, step_index, step_type, status`,
      [
        input.space_id,
        input.run_id,
        randomUUID(),
        input.parent_step_id ?? null,
        input.actor_id,
        input.step_type,
        input.status,
        input.title ?? null,
        input.workspace_id ?? null,
        input.session_id ?? null,
        input.task_id ?? null,
        input.artifact_id ?? null,
        input.proposal_id ?? null,
        input.started_at ?? null,
        input.ended_at ?? null,
        redactEvidenceText(input.input_summary),
        redactEvidenceText(input.output_summary),
        input.error_type ?? null,
        redactEvidenceText(input.error_message),
        JSON.stringify(sanitizeEvidenceJson(input.metadata_json ?? {})),
        new Date().toISOString(),
      ],
    );
    const row = result.rows[0];
    if (!row) throw new Error("RunStep insert returned no row");
    return row;
  }

  async updateRunStepStatus(input: {
    step_id: string;
    run_id: string;
    space_id: string;
    status: "succeeded" | "failed" | "skipped" | "cancelled";
    ended_at: string;
    output_summary?: string | null;
    error_type?: string | null;
    error_message?: string | null;
  }): Promise<boolean> {
    const result = await this.db.query(
      `UPDATE run_steps
          SET status = $4,
              ended_at = $5,
              output_summary = COALESCE($6, output_summary),
              error_type = COALESCE($7, error_type),
              error_message = COALESCE($8, error_message),
              updated_at = $5
        WHERE id = $1 AND run_id = $2 AND space_id = $3`,
      [
        input.step_id,
        input.run_id,
        input.space_id,
        input.status,
        input.ended_at,
        redactEvidenceText(input.output_summary),
        input.error_type ?? null,
        redactEvidenceText(input.error_message),
      ],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async tryAcquireExecutionLock(input: {
    run_id: string;
    worker_id: string;
    job_id?: string | null;
  }): Promise<boolean> {
    const result = await this.db.query(
      `INSERT INTO run_execution_locks (run_id, locked_at, worker_id, job_id)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (run_id) DO NOTHING`,
      [input.run_id, new Date().toISOString(), input.worker_id, input.job_id ?? null],
    );
    return (result.rowCount ?? 0) === 1;
  }

  async releaseExecutionLock(runId: string): Promise<void> {
    await this.db.query("DELETE FROM run_execution_locks WHERE run_id = $1", [runId]);
  }
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Trim a value to a non-empty string, or "" when absent/non-string. */
function trimmed(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function extractErrorMessage(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const message = record.error_message ?? record.error_text ?? record.message;
  return typeof message === "string" ? message : null;
}

function addOptionalFilter(
  clauses: string[],
  params: unknown[],
  column: string,
  value: string | null | undefined,
): void {
  if (value == null || value === "") return;
  params.push(value);
  clauses.push(`${column} = $${params.length}`);
}

function validateRunCreateInput(input: RunCreateInput): void {
  assertOneOf(input.mode, ["live", "dry_run"], "mode");
  assertOneOf(
    input.run_type,
    ["agent", "system", "workflow", "validation", "reflection", "export", "evolution"],
    "run_type",
  );
  assertOneOf(input.trigger_origin, ["manual", "automation", "job", "system"], "trigger_origin");
}

function assertOneOf(value: string, allowed: readonly string[], field: string): void {
  if (allowed.includes(value)) return;
  throw new RunCreateValidationError(
    `Invalid ${field} '${value}'. Must be one of: ${allowed.slice().sort().join(", ")}`,
  );
}

function taskScoreForOutcome(outcome: string): number | null {
  if (outcome === "passed") return 1;
  if (outcome === "partial") return 0.5;
  if (outcome === "failed") return 0;
  return null;
}

function taskConfidenceForOutcome(outcome: string): number {
  if (outcome === "passed" || outcome === "failed") return 1;
  if (outcome === "partial") return 0.7;
  return 0.3;
}

function taskRecommendationForOutcome(outcome: string): string {
  if (outcome === "passed") return "accept";
  if (outcome === "partial") return "review";
  if (outcome === "failed") return "retry";
  return "needs_evidence";
}

function taskSummaryFromRunEvaluation(row: RunEvaluationRecord): string {
  const outcome = row.outcome_status;
  const trajectory = row.trajectory_status;
  if (outcome === "passed" && trajectory === "acceptable") {
    return "Run evaluation passed with acceptable trajectory.";
  }
  if (outcome === "failed") {
    if (row.failure_layer && row.failure_reason_code) {
      return `Run evaluation failed at ${row.failure_layer}: ${row.failure_reason_code}.`;
    }
    if (row.failure_layer) return `Run evaluation failed at ${row.failure_layer}.`;
    if (row.failure_reason_code) return `Run evaluation failed: ${row.failure_reason_code}.`;
    return "Run evaluation failed.";
  }
  if (outcome === "partial") return `Run evaluation is partial; trajectory ${trajectory}.`;
  if (outcome === "unknown") return `Run evaluation is unknown; trajectory ${trajectory}.`;
  return `Run evaluation ${outcome}; trajectory ${trajectory}.`;
}

function taskChecklistFromRunEvaluation(row: RunEvaluationRecord): Record<string, unknown> {
  return {
    run_evaluation_id: row.id,
    run_id: row.run_id,
    outcome_status: row.outcome_status,
    trajectory_status: row.trajectory_status,
    failure_layer: row.failure_layer,
    failure_reason_code: row.failure_reason_code,
    evaluator_version: row.evaluator_version,
  };
}

function taskKnownIssuesFromRunEvaluation(row: RunEvaluationRecord): Record<string, unknown>[] {
  const issues: Record<string, unknown>[] = [];
  if (row.failure_layer || row.failure_reason_code) {
    issues.push({
      kind: "failure",
      failure_layer: row.failure_layer,
      failure_reason_code: row.failure_reason_code,
    });
  }
  const evidence = recordValue(row.evidence_json);
  collectIssueList(issues, recordValue(evidence.context).warnings, "context_warning", "code");
  const materialization = recordValue(evidence.materialization);
  collectIssueList(issues, materialization.codes, "materialization_code", "code");
  collectIssueList(issues, materialization.errors, "materialization_error", "error");
  collectIssueList(issues, materialization.code_patch_warnings, "materialization_warning", "code");
  const validation = recordValue(evidence.validation);
  if (typeof validation.status === "string" && validation.status) {
    issues.push({ kind: "validation_status", status: validation.status });
  }
  collectIssueList(issues, validation.signals, "validation_signal", "code");
  if (row.trajectory_status === "unsafe") {
    issues.push({ kind: "trajectory", status: "unsafe" });
  }
  return issues;
}

function collectIssueList(
  issues: Record<string, unknown>[],
  value: unknown,
  kind: string,
  field: string,
): void {
  if (!Array.isArray(value)) return;
  for (const item of value) {
    if (item) issues.push({ kind, [field]: item });
  }
}
