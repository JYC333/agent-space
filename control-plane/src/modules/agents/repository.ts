import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { getDbPool, type Pool, type PoolClient } from "../../db/pool";
import { withTransaction } from "../../db/tx";
import { HttpError } from "../routeUtils/common";
import {
  BUILTIN_RUNTIME_ADAPTER_SPECS,
  type RuntimeAdapterType,
} from "../runtimeAdapters/specs";

interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

const DEFAULT_MODEL_CONFIG = { model: "claude-sonnet-4-6", max_tokens: 8192 };
const DEFAULT_MEMORY_POLICY = {
  readable_scopes: ["system", "space", "user", "workspace", "capability", "agent"],
  writable_scopes: ["agent"],
  readable_types: ["preference", "semantic", "episodic", "procedural", "project"],
};
const DEFAULT_RUNTIME_POLICY = {
  risk_level: "medium",
  max_run_time_seconds: 300,
  allowed_adapter_types: [
    "capability",
    "model_api",
    "claude_code",
    "codex_cli",
    "opencode",
    "gemini_cli",
  ],
  default_adapter_type: "model_api",
};
const DEFAULT_RUNTIME_CONFIG = { risk_level: "medium", max_run_time_seconds: 300 };

export interface AgentRecord {
  id: string;
  space_id: string;
  owner_user_id: string | null;
  name: string;
  description: string | null;
  role_instruction: string | null;
  status: string;
  agent_kind: string;
  source_template_id: string | null;
  source_template_version_id: string | null;
  current_version_id: string | null;
  visibility: string;
  created_at: unknown;
  updated_at: unknown;
  model_provider_id?: string | null;
  provider_name?: string | null;
  provider_type?: string | null;
  model_name?: string | null;
  system_prompt?: string | null;
  runtime_policy_json?: unknown;
}

export interface AgentVersionRecord {
  id: string;
  agent_id: string;
  space_id: string;
  version_label: string;
  model_provider_id: string | null;
  model_name: string | null;
  system_prompt: string | null;
  model_config_json: Record<string, unknown>;
  runtime_config_json: Record<string, unknown>;
  context_policy_json: Record<string, unknown>;
  memory_policy_json: Record<string, unknown>;
  capabilities_json: unknown[];
  tool_permissions_json: Record<string, unknown>;
  runtime_policy_json: Record<string, unknown>;
  tool_policy_json: Record<string, unknown>;
  output_policy_json: Record<string, unknown>;
  schedule_config_json: Record<string, unknown>;
  output_schema_json: Record<string, unknown>;
  source_proposal_id: string | null;
  source_activity_id: string | null;
  created_at: unknown;
  published_at: unknown | null;
  archived_at: unknown | null;
}

export interface AgentOut {
  id: string;
  space_id: string;
  created_by_user_id: string | null;
  name: string;
  description: string | null;
  visibility: string;
  role_instruction: string | null;
  status: string;
  agent_kind: string;
  current_version_id: string | null;
  source_template_id: string | null;
  source_template_version_id: string | null;
  model: {
    provider_id: string | null;
    provider_name: string | null;
    provider_type: string | null;
    model: string | null;
  } | null;
  adapter_type: string | null;
  requires_model_provider: boolean;
  system_prompt: string | null;
  created_at: unknown;
  updated_at: unknown;
}

export interface AssistantSettingsRecord {
  id: string;
  space_id: string;
  assistant_agent_id: string | null;
  response_style: string | null;
  verbosity: string | null;
  default_context_toggles_json: Record<string, boolean>;
  default_project_id: string | null;
  proposal_style: string | null;
  model_preferences_json: Record<string, unknown>;
  created_at: unknown;
  updated_at: unknown;
}

const AGENT_COLUMNS = `
  a.id, a.space_id, a.owner_user_id, a.name, a.description, a.role_instruction,
  a.status, a.agent_kind, a.source_template_id, a.source_template_version_id,
  a.current_version_id, a.visibility, a.created_at, a.updated_at,
  av.model_provider_id, av.model_name, av.system_prompt, av.runtime_policy_json,
  mp.name AS provider_name, mp.provider_type AS provider_type
`;

