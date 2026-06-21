import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
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
import {
  addOptionalFilter,
  extractErrorMessage,
  recordValue,
  requiredSandboxLevelForRun,
  trimmed,
  validateRunCreateInput,
} from "./runRepositoryHelpers";
import {
  type ArtifactSummaryRecord,
  type ModelProviderSummaryRecord,
  type ProposalSummaryRecord,
  type Queryable,
  RunCreateValidationError,
  type RunChatResultRecord,
  type RunCreateInput,
  type RunEvaluationRecord,
  type RunEventDetailRecord,
  type RunEventInput,
  type RunEventPage,
  type RunEventPageFilters,
  type RunEventRecord,
  type RunFinalizationRecord,
  type RunListFilters,
  type RunRecord,
  type RunStepDetailRecord,
  type RunStepInput,
  type RunStepRecord,
  type RunTerminalUpdate,
} from "./runRepositoryTypes";
import {
  taskChecklistFromRunEvaluation,
  taskConfidenceForOutcome,
  taskKnownIssuesFromRunEvaluation,
  taskRecommendationForOutcome,
  taskScoreForOutcome,
  taskSummaryFromRunEvaluation,
} from "./taskEvaluationProjection";

export {
  RunCreateValidationError,
  type ArtifactSummaryRecord,
  type ModelProviderSummaryRecord,
  type ProposalSummaryRecord,
  type QueryResult,
  type Queryable,
  type RunChatResultRecord,
  type RunCreateInput,
  type RunEvaluationRecord,
  type RunEventDetailRecord,
  type RunEventInput,
  type RunEventPage,
  type RunEventPageFilters,
  type RunEventRecord,
  type RunFinalizationRecord,
  type RunListFilters,
  type RunRecord,
  type RunStepDetailRecord,
  type RunStepInput,
  type RunStepRecord,
  type RunTerminalUpdate,
} from "./runRepositoryTypes";

