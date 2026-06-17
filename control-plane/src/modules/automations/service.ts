import type { ControlPlaneConfig } from "../../config";
import { getDbPool, type PoolClient } from "../../db/pool";
import { withTransaction } from "../../db/tx";
import { PgJobQueueRepository } from "../jobs/repository";
import { HttpError } from "../routeUtils/common";
import { enforce } from "../policy";
import { loadActionRegistry } from "../policy/actionRegistry";
import { computeDecision } from "../policy/gateway";
import { PgRunRepository } from "../runs/repository";
import { BUILTIN_RUNTIME_ADAPTER_SPECS, type RuntimeAdapterType } from "../runtimeAdapters";
import { computeNextRunAt, InvalidScheduleError } from "./schedule";
import {
  PgAutomationRepository,
  automationToOut,
  type AutomationRepositoryPort,
  type AutomationRow,
} from "./repository";

const VALID_TRIGGER_TYPES = new Set(["manual", "schedule"]);
const VALID_STATUSES = new Set(["active", "paused", "archived"]);
const CREATE_KEYS = new Set([
  "name",
  "agent_id",
  "workspace_id",
  "description",
  "trigger_type",
  "config_json",
]);
const UPDATE_KEYS = new Set(["name", "description", "status", "config_json"]);
const FORBIDDEN_CONFIG_KEYS = new Set([
  "api_key",
  "token",
  "secret",
  "password",
  "credential",
  "personal_context_block",
  "approved_by_user",
  "approved_by_granting_user",
  "approval_status",
  "is_approved",
  "auto_approved",
  "pre_approved",
]);
const FORBIDDEN_COMPACT_CONFIG_KEYS = new Set([
  "apikey",
  "token",
  "authtoken",
  "accesstoken",
  "refreshtoken",
  "bearertoken",
  "clientsecret",
  "personalcontextblock",
  "approvedbyuser",
  "approvedbygrantinguser",
  "approvalstatus",
  "isapproved",
  "autoapproved",
  "preapproved",
]);
const MAX_CONFIG_JSON_BYTES = 8192;
const MAX_CONFIG_DEPTH = 8;
const MAX_CONFIG_STRING_LENGTH = 2048;
const VALID_RISK_LEVELS = new Set(["low", "medium", "high", "critical"]);

interface AgentPreflightRow {
  status: string;
  current_version_id: string | null;
  version_id: string | null;
  runtime_config_json: unknown;
  runtime_policy_json: unknown;
  model_provider_id: string | null;
}

export class AutomationService {
  constructor(
    private readonly config: ControlPlaneConfig,
    private readonly repo: AutomationRepositoryPort,
  ) {}

  async create(input: {
    spaceId: string;
    ownerUserId: string;
    body: Record<string, unknown>;
  }): Promise<AutomationRow> {
    rejectExtraKeys(input.body, CREATE_KEYS);
    const name = requiredString(input.body.name, "name", 256);
    const agentId = requiredString(input.body.agent_id, "agent_id");
    const workspaceId = optionalString(input.body.workspace_id, "workspace_id");
    const triggerType = optionalString(input.body.trigger_type, "trigger_type") ?? "manual";
    if (!VALID_TRIGGER_TYPES.has(triggerType)) {
      throw new HttpError(422, `Unsupported trigger_type ${JSON.stringify(triggerType)}`);
    }
    const configJson = validateConfigJson(input.body.config_json);
    if (triggerType === "schedule") {
      try {
        computeNextRunAt(configJson);
      } catch (error) {
        if (error instanceof InvalidScheduleError) throw new HttpError(422, error.message);
        throw error;
      }
    }
    await this.enforceAction("automation.create", input.spaceId, input.ownerUserId, {
      agent_id: agentId,
      trigger_type: triggerType,
    });
    const preflightSnapshot = await this.runPreflight(
      input.spaceId,
      agentId,
      workspaceId,
      triggerType === "schedule",
    );
    return this.repo.create({
      spaceId: input.spaceId,
      ownerUserId: input.ownerUserId,
      name,
      description: optionalNullableString(input.body.description, "description"),
      agentId,
      workspaceId,
      triggerType,
      configJson,
      preflightSnapshot,
    });
  }