const VERSION_COLUMN_NAMES = [
  "id",
  "agent_id",
  "space_id",
  "version_label",
  "model_provider_id",
  "model_name",
  "system_prompt",
  "model_config_json",
  "runtime_config_json",
  "context_policy_json",
  "memory_policy_json",
  "capabilities_json",
  "tool_permissions_json",
  "runtime_policy_json",
  "tool_policy_json",
  "output_policy_json",
  "schedule_config_json",
  "output_schema_json",
  "source_proposal_id",
  "source_activity_id",
  "created_at",
  "published_at",
  "archived_at",
] as const;

const VERSION_COLUMNS = VERSION_COLUMN_NAMES.join(", ");

function versionColumns(alias: string): string {
  return VERSION_COLUMN_NAMES.map((column) => `${alias}.${column}`).join(", ");
}

const SETTINGS_COLUMNS = `
  id, space_id, assistant_agent_id, response_style, verbosity,
  default_context_toggles_json, default_project_id, proposal_style,
  model_preferences_json, created_at, updated_at
`;

export interface AgentChatRecord {
  id: string;
  space_id: string;
  name: string | null;
  current_version_id: string | null;
}

export class PgAgentChatRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgAgentChatRepository {
    if (!config.databaseUrl) {
      throw new Error("Agent chat repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgAgentChatRepository(getDbPool(config.databaseUrl));
  }

  async getAgentForChat(
    spaceId: string,
    agentId: string,
  ): Promise<AgentChatRecord | null> {
    const result: QueryResult<AgentChatRecord> = await this.db.query<AgentChatRecord>(
      `SELECT id, space_id, name, current_version_id
         FROM agents
        WHERE space_id = $1 AND id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }
}

export class PgAgentRepository {
  constructor(private readonly pool: Pool) {}

  static fromConfig(config: ControlPlaneConfig): PgAgentRepository {
    if (!config.databaseUrl) {
      throw new HttpError(502, "CONTROL_PLANE_DATABASE_URL is required");
    }
    return new PgAgentRepository(getDbPool(config.databaseUrl));
  }

  async list(
    spaceId: string,
    filters: {
      createdByUserId?: string | null;
      visibility?: string | null;
      status?: string | null;
      limit: number;
      offset: number;
    },
  ): Promise<AgentOut[]> {
    const params: unknown[] = [spaceId];
    const clauses = ["a.space_id = $1"];
    if (filters.createdByUserId) {
      params.push(filters.createdByUserId);
      clauses.push(`a.owner_user_id = $${params.length}`);
    }
    if (filters.visibility) {
      params.push(filters.visibility);
      clauses.push(`a.visibility = $${params.length}`);
    }
    if (filters.status) {
      const statuses = filters.status.split(",").map((s) => s.trim()).filter(Boolean);
      if (statuses.length === 1) {
        params.push(statuses[0]);
        clauses.push(`a.status = $${params.length}`);
      } else if (statuses.length > 1) {
        params.push(statuses);
        clauses.push(`a.status = ANY($${params.length}::text[])`);
      }
    }
    params.push(filters.limit, filters.offset);
    const result = await this.pool.query<AgentRecord>(
      `SELECT ${AGENT_COLUMNS}
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id
         LEFT JOIN model_providers mp ON mp.id = av.model_provider_id
        WHERE ${clauses.join(" AND ")}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT $${params.length - 1} OFFSET $${params.length}`,
      params,
    );
    return result.rows.map(agentOut);
  }

  async get(spaceId: string, agentId: string): Promise<AgentOut | null> {
    const result = await this.pool.query<AgentRecord>(
      `SELECT ${AGENT_COLUMNS}
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id
         LEFT JOIN model_providers mp ON mp.id = av.model_provider_id
        WHERE a.space_id = $1 AND a.id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ? agentOut(result.rows[0]) : null;
  }

  async create(input: {
    spaceId: string;
    userId: string;
    name: string;
    description?: string | null;
    visibility?: string | null;
    roleInstruction?: string | null;
    systemPrompt?: string | null;
    defaultModelProviderId?: string | null;
    defaultModel?: string | null;
    adapterType?: string | null;
    modelConfigJson?: Record<string, unknown> | null;
    runtimeConfigJson?: Record<string, unknown> | null;
    contextPolicyJson?: Record<string, unknown> | null;
    memoryPolicyJson?: Record<string, unknown> | null;
    capabilitiesJson?: unknown[] | null;
    toolPermissionsJson?: Record<string, unknown> | null;
    runtimePolicyJson?: Record<string, unknown> | null;
  }): Promise<AgentOut> {
    const adapterType = normalizeAdapterType(input.adapterType);
    const providerId = input.defaultModelProviderId ?? null;
    const modelName = input.defaultModel ?? null;
    await this.validateModelSelection(input.spaceId, adapterType, providerId, modelName);
    return withTransaction(this.pool, async (client) =>
      this.createAgentWithVersion(client, {
        spaceId: input.spaceId,
        ownerUserId: input.userId,
        name: input.name,
        description: input.description ?? null,
        visibility: input.visibility ?? "private",
        roleInstruction: input.roleInstruction ?? null,
        status: "active",
        agentKind: "standard",
        systemPrompt: input.systemPrompt ?? null,
        modelProviderId: providerId,
        modelName,
        modelConfigJson: input.modelConfigJson ?? {
          ...DEFAULT_MODEL_CONFIG,
          ...(modelName ? { model: modelName } : {}),
        },
        runtimeConfigJson: input.runtimeConfigJson ?? DEFAULT_RUNTIME_CONFIG,
        contextPolicyJson: input.contextPolicyJson ?? {},
        memoryPolicyJson: input.memoryPolicyJson ?? DEFAULT_MEMORY_POLICY,
        capabilitiesJson: input.capabilitiesJson ?? [],
        toolPermissionsJson: input.toolPermissionsJson ?? {},
        runtimePolicyJson: buildRuntimePolicy(adapterType, input.runtimePolicyJson),
      }),
    );
  }

  async update(
    spaceId: string,
    agentId: string,
    patch: {
      name?: string;
      description?: string | null;
      visibility?: string;
      roleInstruction?: string | null;
      status?: string;
    },
  ): Promise<AgentOut> {
    const existing = await this.get(spaceId, agentId);
    if (!existing) throw new HttpError(404, "Agent not found");
    const now = new Date().toISOString();
    const result = await this.pool.query<AgentRecord>(
      `UPDATE agents
          SET name = COALESCE($3, name),
              description = CASE WHEN $4::boolean THEN $5 ELSE description END,
              visibility = COALESCE($6, visibility),
              role_instruction = CASE WHEN $7::boolean THEN $8 ELSE role_instruction END,
              status = COALESCE($9, status),
              updated_at = $10
        WHERE space_id = $1 AND id = $2
        RETURNING id`,
      [
        spaceId,
        agentId,
        patch.name ?? null,
        Object.hasOwn(patch, "description"),
        patch.description ?? null,
        patch.visibility ?? null,
        Object.hasOwn(patch, "roleInstruction"),
        patch.roleInstruction ?? null,
        patch.status ?? null,
        now,
      ],
    );
    if (!result.rows[0]) throw new HttpError(404, "Agent not found");
    const updated = await this.get(spaceId, agentId);
    if (!updated) throw new HttpError(404, "Agent not found");
    return updated;
  }

  async updateConfig(
    spaceId: string,
    agentId: string,
    patch: {
      userId: string;
      name?: string | null;
      description?: string | null;
      systemPrompt?: string | null;
      modelProviderId?: string | null;
      modelName?: string | null;
      modelConfigJson?: Record<string, unknown> | null;
      contextPolicyJson?: Record<string, unknown> | null;
      memoryPolicyJson?: Record<string, unknown> | null;
      outputPolicyJson?: Record<string, unknown> | null;
      scheduleConfigJson?: Record<string, unknown> | null;
      outputSchemaJson?: Record<string, unknown> | null;
    },
  ): Promise<AgentOut> {
    const current = await this.getCurrentVersion(spaceId, agentId);
    if (!current) throw new HttpError(404, "Agent has no current version");
    const modelProviderId = Object.hasOwn(patch, "modelProviderId")
      ? patch.modelProviderId ?? null
      : current.model_provider_id;
    const modelName = Object.hasOwn(patch, "modelName")
      ? patch.modelName ?? null
      : current.model_name;
    if (modelProviderId || modelName) {
      const adapterType = normalizeAdapterType(
        stringValue(current.runtime_policy_json?.default_adapter_type),
      );
      await this.validateModelSelection(spaceId, adapterType, modelProviderId, modelName);
    }
    return withTransaction(this.pool, async (client) => {
      const now = new Date().toISOString();
      if (Object.hasOwn(patch, "name") || Object.hasOwn(patch, "description")) {
        await client.query(
          `UPDATE agents
              SET name = COALESCE($3, name),
                  description = CASE WHEN $4::boolean THEN $5 ELSE description END,
                  updated_at = $6
            WHERE space_id = $1 AND id = $2`,
          [
            spaceId,
            agentId,
            patch.name ?? null,
            Object.hasOwn(patch, "description"),
            patch.description ?? null,
            now,
          ],
        );
      }
      const versionPatch: Partial<AgentVersionRecord> = {
        system_prompt: Object.hasOwn(patch, "systemPrompt") ? patch.systemPrompt ?? null : current.system_prompt,
        model_provider_id: modelProviderId,
        model_name: modelName,
        model_config_json: patch.modelConfigJson
          ? { ...current.model_config_json, ...patch.modelConfigJson }
          : current.model_config_json,
        context_policy_json: patch.contextPolicyJson ?? current.context_policy_json,
        memory_policy_json: patch.memoryPolicyJson ?? current.memory_policy_json,
        output_policy_json: patch.outputPolicyJson ?? current.output_policy_json,
        schedule_config_json: patch.scheduleConfigJson ?? current.schedule_config_json,
        output_schema_json: patch.outputSchemaJson ?? current.output_schema_json,
      };
      const newVersion = await this.insertVersion(client, {
        agentId,
        spaceId,
        versionLabel: await this.nextVersionLabel(client, spaceId, agentId),
        modelProviderId: versionPatch.model_provider_id ?? null,
        modelName: versionPatch.model_name ?? null,
        systemPrompt: versionPatch.system_prompt ?? null,
        modelConfigJson: versionPatch.model_config_json ?? DEFAULT_MODEL_CONFIG,
        runtimeConfigJson: current.runtime_config_json,
        contextPolicyJson: versionPatch.context_policy_json ?? {},
        memoryPolicyJson: versionPatch.memory_policy_json ?? DEFAULT_MEMORY_POLICY,
        capabilitiesJson: current.capabilities_json,
        toolPermissionsJson: current.tool_permissions_json,
        runtimePolicyJson: current.runtime_policy_json,
        toolPolicyJson: current.tool_policy_json,
        outputPolicyJson: versionPatch.output_policy_json ?? {},
        scheduleConfigJson: versionPatch.schedule_config_json ?? {},
        outputSchemaJson: versionPatch.output_schema_json ?? {},
      });
      await client.query(
        `UPDATE agents SET current_version_id = $3, updated_at = $4 WHERE space_id = $1 AND id = $2`,
        [spaceId, agentId, newVersion.id, now],
      );
      const updated = await this.getAgentWithClient(client, spaceId, agentId);
      if (!updated) throw new HttpError(404, "Agent not found");
      return updated;
    });
  }

  async getCurrentVersion(spaceId: string, agentId: string): Promise<AgentVersionRecord | null> {
    const result = await this.pool.query<AgentVersionRecord>(
      `SELECT ${versionColumns("av")}
         FROM agents a
         JOIN agent_versions av ON av.id = a.current_version_id
        WHERE a.space_id = $1 AND a.id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }

  async listVersions(spaceId: string, agentId: string): Promise<AgentVersionRecord[]> {
    await this.requireAgent(spaceId, agentId);
    const result = await this.pool.query<AgentVersionRecord>(
      `SELECT ${VERSION_COLUMNS}
         FROM agent_versions
        WHERE space_id = $1 AND agent_id = $2
        ORDER BY created_at DESC, id DESC`,
      [spaceId, agentId],
    );
    return result.rows;
  }

  async getVersion(
    spaceId: string,
    agentId: string,
    versionId: string,
  ): Promise<AgentVersionRecord> {
    const result = await this.pool.query<AgentVersionRecord>(
      `SELECT ${VERSION_COLUMNS}
         FROM agent_versions
        WHERE space_id = $1 AND agent_id = $2 AND id = $3
        LIMIT 1`,
      [spaceId, agentId, versionId],
    );
    const row = result.rows[0];
    if (!row) throw new HttpError(404, "AgentVersion not found for this agent in this space");
    return row;
  }

  async restoreVersion(
    spaceId: string,
    agentId: string,
    versionId: string,
  ): Promise<AgentOut> {
    const source = await this.getVersion(spaceId, agentId, versionId);
    return withTransaction(this.pool, async (client) => {
      const version = await this.insertVersion(client, {
        agentId,
        spaceId,
        versionLabel: await this.nextVersionLabel(client, spaceId, agentId),
        modelProviderId: source.model_provider_id,
        modelName: source.model_name,
        systemPrompt: source.system_prompt,
        modelConfigJson: source.model_config_json,
        runtimeConfigJson: source.runtime_config_json,
        contextPolicyJson: source.context_policy_json,
        memoryPolicyJson: source.memory_policy_json,
        capabilitiesJson: source.capabilities_json,
        toolPermissionsJson: source.tool_permissions_json,
        runtimePolicyJson: source.runtime_policy_json,
        toolPolicyJson: source.tool_policy_json,
        outputPolicyJson: source.output_policy_json,
        scheduleConfigJson: source.schedule_config_json,
        outputSchemaJson: source.output_schema_json,
      });
      await client.query(
        `UPDATE agents SET current_version_id = $3, updated_at = $4 WHERE space_id = $1 AND id = $2`,
        [spaceId, agentId, version.id, new Date().toISOString()],
      );
      const updated = await this.getAgentWithClient(client, spaceId, agentId);
      if (!updated) throw new HttpError(404, "Agent not found");
      return updated;
    });
  }

  async getDefaultAssistant(spaceId: string): Promise<AgentOut | null> {
    const result = await this.pool.query<AgentRecord>(
      `SELECT ${AGENT_COLUMNS}
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id
         LEFT JOIN model_providers mp ON mp.id = av.model_provider_id
        WHERE a.space_id = $1
          AND a.agent_kind = 'system_assistant'
          AND a.status = 'active'
        ORDER BY a.created_at ASC
        LIMIT 1`,
      [spaceId],
    );
    return result.rows[0] ? agentOut(result.rows[0]) : null;
  }

  async ensureDefaultAssistant(spaceId: string): Promise<AgentOut> {
    const existing = await this.getDefaultAssistant(spaceId);
    if (existing) return existing;
    return withTransaction(this.pool, async (client) => {
      const current = await client.query<AgentRecord>(
        `SELECT ${AGENT_COLUMNS}
           FROM agents a
           LEFT JOIN agent_versions av ON av.id = a.current_version_id
           LEFT JOIN model_providers mp ON mp.id = av.model_provider_id
          WHERE a.space_id = $1
            AND a.agent_kind = 'system_assistant'
            AND a.status = 'active'
          ORDER BY a.created_at ASC
          LIMIT 1`,
        [spaceId],
      );
      if (current.rows[0]) return agentOut(current.rows[0]);
      return this.createAgentWithVersion(client, {
        spaceId,
        ownerUserId: null,
        name: "Personal Assistant",
        description: "System-managed contextual chat assistant for this space.",
        visibility: "space_shared",
        roleInstruction: null,
        status: "active",
        agentKind: "system_assistant",
        systemPrompt: "You are the space's contextual personal assistant.",
        modelProviderId: null,
        modelName: null,
        modelConfigJson: DEFAULT_MODEL_CONFIG,
        runtimeConfigJson: DEFAULT_RUNTIME_CONFIG,
        contextPolicyJson: {},
        memoryPolicyJson: DEFAULT_MEMORY_POLICY,
        capabilitiesJson: [],
        toolPermissionsJson: {},
        runtimePolicyJson: buildRuntimePolicy("model_api", null),
      });
    });
  }

  async getAssistantSettings(spaceId: string): Promise<AssistantSettingsRecord> {
    const existing = await this.pool.query<AssistantSettingsRecord>(
      `SELECT ${SETTINGS_COLUMNS}
         FROM space_assistant_settings
        WHERE space_id = $1
        LIMIT 1`,
      [spaceId],
    );
    if (existing.rows[0]) return existing.rows[0];
    const assistant = await this.getDefaultAssistant(spaceId);
    const now = new Date().toISOString();
    const inserted = await this.pool.query<AssistantSettingsRecord>(
      `INSERT INTO space_assistant_settings (
         id, space_id, assistant_agent_id, default_context_toggles_json,
         model_preferences_json, created_at, updated_at
       ) VALUES ($1, $2, $3, '{}'::jsonb, '{}'::jsonb, $4, $4)
       ON CONFLICT (space_id) DO UPDATE
          SET assistant_agent_id = COALESCE(space_assistant_settings.assistant_agent_id, EXCLUDED.assistant_agent_id),
              updated_at = EXCLUDED.updated_at
       RETURNING ${SETTINGS_COLUMNS}`,
      [randomUUID(), spaceId, assistant?.id ?? null, now],
    );
    return inserted.rows[0]!;
  }

  async updateAssistantSettings(
    spaceId: string,
    patch: Record<string, unknown>,
  ): Promise<AssistantSettingsRecord> {
    const existing = await this.getAssistantSettings(spaceId);
    const assistant = existing.assistant_agent_id ? null : await this.getDefaultAssistant(spaceId);
    const result = await this.pool.query<AssistantSettingsRecord>(
      `UPDATE space_assistant_settings
          SET assistant_agent_id = COALESCE(assistant_agent_id, $2),
              response_style = CASE WHEN $3::boolean THEN $4 ELSE response_style END,
              verbosity = CASE WHEN $5::boolean THEN $6 ELSE verbosity END,
              default_context_toggles_json = CASE WHEN $7::boolean THEN $8::jsonb ELSE default_context_toggles_json END,
              default_project_id = CASE WHEN $9::boolean THEN $10 ELSE default_project_id END,
              proposal_style = CASE WHEN $11::boolean THEN $12 ELSE proposal_style END,
              model_preferences_json = CASE WHEN $13::boolean THEN $14::jsonb ELSE model_preferences_json END,
              updated_at = $15
        WHERE space_id = $1
        RETURNING ${SETTINGS_COLUMNS}`,
      [
        spaceId,
        assistant?.id ?? null,
        Object.hasOwn(patch, "response_style"),
        stringOrNull(patch.response_style),
        Object.hasOwn(patch, "verbosity"),
        stringOrNull(patch.verbosity),
        Object.hasOwn(patch, "default_context_toggles_json"),
        JSON.stringify(recordValue(patch.default_context_toggles_json) ?? {}),
        Object.hasOwn(patch, "default_project_id"),
        stringOrNull(patch.default_project_id),
        Object.hasOwn(patch, "proposal_style"),
        stringOrNull(patch.proposal_style),
        Object.hasOwn(patch, "model_preferences_json"),
        JSON.stringify(recordValue(patch.model_preferences_json) ?? {}),
        new Date().toISOString(),
      ],
    );
    return result.rows[0]!;
  }

  private async validateModelSelection(
    spaceId: string,
    adapterType: string,
    providerId: string | null,
    modelName: string | null,
  ): Promise<void> {
    const spec = BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType];
    if (!spec) throw new HttpError(400, `Unknown adapter_type ${JSON.stringify(adapterType)}`);
    if (modelName && !providerId) {
      throw new HttpError(400, "default_model_provider_id is required when default_model is set");
    }
    if (spec.model.model_provider_mode === "required" && !providerId) {
      throw new HttpError(
        400,
        `adapter_type ${JSON.stringify(adapterType)} requires a model provider; set default_model_provider_id.`,
      );
    }
    if (providerId) {
      const provider = await this.pool.query<{ id: string }>(
        `SELECT id FROM model_providers WHERE space_id = $1 AND id = $2 AND enabled = true`,
        [spaceId, providerId],
      );
      if (!provider.rows[0]) {
        throw new HttpError(400, "Model provider is not selectable in this space");
      }
    }
  }

  private async requireAgent(spaceId: string, agentId: string): Promise<void> {
    const found = await this.pool.query<{ id: string }>(
      `SELECT id FROM agents WHERE space_id = $1 AND id = $2 LIMIT 1`,
      [spaceId, agentId],
    );
    if (!found.rows[0]) throw new HttpError(404, "Agent not found");
  }

  private async createAgentWithVersion(
    client: PoolClient,
    input: {
      spaceId: string;
      ownerUserId: string | null;
      name: string;
      description: string | null;
      visibility: string;
      roleInstruction: string | null;
      status: string;
      agentKind: string;
      systemPrompt: string | null;
      modelProviderId: string | null;
      modelName: string | null;
      modelConfigJson: Record<string, unknown>;
      runtimeConfigJson: Record<string, unknown>;
      contextPolicyJson: Record<string, unknown>;
      memoryPolicyJson: Record<string, unknown>;
      capabilitiesJson: unknown[];
      toolPermissionsJson: Record<string, unknown>;
      runtimePolicyJson: Record<string, unknown>;
    },
  ): Promise<AgentOut> {
    const agentId = randomUUID();
    const now = new Date().toISOString();
    await client.query(
      `INSERT INTO agents (
         id, space_id, owner_user_id, name, description, role_instruction,
         status, agent_kind, visibility, created_at, updated_at
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)`,
      [
        agentId,
        input.spaceId,
        input.ownerUserId,
        input.name,
        input.description,
        input.roleInstruction,
        input.status,
        input.agentKind,
        input.visibility,
        now,
      ],
    );
    const version = await this.insertVersion(client, {
      agentId,
      spaceId: input.spaceId,
      versionLabel: "v1",
      modelProviderId: input.modelProviderId,
      modelName: input.modelName,
      systemPrompt: input.systemPrompt,
      modelConfigJson: input.modelConfigJson,
      runtimeConfigJson: input.runtimeConfigJson,
      contextPolicyJson: input.contextPolicyJson,
      memoryPolicyJson: input.memoryPolicyJson,
      capabilitiesJson: input.capabilitiesJson,
      toolPermissionsJson: input.toolPermissionsJson,
      runtimePolicyJson: input.runtimePolicyJson,
      toolPolicyJson: {},
      outputPolicyJson: {},
      scheduleConfigJson: {},
      outputSchemaJson: {},
    });
    await client.query(
      `UPDATE agents SET current_version_id = $3, updated_at = $4 WHERE space_id = $1 AND id = $2`,
      [input.spaceId, agentId, version.id, now],
    );
    const created = await this.getAgentWithClient(client, input.spaceId, agentId);
    if (!created) throw new Error("Agent insert returned no row");
    return created;
  }

  private async insertVersion(
    db: Queryable,
    input: {
      agentId: string;
      spaceId: string;
      versionLabel: string;
      modelProviderId: string | null;
      modelName: string | null;
      systemPrompt: string | null;
      modelConfigJson: Record<string, unknown>;
      runtimeConfigJson: Record<string, unknown>;
      contextPolicyJson: Record<string, unknown>;
      memoryPolicyJson: Record<string, unknown>;
      capabilitiesJson: unknown[];
      toolPermissionsJson: Record<string, unknown>;
      runtimePolicyJson: Record<string, unknown>;
      toolPolicyJson: Record<string, unknown>;
      outputPolicyJson: Record<string, unknown>;
      scheduleConfigJson: Record<string, unknown>;
      outputSchemaJson: Record<string, unknown>;
    },
  ): Promise<{ id: string }> {
    const id = randomUUID();
    const now = new Date().toISOString();
    const result = await db.query<{ id: string }>(
      `INSERT INTO agent_versions (
         id, agent_id, space_id, version_label, model_provider_id, model_name,
         system_prompt, model_config_json, runtime_config_json,
         context_policy_json, memory_policy_json, capabilities_json,
         tool_permissions_json, runtime_policy_json, tool_policy_json,
         output_policy_json, schedule_config_json, output_schema_json, created_at
       ) VALUES (
         $1, $2, $3, $4, $5, $6,
         $7, $8::jsonb, $9::jsonb,
         $10::jsonb, $11::jsonb, $12::jsonb,
         $13::jsonb, $14::jsonb, $15::jsonb,
         $16::jsonb, $17::jsonb, $18::jsonb, $19
       )
       RETURNING id`,
      [
        id,
        input.agentId,
        input.spaceId,
        input.versionLabel,
        input.modelProviderId,
        input.modelName,
        input.systemPrompt,
        JSON.stringify(input.modelConfigJson),
        JSON.stringify(input.runtimeConfigJson),
        JSON.stringify(input.contextPolicyJson),
        JSON.stringify(input.memoryPolicyJson),
        JSON.stringify(input.capabilitiesJson),
        JSON.stringify(input.toolPermissionsJson),
        JSON.stringify(input.runtimePolicyJson),
        JSON.stringify(input.toolPolicyJson),
        JSON.stringify(input.outputPolicyJson),
        JSON.stringify(input.scheduleConfigJson),
        JSON.stringify(input.outputSchemaJson),
        now,
      ],
    );
    return result.rows[0] ?? { id };
  }

  private async nextVersionLabel(db: Queryable, spaceId: string, agentId: string): Promise<string> {
    const result = await db.query<{ version_label: string }>(
      `SELECT version_label
         FROM agent_versions
        WHERE space_id = $1 AND agent_id = $2
        ORDER BY created_at DESC`,
      [spaceId, agentId],
    );
    let max = 0;
    for (const row of result.rows) {
      if (row.version_label.startsWith("v")) {
        const n = Number(row.version_label.slice(1));
        if (Number.isInteger(n) && n > max) max = n;
      }
    }
    return `v${max + 1}`;
  }

  private async getAgentWithClient(
    client: Queryable,
    spaceId: string,
    agentId: string,
  ): Promise<AgentOut | null> {
    const result = await client.query<AgentRecord>(
      `SELECT ${AGENT_COLUMNS}
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id
         LEFT JOIN model_providers mp ON mp.id = av.model_provider_id
        WHERE a.space_id = $1 AND a.id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ? agentOut(result.rows[0]) : null;
  }
}

function agentOut(row: AgentRecord): AgentOut {
  const adapterType = normalizeAdapterType(runtimePolicy(row).default_adapter_type);
  const spec = BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType];
  const requiresModelProvider = spec?.model.model_provider_mode === "required";
  const hasModel =
    row.model_provider_id !== null ||
    row.provider_name !== null ||
    row.provider_type !== null ||
    row.model_name !== null;
  return {
    id: row.id,
    space_id: row.space_id,
    created_by_user_id: row.owner_user_id,
    name: row.name,
    description: row.description,
    visibility: row.visibility,
    role_instruction: row.role_instruction,
    status: row.status,
    agent_kind: row.agent_kind,
    current_version_id: row.current_version_id,
    source_template_id: row.source_template_id,
    source_template_version_id: row.source_template_version_id,
    model: hasModel
      ? {
          provider_id: row.model_provider_id ?? null,
          provider_name: row.provider_name ?? null,
          provider_type: row.provider_type ?? null,
          model: row.model_name ?? null,
        }
      : null,
    adapter_type: adapterType,
    requires_model_provider: requiresModelProvider,
    system_prompt: row.system_prompt ?? null,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function runtimePolicy(row: AgentRecord): Record<string, unknown> {
  return recordValue(row.runtime_policy_json) ?? DEFAULT_RUNTIME_POLICY;
}

function buildRuntimePolicy(
  adapterType: string,
  base: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const policy = { ...DEFAULT_RUNTIME_POLICY, ...(base ?? {}) };
  const allowed = Array.isArray(policy.allowed_adapter_types)
    ? policy.allowed_adapter_types.filter((item): item is string => typeof item === "string")
    : [...DEFAULT_RUNTIME_POLICY.allowed_adapter_types];
  if (!allowed.includes(adapterType)) allowed.push(adapterType);
  policy.allowed_adapter_types = allowed;
  policy.default_adapter_type = adapterType;
  return policy;
}

function normalizeAdapterType(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "model_api";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