interface RuntimeProfileForRun {
  id: string;
  space_id: string;
  agent_id: string;
  name: string;
  adapter_type: string;
  model_provider_id: string | null;
  model_name: string | null;
  credential_profile_id: string | null;
  runtime_config_json: unknown;
  runtime_policy_json: unknown;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export class PgRunRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ServerConfig): PgRunRepository {
    if (!config.databaseUrl) {
      throw new Error("Run repository requires SERVER_DATABASE_URL");
    }
    return new PgRunRepository(getDbPool(config.databaseUrl));
  }

  async recoverStaleRuns(staleAfterSeconds = 3600, now = new Date()): Promise<number> {
    const cutoff = new Date(
      now.getTime() - Math.max(1, staleAfterSeconds) * 1000,
    ).toISOString();
    const completedAt = now.toISOString();
    const errorMessage = "Run timed out (stale running recovery at server worker startup)";
    const errorJson = sanitizeErrorJson({
      error_code: "stale_run_recovered",
      error_text: "Run was stuck in running status and was recovered at server worker startup",
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
    const runtimeProfile = input.runtime_profile_id
      ? await this.requireRuntimeProfileForRun(
          input.space_id,
          input.agent_id,
          input.runtime_profile_id,
        )
      : await this.getDefaultRuntimeProfileForRun(input.space_id, input.agent_id);
    // Resolve adapter type + model provider from the agent version and space
    // defaults when the caller did not pass them explicitly. The chat path
    // passes neither, so without this the run is created with a null provider
    // and a `model_api` execution fails closed with `model_provider_required`.
    const resolved = await this.resolveRunModelConfig(
      input.space_id,
      agent.current_version_id,
      input,
      runtimeProfile,
    );
    const requiredSandboxLevel = requiredSandboxLevelForRun(
      resolved.adapterType,
      input.workspace_id,
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
    const capabilitiesJson = normalizeRunCapabilitiesJson(input.capabilities_json);
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
          runtime_profile_id: runtimeProfile?.id ?? null,
          session_id: input.session_id ?? null,
          workspace_id: input.workspace_id ?? null,
          project_id: input.project_id ?? null,
          user_message: input.prompt ?? input.instruction ?? null,
          manual_context: [],
          capabilities_json: capabilitiesJson,
        }),
        now,
      ],
    );

    const runId = randomUUID();
    const modelOverride = {
      ...(input.model_override_json ?? {}),
      ...(resolved.modelName || resolved.modelProviderId
        ? { model: resolved.modelName, source: resolved.source }
        : {}),
    };
    const modelOverrideJson = Object.keys(modelOverride).length > 0
      ? JSON.stringify(modelOverride)
      : null;
    const runtimeProfileSnapshotJson = runtimeProfile
      ? JSON.stringify(runtimeProfileSnapshot(runtimeProfile))
      : null;
    const result = await this.db.query<RunRecord>(
      `INSERT INTO runs (
          id, space_id, agent_id, agent_version_id, runtime_profile_id,
          context_snapshot_id,
          workspace_id, session_id, parent_run_id, instructed_by_user_id,
          run_type, trigger_origin, status, mode, prompt, instruction,
          scheduled_at, created_at, updated_at, adapter_type, capability_id,
          capabilities_json, model_provider_id, model_override_json, runtime_profile_snapshot_json,
          required_sandbox_level, usage_accuracy, visibility, project_id, source
       )
       VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
          $11, $12, 'queued', $13, $14, $15, $16, $17, $17,
          $18, $19, $20::jsonb, $21, $22::jsonb, $23::jsonb, $24, 'estimated',
          'space_shared', $25, 'managed'
       )
       RETURNING id, space_id, agent_id, agent_version_id, runtime_profile_id,
                 context_snapshot_id,
                 run_type, status, mode, prompt, instruction, workspace_id,
                 session_id, parent_run_id, project_id, scheduled_at,
                 adapter_type, capability_id, capabilities_json, model_provider_id,
                 model_override_json, runtime_profile_snapshot_json,
                 required_sandbox_level, trigger_origin,
                 instructed_by_user_id, error_message, error_json, output_json,
                 usage_json, started_at, ended_at, created_at, updated_at,
                 visibility`,
      [
        runId,
        input.space_id,
        input.agent_id,
        agent.current_version_id,
        runtimeProfile?.id ?? null,
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
        JSON.stringify(capabilitiesJson),
        resolved.modelProviderId,
        modelOverrideJson,
        runtimeProfileSnapshotJson,
        requiredSandboxLevel,
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

  private async requireRuntimeProfileForRun(
    spaceId: string,
    agentId: string,
    runtimeProfileId: string,
  ): Promise<RuntimeProfileForRun> {
    const profile = await this.getRuntimeProfileForRun(spaceId, agentId, runtimeProfileId);
    if (!profile) {
      throw new RunCreateValidationError(
        `Runtime profile '${runtimeProfileId}' not found for Agent '${agentId}' in this space`,
        404,
      );
    }
    if (!profile.enabled) {
      throw new RunCreateValidationError(
        `Runtime profile '${runtimeProfileId}' is disabled`,
        409,
      );
    }
    return profile;
  }

  private async getDefaultRuntimeProfileForRun(
    spaceId: string,
    agentId: string,
  ): Promise<RuntimeProfileForRun | null> {
    const result = await this.db.query<RuntimeProfileForRun>(
      `SELECT id, space_id, agent_id, name, adapter_type, model_provider_id,
              model_name, credential_profile_id, runtime_config_json,
              runtime_policy_json, enabled, is_default, created_at, updated_at
         FROM agent_runtime_profiles
        WHERE space_id = $1
          AND agent_id = $2
          AND enabled = true
        ORDER BY is_default DESC, created_at ASC, id ASC
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }

  private async getRuntimeProfileForRun(
    spaceId: string,
    agentId: string,
    runtimeProfileId: string,
  ): Promise<RuntimeProfileForRun | null> {
    const result = await this.db.query<RuntimeProfileForRun>(
      `SELECT id, space_id, agent_id, name, adapter_type, model_provider_id,
              model_name, credential_profile_id, runtime_config_json,
              runtime_policy_json, enabled, is_default, created_at, updated_at
         FROM agent_runtime_profiles
        WHERE space_id = $1 AND agent_id = $2 AND id = $3
        LIMIT 1`,
      [spaceId, agentId, runtimeProfileId],
    );
    return result.rows[0] ?? null;
  }

  /**
   * Resolve adapter type + model provider + model for a new run. Priority:
   * runtime profile → legacy explicit request → agent version default →
   * space default provider (for adapters that require a provider).
   */
  private async resolveRunModelConfig(
    spaceId: string,
    versionId: string,
    input: RunCreateInput,
    runtimeProfile: RuntimeProfileForRun | null,
  ): Promise<{
    adapterType: string;
    modelProviderId: string | null;
    modelName: string | null;
    source: string;
  }> {
    const version = await this.loadAgentVersionForResolution(spaceId, versionId);
    const runtimeConfig = recordValue(version?.runtime_config_json);
    const runtimePolicy = recordValue(version?.runtime_policy_json);
    const profileRuntimeConfig = recordValue(runtimeProfile?.runtime_config_json);
    const profileRuntimePolicy = recordValue(runtimeProfile?.runtime_policy_json);
    const adapterType =
      trimmed(runtimeProfile?.adapter_type) ||
      trimmed(profileRuntimeConfig.adapter_type) ||
      trimmed(profileRuntimePolicy.default_adapter_type) ||
      trimmed(input.adapter_type) ||
      trimmed(runtimeConfig.adapter_type) ||
      trimmed(runtimePolicy.default_adapter_type) ||
      "model_api";
    const mode =
      BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType]?.model
        .model_provider_mode ?? "none";
    const requestModel = runtimeProfile ? null : trimmed(input.model) || null;
    const profileModel = trimmed(runtimeProfile?.model_name) || null;
    const versionModel = trimmed(version?.model_name) || null;

    if (runtimeProfile?.model_provider_id) {
      return {
        adapterType,
        modelProviderId: runtimeProfile.model_provider_id,
        modelName: profileModel ?? versionModel,
        source: "runtime_profile",
      };
    }
    if (!runtimeProfile && input.model_provider_id) {
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
        modelName: requestModel ?? profileModel ?? versionModel,
        source: "agent_default",
      };
    }
    if ((adapterType === "claude_code" || adapterType === "codex_cli") && version?.model_provider_id) {
      return {
        adapterType,
        modelProviderId: version.model_provider_id,
        modelName: requestModel ?? profileModel ?? versionModel,
        source: "agent_default",
      };
    }
    if (mode === "required") {
      const fallback = await this.resolveDefaultProvider(spaceId, adapterType);
      if (fallback) {
        return {
          adapterType,
          modelProviderId: fallback.id,
          modelName: requestModel ?? profileModel ?? versionModel ?? fallback.default_model,
          source: fallback.source,
        };
      }
    }
    return {
      adapterType,
      modelProviderId: null,
      modelName: requestModel ?? profileModel,
      source: runtimeProfile && profileModel ? "runtime_profile" : requestModel ? "request" : "none",
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
      `SELECT p.id,
              p.default_model,
              jsonb_set(
                COALESCE(p.config_json, '{}'::jsonb),
                '{is_default}',
                to_jsonb(g.is_default),
                true
              ) AS config_json
         FROM model_provider_space_grants g
         JOIN model_providers p ON p.id = g.provider_id
        WHERE g.space_id = $1
          AND g.enabled = TRUE
          AND p.enabled = TRUE`,
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
              r.runtime_profile_id,
              av.system_prompt AS system_prompt,
              r.context_snapshot_id, r.run_type, r.status, r.mode, r.prompt,
              r.instruction, r.workspace_id, r.session_id, r.parent_run_id,
              r.project_id, r.scheduled_at, r.adapter_type, r.capability_id,
              r.capabilities_json, r.model_provider_id, r.model_override_json, r.required_sandbox_level,
              r.runtime_profile_snapshot_json,
              COALESCE(r.runtime_profile_snapshot_json->'runtime_config_json', av.runtime_config_json) AS runtime_config_json,
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
      `SELECT id, space_id, agent_id, agent_version_id, runtime_profile_id,
              context_snapshot_id,
              run_type, status, mode, prompt, instruction, workspace_id,
              session_id, parent_run_id, project_id, scheduled_at, adapter_type,
              capability_id, capabilities_json, model_provider_id, model_override_json,
              runtime_profile_snapshot_json,
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
      `SELECT p.id, p.name, p.provider_type, p.default_model, p.enabled, p.credential_id
         FROM model_provider_space_grants g
         JOIN model_providers p ON p.id = g.provider_id
        WHERE g.space_id = $1
          AND g.provider_id = $2
          AND g.enabled = TRUE`,
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

  async listRunEventsPage(
    spaceId: string,
    runId: string,
    filters: RunEventPageFilters,
  ): Promise<RunEventPage> {
    const params: unknown[] = [spaceId, runId, filters.from_event_index];
    const clauses = [
      "space_id = $1",
      "run_id = $2",
      "event_index >= $3",
    ];
    addOptionalFilter(clauses, params, "event_type", filters.event_type);
    addOptionalFilter(clauses, params, "status", filters.status);
    const limitParam = params.length + 1;
    const rows = await this.db.query<RunEventDetailRecord>(
      `SELECT id, space_id, run_id, step_id, actor_id, event_index, event_type,
              status, summary, error_code, error_message, workspace_id,
              artifact_id, proposal_id, data_exposure_level, trust_level,
              metadata_json, created_at
         FROM run_events
        WHERE ${clauses.join(" AND ")}
        ORDER BY event_index ASC, id ASC
        LIMIT $${limitParam}`,
      [...params, filters.limit],
    );

    const totalParams: unknown[] = [spaceId, runId];
    const totalClauses = ["space_id = $1", "run_id = $2"];
    addOptionalFilter(totalClauses, totalParams, "event_type", filters.event_type);
    addOptionalFilter(totalClauses, totalParams, "status", filters.status);
    const total = await this.db.query<{ total: string | number }>(
      `SELECT COALESCE(MAX(event_index) + 1, 0)::text AS total
         FROM run_events
        WHERE ${totalClauses.join(" AND ")}`,
      totalParams,
    );

    return {
      items: rows.rows,
      total: Number(total.rows[0]?.total ?? 0),
      limit: filters.limit,
      offset: filters.from_event_index,
    };
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
   * Resolve actor precedence: instructing user actor first, then the
   * `agent_run` job actor for job dispatch, otherwise the
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
      `WITH updated AS (
         UPDATE runs
            SET status = 'running',
                started_at = $3,
                updated_at = $3,
                required_sandbox_level = COALESCE($4, required_sandbox_level)
          WHERE space_id = $1 AND id = $2 AND status = 'queued'
          RETURNING id, space_id, agent_id, agent_version_id, runtime_profile_id,
                    runtime_profile_snapshot_json, run_type, status, mode,
                    prompt, instruction, workspace_id, session_id, project_id,
                    adapter_type, capability_id, capabilities_json, model_provider_id,
                    required_sandbox_level, trigger_origin, instructed_by_user_id, error_message,
                    started_at, ended_at
       )
       SELECT u.*,
              COALESCE(u.runtime_profile_snapshot_json->'runtime_config_json', av.runtime_config_json) AS runtime_config_json
         FROM updated u
         LEFT JOIN agent_versions av
           ON av.id = u.agent_version_id
          AND av.space_id = u.space_id
          AND av.agent_id = u.agent_id`,
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
    // The public run read model surfaces output through output_json.output_text,
    // so the terminal write folds it in before sanitization.
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

function normalizeRunCapabilitiesJson(value: unknown[] | null | undefined): string[] {
  if (value === undefined || value === null) return [];
  const result = value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
  if (result.length !== value.length) {
    throw new RunCreateValidationError("capabilities_json must contain non-empty strings");
  }
  return [...new Set(result)];
}

function runtimeProfileSnapshot(profile: RuntimeProfileForRun): Record<string, unknown> {
  return {
    id: profile.id,
    name: profile.name,
    adapter_type: profile.adapter_type,
    model_provider_id: profile.model_provider_id,
    model_name: profile.model_name,
    credential_profile_id: profile.credential_profile_id,
    runtime_config_json: recordValue(profile.runtime_config_json),
    runtime_policy_json: recordValue(profile.runtime_policy_json),
    is_default: profile.is_default,
  };
}