  async update(input: {
    spaceId: string;
    automationId: string;
    actorUserId: string;
    body: Record<string, unknown>;
  }): Promise<AutomationRow> {
    rejectExtraKeys(input.body, UPDATE_KEYS);
    const existing = await this.repo.get(input.spaceId, input.automationId);
    if (!existing) throw new HttpError(404, `Automation '${input.automationId}' not found`);
    const status = optionalString(input.body.status, "status");
    if (status && !VALID_STATUSES.has(status)) {
      throw new HttpError(422, `Invalid status ${JSON.stringify(status)}`);
    }
    const configJson =
      Object.prototype.hasOwnProperty.call(input.body, "config_json") && input.body.config_json !== null
        ? validateConfigJson(input.body.config_json)
        : undefined;
    if (configJson && existing.trigger_type === "schedule") {
      try {
        computeNextRunAt(configJson);
      } catch (error) {
        if (error instanceof InvalidScheduleError) throw new HttpError(422, error.message);
        throw error;
      }
    }
    await this.enforceAction("automation.update", input.spaceId, input.actorUserId, {
      agent_id: existing.agent_id,
    }, input.automationId);
    return this.repo.update(input.spaceId, input.automationId, {
      name: optionalString(input.body.name, "name", 256) ?? undefined,
      description:
        input.body.description === undefined
          ? undefined
          : optionalNullableString(input.body.description, "description"),
      status: status ?? undefined,
      config_json: configJson,
    });
  }

  async fire(input: {
    spaceId: string;
    automationId: string;
    actorUserId: string;
    prompt?: string | null;
    instruction?: string | null;
    triggerType?: string;
  }): Promise<Record<string, unknown>> {
    const auto = await this.repo.get(input.spaceId, input.automationId);
    if (!auto) throw new HttpError(404, `Automation '${input.automationId}' not found`);
    if (auto.status !== "active") {
      throw new HttpError(409, `Automation is not active (status=${auto.status})`);
    }
    const triggerType = input.triggerType ?? "manual";
    if (!VALID_TRIGGER_TYPES.has(triggerType)) {
      throw new HttpError(422, `Unsupported trigger_type ${JSON.stringify(triggerType)}`);
    }
    const preAuthorized = await this.repo.hasActiveGrant(input.spaceId, auto.id);
    await this.enforceAction("automation.fire", input.spaceId, input.actorUserId, {
      agent_id: auto.agent_id,
      trigger_type: triggerType,
      trigger_origin: "automation",
      automation_pre_authorized: preAuthorized,
    }, auto.id);
    const preflightSnapshot = await this.runPreflight(
      input.spaceId,
      auto.agent_id,
      auto.workspace_id,
      preAuthorized,
    );

    if (!this.config.databaseUrl) {
      throw new HttpError(502, "CONTROL_PLANE_DATABASE_URL is required");
    }
    const result = await withTransaction(getDbPool(this.config.databaseUrl), async (client) => {
      return this.persistFire(client, auto, input, triggerType, preflightSnapshot);
    });
    return {
      run_id: result.runId,
      automation_run_id: result.automationRunId,
      trigger_origin: "automation",
      preflight_executable: Boolean(preflightSnapshot.executable),
    };
  }

  async scanAndFire(): Promise<number> {
    if (!this.config.databaseUrl) return 0;
    const pool = getDbPool(this.config.databaseUrl);
    const due = await this.repo.listDue(new Date().toISOString());
    let fired = 0;
    for (const auto of due) {
      try {
        const fireInput = {
          spaceId: auto.space_id,
          automationId: auto.id,
          actorUserId: auto.owner_user_id,
          triggerType: "schedule",
        };
        const preAuthorized = await this.repo.hasActiveGrant(auto.space_id, auto.id);
        await this.enforceAction("automation.fire", auto.space_id, auto.owner_user_id, {
          agent_id: auto.agent_id,
          trigger_type: "schedule",
          trigger_origin: "automation",
          automation_pre_authorized: preAuthorized,
        }, auto.id);
        const preflightSnapshot = await this.runPreflight(
          auto.space_id,
          auto.agent_id,
          auto.workspace_id,
          preAuthorized,
        );
        await withTransaction(pool, async (client) => {
          const automations = new PgAutomationRepository(client);
          await this.persistFire(client, auto, fireInput, "schedule", preflightSnapshot);
          await automations.advanceSchedule(auto);
        });
        fired += 1;
      } catch {
        await this.repo.advanceSchedule(auto);
      }
    }
    return fired;
  }

  private async persistFire(
    client: PoolClient,
    auto: AutomationRow,
    input: {
      spaceId: string;
      actorUserId: string;
      prompt?: string | null;
      instruction?: string | null;
    },
    triggerType: string,
    preflightSnapshot: Record<string, unknown>,
  ): Promise<{ runId: string; automationRunId: string }> {
    const runs = new PgRunRepository(client);
    const queue = new PgJobQueueRepository(client);
    const automations = new PgAutomationRepository(client);
    const run = await runs.createQueuedRun({
      space_id: input.spaceId,
      user_id: input.actorUserId,
      agent_id: auto.agent_id,
      workspace_id: auto.workspace_id,
      prompt: input.prompt ?? null,
      instruction: input.instruction ?? null,
      trigger_origin: "automation",
      run_type: "agent",
      mode: "live",
    });
    await queue.enqueue({
      job_type: "agent_run",
      payload: { run_id: run.id },
      space_id: input.spaceId,
      user_id: input.actorUserId,
      agent_id: auto.agent_id,
      workspace_id: auto.workspace_id,
    });
    const automationRunId = await automations.createAutomationRun({
      automationId: auto.id,
      runId: run.id,
      triggeredByUserId: input.actorUserId,
      triggerType,
      preflightSnapshot,
    });
    return { runId: run.id, automationRunId };
  }

  private async enforceAction(
    action: string,
    spaceId: string,
    actorUserId: string,
    context: Record<string, unknown>,
    resourceId?: string,
  ): Promise<void> {
    const membershipRole = await this.repo.getMembershipRole(spaceId, actorUserId);
    const registry = await loadActionRegistry();
    const result = await enforce(this.config, registry, {
      action,
      actor_type: "user",
      actor_id: actorUserId,
      space_id: spaceId,
      resource_type: "automation",
      resource_id: resourceId ?? null,
      context: { ...context, membership_role: membershipRole ?? "guest" },
      force_record: false,
    });
    if (result.status === "blocked") {
      throw new HttpError(403, result.message ?? "Policy denied");
    }
    if (result.status === "error") {
      throw new HttpError(500, result.message ?? "Policy audit failed");
    }
  }

  private async runPreflight(
    spaceId: string,
    agentId: string,
    workspaceId: string | null | undefined,
    automationPreAuthorized: boolean,
  ): Promise<Record<string, unknown>> {
    if (!this.config.databaseUrl) return { executable: true, skipped: "database_not_configured" };
    const db = getDbPool(this.config.databaseUrl);
    const agent = await db.query<AgentPreflightRow>(
      `SELECT a.status,
              a.current_version_id,
              av.id AS version_id,
              av.runtime_config_json,
              av.runtime_policy_json,
              av.model_provider_id
         FROM agents a
         LEFT JOIN agent_versions av ON av.id = a.current_version_id AND av.space_id = a.space_id
        WHERE a.space_id = $1 AND a.id = $2`,
      [spaceId, agentId],
    );
    const row = agent.rows[0];
    const runtimeErrors: string[] = [];
    const runtimeWarnings: string[] = [];
    let adapterType: string | null = null;
    let riskLevel: string | null = null;
    let requiredSandboxLevel: string | null = null;
    let modelProviderId: string | null = null;

    if (!row) {
      runtimeErrors.push("Agent not found");
    } else {
      if (row.status !== "active") runtimeErrors.push(`Agent is not active (status=${row.status})`);
      if (!row.current_version_id) runtimeErrors.push("Agent has no current version");
      if (row.current_version_id && !row.version_id) runtimeErrors.push("Current AgentVersion not found");

      const runtimeConfig = recordValue(row.runtime_config_json);
      const runtimePolicy = recordValue(row.runtime_policy_json);
      adapterType =
        stringValue(runtimeConfig.adapter_type) ??
        stringValue(runtimePolicy.default_adapter_type) ??
        "model_api";
      riskLevel = normalizeRiskLevel(runtimePolicy.risk_level);
      const spec = runtimeAdapterSpec(adapterType);
      requiredSandboxLevel = requiredSandboxFor(riskLevel, spec);
      if (!spec) {
        runtimeErrors.push(`Unknown runtime adapter '${adapterType}'`);
      } else if (spec.implementation_status !== "implemented") {
        runtimeErrors.push(`Runtime adapter '${adapterType}' is not implemented`);
      }
      if (requiredSandboxLevel === "one_shot_docker") {
        runtimeErrors.push("risk_level=critical requires one_shot_docker sandbox which is not implemented");
      }
      if (spec?.sandbox.requires_workspace_for_execution && !workspaceId) {
        runtimeErrors.push(`Runtime adapter '${adapterType}' requires workspace_id`);
      }
      if (spec?.sandbox.requires_file_access && requiredSandboxLevel === "worktree" && !workspaceId) {
        runtimeErrors.push("workspace_id is required for worktree-level runs");
      }
      if (workspaceId) {
        const workspace = await db.query<{ id: string }>(
          `SELECT id FROM workspaces WHERE space_id = $1 AND id = $2`,
          [spaceId, workspaceId],
        );
        if (!workspace.rows[0]) runtimeErrors.push("Workspace not found");
      }
      modelProviderId = row.model_provider_id ?? null;
      if (!modelProviderId && spec?.model.model_provider_mode === "required") {
        modelProviderId = await resolveDefaultProvider(db, spaceId, adapterType);
        if (!modelProviderId) {
          runtimeErrors.push(`Runtime adapter '${adapterType}' requires a model provider`);
        }
      }
    }

    const registry = await loadActionRegistry();
    const policyChecks: Record<string, unknown>[] = [];
    const runtimeExecute = computeDecision(registry, {
      action: "runtime.execute",
      actor_type: "run",
      actor_id: null,
      space_id: spaceId,
      resource_space_id: spaceId,
      resource_type: "agent",
      resource_id: agentId,
      context: {
        trigger_origin: "automation",
        agent_status: row?.status,
        risk_level: riskLevel ?? "medium",
        adapter_type: adapterType,
      },
      force_record: false,
    }).decision;
    policyChecks.push(policyCheck("runtime.execute", runtimeExecute));

    if (modelProviderId) {
      const credential = computeDecision(registry, {
        action: "runtime.use_credential",
        actor_type: "run",
        actor_id: null,
        space_id: spaceId,
        resource_space_id: spaceId,
        resource_type: "model_provider",
        resource_id: modelProviderId,
        context: {
          trigger_origin: "automation",
          automation_pre_authorized: automationPreAuthorized,
        },
        force_record: false,
      }).decision;
      policyChecks.push(policyCheck("runtime.use_credential", credential));
    }

    for (const action of ["context.inject_memory", "context.render_for_runtime"]) {
      const decision = computeDecision(registry, {
        action,
        actor_type: "run",
        actor_id: null,
        space_id: spaceId,
        resource_space_id: spaceId,
        resource_type: action === "context.inject_memory" ? "memory" : "context",
        context: {
          trigger_origin: "automation",
          has_personal_grant_context: false,
        },
        metadata_json: {
          workspace_id: workspaceId ?? null,
          adapter_type: adapterType,
        },
        force_record: false,
      }).decision;
      policyChecks.push(policyCheck(action, decision));
    }

    const policyErrors = policyChecks
      .filter((check) => check.allowed !== true)
      .map((check) => `${check.action}: ${check.decision} (${check.reason_code ?? "policy_denied"}) ${check.message ?? ""}`.trim());
    const snapshot = {
      executable: runtimeErrors.length === 0 && policyErrors.length === 0,
      runtime_preflight: {
        executable: runtimeErrors.length === 0,
        adapter_type: adapterType,
        required_sandbox_level: requiredSandboxLevel,
        errors: runtimeErrors,
        warnings: runtimeWarnings,
      },
      policy_preflight: {
        executable: policyErrors.length === 0,
        checks: policyChecks,
        errors: policyErrors,
        warnings: [],
      },
    };
    if (!snapshot.executable) {
      throw new HttpError(422, `Preflight failed: ${[...runtimeErrors, ...policyErrors].join("; ")}`);
    }
    return snapshot;
  }
}

function rejectExtraKeys(body: Record<string, unknown>, allowed: Set<string>): void {
  for (const key of Object.keys(body)) {
    if (!allowed.has(key)) throw new HttpError(422, `Unsupported field ${JSON.stringify(key)}`);
  }
}

function requiredString(value: unknown, field: string, maxLength?: number): string {
  if (typeof value !== "string" || value.length < 1) {
    throw new HttpError(422, `${field} must be a non-empty string`);
  }
  if (maxLength !== undefined && value.length > maxLength) {
    throw new HttpError(422, `${field} exceeds maximum length of ${maxLength}`);
  }
  return value;
}

function optionalString(value: unknown, field: string, maxLength?: number): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") throw new HttpError(422, `${field} must be a string`);
  if (value.length < 1) throw new HttpError(422, `${field} must not be empty`);
  if (maxLength !== undefined && value.length > maxLength) {
    throw new HttpError(422, `${field} exceeds maximum length of ${maxLength}`);
  }
  return value;
}

function optionalNullableString(value: unknown, field: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") throw new HttpError(422, `${field} must be a string`);
  return value;
}

function validateConfigJson(value: unknown): Record<string, unknown> {
  if (value === undefined || value === null) return {};
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(422, "config_json must be an object");
  }
  let encoded: string;
  try {
    encoded = JSON.stringify(value);
  } catch {
    throw new HttpError(422, "config_json must be JSON serializable");
  }
  if (Buffer.byteLength(encoded, "utf8") > MAX_CONFIG_JSON_BYTES) {
    throw new HttpError(422, `config_json exceeds maximum serialized size of ${MAX_CONFIG_JSON_BYTES} bytes`);
  }
  walkConfigJson(value, 1);
  return value as Record<string, unknown>;
}

function walkConfigJson(value: unknown, depth: number): void {
  if (depth > MAX_CONFIG_DEPTH) {
    throw new HttpError(422, `config_json exceeds maximum depth of ${MAX_CONFIG_DEPTH}`);
  }
  if (Array.isArray(value)) {
    for (const item of value) walkConfigJson(item, depth + 1);
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (isForbiddenConfigKey(key)) {
        throw new HttpError(422, `config_json contains forbidden key ${JSON.stringify(key)}`);
      }
      walkConfigJson(child, depth + 1);
    }
    return;
  }
  if (typeof value === "string" && value.length > MAX_CONFIG_STRING_LENGTH) {
    throw new HttpError(422, `config_json string exceeds maximum length of ${MAX_CONFIG_STRING_LENGTH}`);
  }
}

function isForbiddenConfigKey(key: string): boolean {
  const lower = key.toLowerCase();
  const compact = lower.replace(/[^a-z0-9]/g, "");
  if (FORBIDDEN_CONFIG_KEYS.has(lower) || FORBIDDEN_COMPACT_CONFIG_KEYS.has(compact)) {
    return true;
  }
  if (compact.endsWith("token") && compact !== "maxtoken") return true;
  return (
    compact.includes("secret") ||
    compact.includes("password") ||
    compact.includes("credential")
  );
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function normalizeRiskLevel(value: unknown): string {
  return typeof value === "string" && VALID_RISK_LEVELS.has(value) ? value : "medium";
}

function runtimeAdapterSpec(adapterType: string | null) {
  if (!adapterType) return null;
  return BUILTIN_RUNTIME_ADAPTER_SPECS[adapterType as RuntimeAdapterType] ?? null;
}

function requiredSandboxFor(
  riskLevel: string,
  spec: ReturnType<typeof runtimeAdapterSpec>,
): string {
  if (riskLevel === "critical") return "one_shot_docker";
  if (spec?.sandbox.requires_file_access) return "worktree";
  if (riskLevel === "high") return "worktree";
  return "none";
}

async function resolveDefaultProvider(
  db: { query<Row = Record<string, unknown>>(sql: string, params?: readonly unknown[]): Promise<{ rows: Row[] }> },
  spaceId: string,
  adapterType: string,
): Promise<string | null> {
  const result = await db.query<{ id: string; config_json: unknown }>(
    `SELECT id, config_json
       FROM model_providers
      WHERE space_id = $1 AND enabled = TRUE`,
    [spaceId],
  );
  let spaceDefault: string | null = null;
  for (const row of result.rows) {
    const cfg = recordValue(row.config_json);
    if (cfg.runtime_default_for === adapterType) return row.id;
    if (cfg.runtime_default_adapter_type === adapterType) return row.id;
    if (Array.isArray(cfg.runtime_default_adapter_types) && cfg.runtime_default_adapter_types.includes(adapterType)) {
      return row.id;
    }
    const defaults = recordValue(cfg.runtime_defaults);
    if (defaults[adapterType] === true) return row.id;
    if (spaceDefault === null && cfg.is_default === true) spaceDefault = row.id;
  }
  return spaceDefault;
}

function policyCheck(action: string, decision: {
  decision: string;
  message?: string | null;
  reason_code?: string | null;
  policy_rule_id?: string | null;
  audit_code?: string | null;
}): Record<string, unknown> {
  return {
    action,
    decision: decision.decision,
    allowed: decision.decision === "allow",
    reason_code: decision.reason_code ?? null,
    policy_rule_id: decision.policy_rule_id ?? null,
    audit_code: decision.audit_code ?? null,
    message: decision.message ?? null,
  };
}

export { automationToOut };
