/**
 * Provider command persistence, credential pools, and credential resolution.
 *
 * This store is used when the control plane owns provider commands and the
 * provider credential channel. Alembic remains the database schema owner.
 *
 * Credential pools (Hermes H1): a provider holds 1→N encrypted Credentials
 * through `model_provider_credentials` rows. The primary credential
 * (`model_providers.credential_id`) is lazily enrolled as the position-0 pool
 * member, so pre-pool rows keep working without a data migration and all
 * rotation/health state lives in one place. Failure state is self-healing:
 * a failed key gets `cooldown_until` (never a permanent dead flag), and
 * selection simply skips cooling keys. `healthy=false` marks auth-class
 * failures for operators but does not outlive its cooldown.
 *
 * Rotation strategy and the provider fallback chain are provider-level
 * configuration in `config_json` (same pattern as `is_default`), so no
 * provider-table schema change is needed.
 */

import { randomUUID } from "node:crypto";
import { getDbPool, type Pool } from "./db";
import type { ControlPlaneConfig } from "../../config";
import {
  decryptModelProviderApiKeySecretRefV1,
  encryptModelProviderApiKeySecretRefV1,
  loadOrCreateModelProviderApiKeyMasterKey,
} from "./secretRefCrypto";
import { mapProviderRowToDto } from "./dbReader";
import type { ProviderFailureClass } from "./providerResilience";

const PROVIDER_TYPES = new Set([
  "openai",
  "anthropic",
  "openrouter",
  "ollama",
  "custom_openai_compatible",
  "other",
]);
const CLOUD_PROVIDER_TYPES = new Set(["openai", "anthropic", "openrouter"]);
const BASE_URL_REQUIRED_TYPES = new Set(["ollama", "custom_openai_compatible"]);
const ROTATION_STRATEGIES = new Set(["fill_first", "round_robin", "least_used", "random"]);

export type RotationStrategy = "fill_first" | "round_robin" | "least_used" | "random";

export class ProviderCommandValidationError extends Error {
  readonly statusCode = 400;

  constructor(message: string) {
    super(message);
    this.name = "ProviderCommandValidationError";
  }
}

export class ProviderCommandNotFoundError extends Error {
  readonly statusCode = 404;

  constructor(message: string) {
    super(message);
    this.name = "ProviderCommandNotFoundError";
  }
}

export interface ModelProviderCreateInput {
  name: string;
  provider_type: string;
  base_url?: string | null;
  api_key?: string | null;
  default_model?: string | null;
  available_models?: string[];
  enabled?: boolean;
  is_default?: boolean;
}

export interface ModelProviderUpdateInput {
  name?: string;
  provider_type?: string;
  base_url?: string | null;
  api_key?: string | null;
  default_model?: string | null;
  available_models?: string[];
  enabled?: boolean;
  is_default?: boolean;
}

export interface ProviderInfo {
  id: string;
  space_id: string;
  name: string;
  provider_type: string;
  base_url: string | null;
  default_model: string | null;
  available_models: string[];
  enabled: boolean;
  is_default: boolean;
}

/** One decrypted pool key, ready for a single invocation attempt. */
export interface PoolKeyCandidate {
  member_id: string | null;
  credential_id: string | null;
  api_key: string | null;
}

export interface InvocationTarget {
  provider: ProviderInfo;
  rotation_strategy: RotationStrategy;
  fallback_provider_ids: string[];
  /** Ordered per the rotation strategy; cooling-down keys are excluded. */
  candidates: PoolKeyCandidate[];
}

export type PoolOutcome =
  | { kind: "success" }
  | { kind: "failure"; failure_class: ProviderFailureClass; cooldown_seconds?: number; unhealthy?: boolean };

export interface ProviderPoolCredentialAddInput {
  api_key: string;
  name?: string;
  position?: number;
}

export interface ProviderPoolConfigUpdateInput {
  rotation_strategy?: RotationStrategy;
  fallback_provider_ids?: string[];
}

export interface ProviderTaskChainEntry {
  provider_id: string;
  model?: string | null;
}

export interface CliCredentialAuditInput {
  space_id: string;
  run_id?: string | null;
  runtime_adapter_type?: string | null;
  credential_profile_id?: string | null;
  trigger_origin?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  broker_error?: boolean;
  cleanup_status?: string;
  action?: string;
}

export interface ProviderCommandStore {
  createProvider(spaceId: string, input: ModelProviderCreateInput): Promise<unknown>;
  updateProvider(
    spaceId: string,
    providerId: string,
    input: ModelProviderUpdateInput,
  ): Promise<unknown>;
  deleteProvider(spaceId: string, providerId: string): Promise<void>;
  getInvocationTarget(spaceId: string, providerId?: string | null): Promise<InvocationTarget>;
  recordPoolOutcome(memberId: string, outcome: PoolOutcome): Promise<void>;
  resolveProviderApiKey(spaceId: string, providerId: string): Promise<string>;
  resolveCredentialApiKey(spaceId: string, credentialId: string): Promise<string>;
  listConfiguredModels(spaceId: string, providerId: string): Promise<string[]>;
  recordCliCredentialUsage(input: CliCredentialAuditInput): Promise<string>;
  listPool(spaceId: string, providerId: string): Promise<unknown>;
  addPoolCredential(
    spaceId: string,
    providerId: string,
    input: ProviderPoolCredentialAddInput,
  ): Promise<unknown>;
  removePoolCredential(spaceId: string, providerId: string, memberId: string): Promise<void>;
  updatePoolConfig(
    spaceId: string,
    providerId: string,
    input: ProviderPoolConfigUpdateInput,
  ): Promise<unknown>;
  getTaskChain(spaceId: string, task: string): Promise<ProviderTaskChainEntry[] | null>;
  listTaskPolicies(spaceId: string): Promise<unknown[]>;
  putTaskPolicy(
    spaceId: string,
    task: string,
    chain: ProviderTaskChainEntry[],
    enabled?: boolean,
  ): Promise<unknown>;
  deleteTaskPolicy(spaceId: string, task: string): Promise<void>;
}

type ProviderRow = Parameters<typeof mapProviderRowToDto>[0];

interface PoolMemberRow {
  id: string;
  credential_id: string;
  name: string;
  position: number;
  enabled: boolean;
  healthy: boolean;
  cooldown_until: Date | null;
  last_failure_class: string | null;
  request_count: string | number;
  failure_count: string | number;
  last_used_at: Date | null;
  created_at: Date;
  updated_at: Date;
  secret_ref?: string;
}

function validateProviderType(providerType: string): void {
  if (!PROVIDER_TYPES.has(providerType)) {
    throw new ProviderCommandValidationError(
      `Invalid provider_type '${providerType}'. Must be one of: ${[...PROVIDER_TYPES]
        .sort()
        .join(", ")}`,
    );
  }
}

function validateCreateFields(input: ModelProviderCreateInput): void {
  validateProviderType(input.provider_type);
  if (
    BASE_URL_REQUIRED_TYPES.has(input.provider_type) &&
    !(input.base_url && input.base_url.trim())
  ) {
    throw new ProviderCommandValidationError(
      `base_url is required for provider_type '${input.provider_type}'`,
    );
  }
  if (
    CLOUD_PROVIDER_TYPES.has(input.provider_type) &&
    !(input.api_key && input.api_key.trim())
  ) {
    throw new ProviderCommandValidationError(
      `api_key is required for provider_type '${input.provider_type}'`,
    );
  }
}

function validateBaseUrl(providerType: string, baseUrl: string | null): void {
  if (BASE_URL_REQUIRED_TYPES.has(providerType) && !(baseUrl && baseUrl.trim())) {
    throw new ProviderCommandValidationError(
      `base_url cannot be empty for provider_type '${providerType}'`,
    );
  }
}

function configuredModelsFromRow(row: ProviderRow): string[] {
  const caps = row.capabilities_json;
  if (Array.isArray(caps)) return caps.filter((m): m is string => typeof m === "string");
  if (caps !== null && typeof caps === "object") {
    const models = (caps as { models?: unknown }).models;
    if (Array.isArray(models)) return models.filter((m): m is string => typeof m === "string");
  }
  return [];
}

function configRecord(row: ProviderRow): Record<string, unknown> {
  return row.config_json !== null && typeof row.config_json === "object"
    ? { ...(row.config_json as Record<string, unknown>) }
    : {};
}

function isDefaultFromRow(row: ProviderRow): boolean {
  return Boolean(configRecord(row).is_default);
}

function rotationStrategyFromRow(row: ProviderRow): RotationStrategy {
  const value = configRecord(row).rotation_strategy;
  return typeof value === "string" && ROTATION_STRATEGIES.has(value)
    ? (value as RotationStrategy)
    : "fill_first";
}

function fallbackProviderIdsFromRow(row: ProviderRow): string[] {
  const value = configRecord(row).fallback_provider_ids;
  if (!Array.isArray(value)) return [];
  return value.filter((id): id is string => typeof id === "string");
}

function providerInfoFromRow(row: ProviderRow): ProviderInfo {
  return {
    id: row.id,
    space_id: row.space_id,
    name: row.name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    default_model: row.default_model,
    available_models: configuredModelsFromRow(row),
    enabled: Boolean(row.enabled),
    is_default: isDefaultFromRow(row),
  };
}

function modelList(defaultModel: string | null | undefined, availableModels?: string[]): string[] {
  const models = [...(availableModels ?? [])];
  if (defaultModel && !models.includes(defaultModel)) models.unshift(defaultModel);
  return models;
}

function json(value: unknown): string {
  return JSON.stringify(value);
}

function mapPoolMember(row: PoolMemberRow): Record<string, unknown> {
  return {
    id: row.id,
    credential_id: row.credential_id,
    name: row.name,
    position: row.position,
    enabled: row.enabled,
    healthy: row.healthy,
    cooldown_until: row.cooldown_until ? row.cooldown_until.toISOString() : null,
    last_failure_class: row.last_failure_class,
    request_count: Number(row.request_count),
    failure_count: Number(row.failure_count),
    last_used_at: row.last_used_at ? row.last_used_at.toISOString() : null,
    created_at: row.created_at.toISOString(),
    updated_at: row.updated_at.toISOString(),
  };
}

/** Order available members per the rotation strategy (Hermes H1). */
export function orderPoolMembers<T extends {
  position: number;
  request_count: string | number;
  last_used_at: Date | null;
}>(members: T[], strategy: RotationStrategy): T[] {
  const sorted = [...members];
  switch (strategy) {
    case "round_robin":
      // Least-recently-used first; never-used keys lead.
      sorted.sort((a, b) => {
        const aT = a.last_used_at?.getTime() ?? 0;
        const bT = b.last_used_at?.getTime() ?? 0;
        return aT - bT || a.position - b.position;
      });
      return sorted;
    case "least_used":
      sorted.sort((a, b) => Number(a.request_count) - Number(b.request_count) || a.position - b.position);
      return sorted;
    case "random":
      for (let i = sorted.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [sorted[i], sorted[j]] = [sorted[j], sorted[i]];
      }
      return sorted;
    case "fill_first":
    default:
      sorted.sort((a, b) => a.position - b.position);
      return sorted;
  }
}

class PgProviderCommandStore implements ProviderCommandStore {
  private pool: Pool;

  constructor(private config: ControlPlaneConfig) {
    if (!config.databaseUrl) {
      throw new Error("Provider command store requires CONTROL_PLANE_DATABASE_URL");
    }
    this.pool = getDbPool(config.databaseUrl);
  }

  private async masterKey(): Promise<Buffer> {
    return loadOrCreateModelProviderApiKeyMasterKey(this.config.agentSpaceHome);
  }

  private async providerById(spaceId: string, providerId: string): Promise<ProviderRow | null> {
    const result = await this.pool.query<ProviderRow>(
      `SELECT id, space_id, name, provider_type, base_url, default_model,
              enabled, credential_id, capabilities_json, config_json,
              created_at, updated_at
         FROM model_providers
        WHERE space_id = $1 AND id = $2
        LIMIT 1`,
      [spaceId, providerId],
    );
    return result.rows[0] ?? null;
  }

  private async defaultProvider(spaceId: string): Promise<ProviderRow | null> {
    const result = await this.pool.query<ProviderRow>(
      `SELECT id, space_id, name, provider_type, base_url, default_model,
              enabled, credential_id, capabilities_json, config_json,
              created_at, updated_at
         FROM model_providers
        WHERE space_id = $1
          AND enabled = true
          AND COALESCE((config_json->>'is_default')::boolean, false) = true
        ORDER BY created_at DESC
        LIMIT 1`,
      [spaceId],
    );
    return result.rows[0] ?? null;
  }

  private async requireProvider(spaceId: string, providerId: string): Promise<ProviderRow> {
    const row = await this.providerById(spaceId, providerId);
    if (!row) {
      throw new ProviderCommandNotFoundError(`ModelProvider '${providerId}' not found`);
    }
    return row;
  }

  private async clearDefault(spaceId: string, exceptId?: string): Promise<void> {
    await this.pool.query(
      `UPDATE model_providers
          SET config_json = jsonb_set(COALESCE(config_json, '{}'::jsonb), '{is_default}', 'false'::jsonb, true),
              updated_at = $2
        WHERE space_id = $1
          AND ($3::text IS NULL OR id <> $3)`,
      [spaceId, new Date(), exceptId ?? null],
    );
  }

  /**
   * Ensure the primary credential (`model_providers.credential_id`)
   * has a position-0 pool row, so pre-pool providers keep working and all
   * health state is tracked uniformly.
   */
  private async enrollPrimaryCredential(row: ProviderRow): Promise<void> {
    if (!row.credential_id) return;
    const now = new Date();
    await this.pool.query(
      `INSERT INTO model_provider_credentials
        (id, space_id, provider_id, credential_id, position, enabled, healthy,
         request_count, failure_count, created_at, updated_at)
       VALUES ($1, $2, $3, $4, 0, true, true, 0, 0, $5, $5)
       ON CONFLICT ON CONSTRAINT uq_model_provider_credentials_provider_credential
       DO NOTHING`,
      [randomUUID(), row.space_id, row.id, row.credential_id, now],
    );
  }

  private async poolMembers(
    spaceId: string,
    providerId: string,
    withSecrets: boolean,
  ): Promise<PoolMemberRow[]> {
    const secretColumn = withSecrets ? ", c.secret_ref" : "";
    const result = await this.pool.query<PoolMemberRow>(
      `SELECT m.id, m.credential_id, c.name, m.position, m.enabled, m.healthy,
              m.cooldown_until, m.last_failure_class, m.request_count,
              m.failure_count, m.last_used_at, m.created_at, m.updated_at${secretColumn}
         FROM model_provider_credentials m
         JOIN credentials c ON c.id = m.credential_id AND c.space_id = m.space_id
        WHERE m.space_id = $1 AND m.provider_id = $2
        ORDER BY m.position ASC, m.created_at ASC`,
      [spaceId, providerId],
    );
    return result.rows;
  }

  private async attachApiKeyCredential(
    spaceId: string,
    providerId: string,
    providerName: string,
    existingCredentialId: string | null | undefined,
    apiKey: string,
  ): Promise<string> {
    const secretRef = encryptModelProviderApiKeySecretRefV1(apiKey, await this.masterKey());
    const now = new Date();
    if (existingCredentialId) {
      const updated = await this.pool.query<{ id: string }>(
        `UPDATE credentials
            SET secret_ref = $3, updated_at = $4
          WHERE id = $1 AND space_id = $2
          RETURNING id`,
        [existingCredentialId, spaceId, secretRef, now],
      );
      if (updated.rows[0]) {
        // A re-keyed credential is healthy again until proven otherwise.
        await this.pool.query(
          `UPDATE model_provider_credentials
              SET healthy = true, cooldown_until = NULL, last_failure_class = NULL, updated_at = $3
            WHERE space_id = $1 AND credential_id = $2`,
          [spaceId, existingCredentialId, now],
        );
        return updated.rows[0].id;
      }
    }

    const credentialId = randomUUID();
    await this.pool.query(
      `INSERT INTO credentials
        (id, space_id, name, credential_type, secret_ref, scopes_json, created_at, updated_at)
       VALUES ($1, $2, $3, 'api_key', $4, $5::jsonb, $6, $6)`,
      [credentialId, spaceId, `${providerName} API key`, secretRef, json([]), now],
    );
    await this.pool.query(
      `UPDATE model_providers SET credential_id = $3, updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [providerId, spaceId, credentialId, now],
    );
    await this.pool.query(
      `INSERT INTO model_provider_credentials
        (id, space_id, provider_id, credential_id, position, enabled, healthy,
         request_count, failure_count, created_at, updated_at)
       VALUES ($1, $2, $3, $4, 0, true, true, 0, 0, $5, $5)
       ON CONFLICT ON CONSTRAINT uq_model_provider_credentials_provider_credential
       DO NOTHING`,
      [randomUUID(), spaceId, providerId, credentialId, now],
    );
    return credentialId;
  }

  async createProvider(spaceId: string, input: ModelProviderCreateInput): Promise<unknown> {
    validateCreateFields(input);
    const isDefault = Boolean(input.is_default);
    if (isDefault) await this.clearDefault(spaceId);

    const providerId = randomUUID();
    const now = new Date();
    const models = modelList(input.default_model, input.available_models ?? []);
    const name = input.name.trim();
    await this.pool.query(
      `INSERT INTO model_providers
        (id, space_id, name, provider_type, base_url, default_model, enabled,
         credential_id, capabilities_json, config_json, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, $8::jsonb, $9::jsonb, $10, $10)`,
      [
        providerId,
        spaceId,
        name,
        input.provider_type,
        input.base_url || null,
        input.default_model || (models[0] ?? null),
        input.enabled ?? true,
        json({ models }),
        json({ is_default: isDefault }),
        now,
      ],
    );
    if (input.api_key?.trim()) {
      await this.attachApiKeyCredential(spaceId, providerId, name, null, input.api_key);
    }
    const row = await this.providerById(spaceId, providerId);
    if (!row) throw new Error("created provider was not readable");
    return mapProviderRowToDto(row);
  }

  async updateProvider(
    spaceId: string,
    providerId: string,
    input: ModelProviderUpdateInput,
  ): Promise<unknown> {
    const current = await this.requireProvider(spaceId, providerId);

    const providerType = input.provider_type ?? current.provider_type;
    validateProviderType(providerType);
    const baseUrl =
      input.base_url === undefined ? current.base_url : input.base_url || null;
    validateBaseUrl(providerType, baseUrl);
    if (input.is_default === true && !isDefaultFromRow(current)) {
      await this.clearDefault(spaceId, providerId);
    }

    let credentialId = current.credential_id ?? null;
    const name = input.name === undefined ? current.name : input.name.trim();
    const apiKey = input.api_key?.trim();
    if (apiKey) {
      credentialId = await this.attachApiKeyCredential(
        spaceId,
        providerId,
        name,
        credentialId,
        apiKey,
      );
    }

    const available =
      input.available_models === undefined
        ? configuredModelsFromRow(current)
        : input.available_models;
    const defaultModel =
      input.default_model === undefined ? current.default_model : input.default_model || null;
    const configJson = configRecord(current);
    if (input.is_default !== undefined) configJson.is_default = input.is_default;

    const updated = await this.pool.query<ProviderRow>(
      `UPDATE model_providers
          SET name = $3,
              provider_type = $4,
              base_url = $5,
              default_model = $6,
              enabled = $7,
              credential_id = $8,
              capabilities_json = $9::jsonb,
              config_json = $10::jsonb,
              updated_at = $11
        WHERE id = $1 AND space_id = $2
        RETURNING id, space_id, name, provider_type, base_url, default_model,
                  enabled, credential_id, capabilities_json, config_json,
                  created_at, updated_at`,
      [
        providerId,
        spaceId,
        name,
        providerType,
        baseUrl,
        defaultModel,
        input.enabled ?? current.enabled,
        credentialId,
        json({ models: modelList(defaultModel, available) }),
        json(configJson),
        new Date(),
      ],
    );
    return mapProviderRowToDto(updated.rows[0]);
  }

  async deleteProvider(spaceId: string, providerId: string): Promise<void> {
    const current = await this.requireProvider(spaceId, providerId);
    const cfg = configRecord(current);
    cfg.is_default = false;
    await this.pool.query(
      `UPDATE model_providers
          SET enabled = false, config_json = $3::jsonb, updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [providerId, spaceId, json(cfg), new Date()],
    );
  }

  async getInvocationTarget(
    spaceId: string,
    providerId?: string | null,
  ): Promise<InvocationTarget> {
    const row = providerId
      ? await this.providerById(spaceId, providerId)
      : await this.defaultProvider(spaceId);
    if (!row) {
      throw new ProviderCommandNotFoundError(
        providerId ? `ModelProvider '${providerId}' not found` : "No default provider configured",
      );
    }
    if (!row.enabled) {
      throw new ProviderCommandNotFoundError(`ModelProvider '${row.id}' is disabled`);
    }
    await this.enrollPrimaryCredential(row);

    const strategy = rotationStrategyFromRow(row);
    const members = await this.poolMembers(spaceId, row.id, true);
    const now = Date.now();
    const available = members.filter(
      (m) => m.enabled && (!m.cooldown_until || m.cooldown_until.getTime() <= now),
    );
    const masterKey = members.length > 0 ? await this.masterKey() : null;
    const candidates: PoolKeyCandidate[] = orderPoolMembers(available, strategy).map((m) => ({
      member_id: m.id,
      credential_id: m.credential_id,
      api_key: masterKey && m.secret_ref
        ? decryptModelProviderApiKeySecretRefV1(m.secret_ref, masterKey)
        : null,
    }));
    // Key-less providers (e.g. ollama) still get one attempt slot.
    if (candidates.length === 0 && members.length === 0) {
      candidates.push({ member_id: null, credential_id: null, api_key: null });
    }
    return {
      provider: providerInfoFromRow(row),
      rotation_strategy: strategy,
      fallback_provider_ids: fallbackProviderIdsFromRow(row),
      candidates,
    };
  }

  async recordPoolOutcome(memberId: string, outcome: PoolOutcome): Promise<void> {
    const now = new Date();
    if (outcome.kind === "success") {
      await this.pool.query(
        `UPDATE model_provider_credentials
            SET request_count = request_count + 1,
                last_used_at = $2,
                healthy = true,
                cooldown_until = NULL,
                last_failure_class = NULL,
                updated_at = $2
          WHERE id = $1`,
        [memberId, now],
      );
      return;
    }
    const cooldownUntil = outcome.cooldown_seconds
      ? new Date(now.getTime() + outcome.cooldown_seconds * 1_000)
      : null;
    await this.pool.query(
      `UPDATE model_provider_credentials
          SET request_count = request_count + 1,
              failure_count = failure_count + 1,
              last_used_at = $2,
              healthy = $3,
              cooldown_until = COALESCE($4, cooldown_until),
              last_failure_class = $5,
              updated_at = $2
        WHERE id = $1`,
      [memberId, now, !outcome.unhealthy, cooldownUntil, outcome.failure_class],
    );
  }

  async resolveProviderApiKey(spaceId: string, providerId: string): Promise<string> {
    const target = await this.getInvocationTarget(spaceId, providerId);
    const candidate = target.candidates.find((c) => c.api_key);
    if (!candidate?.api_key) {
      throw new ProviderCommandValidationError(
        `ModelProvider '${providerId}' has no available API key credential`,
      );
    }
    if (candidate.member_id) {
      await this.recordPoolOutcome(candidate.member_id, { kind: "success" });
    }
    return candidate.api_key;
  }

  async resolveCredentialApiKey(spaceId: string, credentialId: string): Promise<string> {
    const result = await this.pool.query<{ secret_ref: string }>(
      `SELECT secret_ref
         FROM credentials
        WHERE id = $1 AND space_id = $2 AND credential_type = 'api_key'
        LIMIT 1`,
      [credentialId, spaceId],
    );
    const secretRef = result.rows[0]?.secret_ref;
    if (!secretRef) {
      throw new ProviderCommandNotFoundError(`Credential '${credentialId}' not found`);
    }
    const apiKey = decryptModelProviderApiKeySecretRefV1(secretRef, await this.masterKey());
    if (!apiKey) {
      throw new ProviderCommandValidationError(
        `Credential '${credentialId}' resolved to an empty API key`,
      );
    }
    return apiKey;
  }

  async listConfiguredModels(spaceId: string, providerId: string): Promise<string[]> {
    const row = await this.requireProvider(spaceId, providerId);
    const configured = configuredModelsFromRow(row);
    if (configured.length > 0) return configured;
    return row.default_model ? [row.default_model] : [];
  }

  async recordCliCredentialUsage(input: CliCredentialAuditInput): Promise<string> {
    const eventId = randomUUID();
    const credentialSource = input.credential_profile_id ? "profile" : "none";
    await this.pool.query(
      `INSERT INTO cli_credential_events
        (id, space_id, run_id, runtime_adapter_type,
         credential_profile_id, credential_source, trigger_origin, fallback_used,
         fallback_reason, broker_error, cleanup_status, action, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
      [
        eventId,
        input.space_id,
        input.run_id ?? null,
        input.runtime_adapter_type ?? null,
        input.credential_profile_id ?? null,
        credentialSource,
        input.trigger_origin ?? null,
        Boolean(input.fallback_used),
        input.fallback_reason ?? null,
        Boolean(input.broker_error),
        input.cleanup_status ?? "not_needed",
        input.action ?? "grant",
        new Date(),
      ],
    );
    return eventId;
  }

  // -------------------------------------------------------------------------
  // Credential pool management (Hermes H1)
  // -------------------------------------------------------------------------

  async listPool(spaceId: string, providerId: string): Promise<unknown> {
    const row = await this.requireProvider(spaceId, providerId);
    await this.enrollPrimaryCredential(row);
    const members = await this.poolMembers(spaceId, providerId, false);
    return {
      provider_id: providerId,
      rotation_strategy: rotationStrategyFromRow(row),
      fallback_provider_ids: fallbackProviderIdsFromRow(row),
      members: members.map(mapPoolMember),
    };
  }

  async addPoolCredential(
    spaceId: string,
    providerId: string,
    input: ProviderPoolCredentialAddInput,
  ): Promise<unknown> {
    const row = await this.requireProvider(spaceId, providerId);
    if (!input.api_key.trim()) {
      throw new ProviderCommandValidationError("api_key must not be empty");
    }
    await this.enrollPrimaryCredential(row);

    const secretRef = encryptModelProviderApiKeySecretRefV1(input.api_key, await this.masterKey());
    const now = new Date();
    const credentialId = randomUUID();
    const memberId = randomUUID();
    const name = input.name?.trim() || `${row.name} pool key`;
    let position = input.position;
    if (position === undefined) {
      const result = await this.pool.query<{ max: number | null }>(
        `SELECT MAX(position) AS max FROM model_provider_credentials
          WHERE space_id = $1 AND provider_id = $2`,
        [spaceId, providerId],
      );
      position = (result.rows[0]?.max ?? -1) + 1;
    }

    await this.pool.query(
      `INSERT INTO credentials
        (id, space_id, name, credential_type, secret_ref, scopes_json, created_at, updated_at)
       VALUES ($1, $2, $3, 'api_key', $4, $5::jsonb, $6, $6)`,
      [credentialId, spaceId, name, secretRef, json([]), now],
    );
    await this.pool.query(
      `INSERT INTO model_provider_credentials
        (id, space_id, provider_id, credential_id, position, enabled, healthy,
         request_count, failure_count, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, true, true, 0, 0, $6, $6)`,
      [memberId, spaceId, providerId, credentialId, position, now],
    );
    // A provider that previously had no key at all gains this one as primary.
    if (!row.credential_id) {
      await this.pool.query(
        `UPDATE model_providers SET credential_id = $3, updated_at = $4
          WHERE id = $1 AND space_id = $2`,
        [providerId, spaceId, credentialId, now],
      );
    }
    const members = await this.poolMembers(spaceId, providerId, false);
    const created = members.find((m) => m.id === memberId);
    if (!created) throw new Error("created pool member was not readable");
    return mapPoolMember(created);
  }

  async removePoolCredential(spaceId: string, providerId: string, memberId: string): Promise<void> {
    const row = await this.requireProvider(spaceId, providerId);
    const member = await this.pool.query<{ credential_id: string }>(
      `DELETE FROM model_provider_credentials
        WHERE id = $1 AND space_id = $2 AND provider_id = $3
        RETURNING credential_id`,
      [memberId, spaceId, providerId],
    );
    const credentialId = member.rows[0]?.credential_id;
    if (!credentialId) {
      throw new ProviderCommandNotFoundError(`Pool credential '${memberId}' not found`);
    }
    const now = new Date();
    if (row.credential_id === credentialId) {
      // Primary removed: promote the lowest-position remaining member.
      const remaining = await this.poolMembers(spaceId, providerId, false);
      const next = remaining[0]?.credential_id ?? null;
      await this.pool.query(
        `UPDATE model_providers SET credential_id = $3, updated_at = $4
          WHERE id = $1 AND space_id = $2`,
        [providerId, spaceId, next, now],
      );
    }
    // Drop the credential row itself unless any other pool still references it.
    const stillUsed = await this.pool.query(
      `SELECT 1 FROM model_provider_credentials WHERE credential_id = $1
        UNION ALL
       SELECT 1 FROM model_providers WHERE credential_id = $1
        LIMIT 1`,
      [credentialId],
    );
    if (stillUsed.rows.length === 0) {
      await this.pool.query(`DELETE FROM credentials WHERE id = $1 AND space_id = $2`, [
        credentialId,
        spaceId,
      ]);
    }
  }

  async updatePoolConfig(
    spaceId: string,
    providerId: string,
    input: ProviderPoolConfigUpdateInput,
  ): Promise<unknown> {
    const row = await this.requireProvider(spaceId, providerId);
    const cfg = configRecord(row);
    if (input.rotation_strategy !== undefined) {
      if (!ROTATION_STRATEGIES.has(input.rotation_strategy)) {
        throw new ProviderCommandValidationError(
          `Invalid rotation_strategy '${input.rotation_strategy}'`,
        );
      }
      cfg.rotation_strategy = input.rotation_strategy;
    }
    if (input.fallback_provider_ids !== undefined) {
      for (const id of input.fallback_provider_ids) {
        if (id === providerId) {
          throw new ProviderCommandValidationError(
            "fallback_provider_ids must not contain the provider itself",
          );
        }
        await this.requireProvider(spaceId, id);
      }
      cfg.fallback_provider_ids = input.fallback_provider_ids;
    }
    await this.pool.query(
      `UPDATE model_providers SET config_json = $3::jsonb, updated_at = $4
        WHERE id = $1 AND space_id = $2`,
      [providerId, spaceId, json(cfg), new Date()],
    );
    return this.listPool(spaceId, providerId);
  }

  // -------------------------------------------------------------------------
  // Per-auxiliary-task provider chains (Hermes H2)
  // -------------------------------------------------------------------------

  async getTaskChain(spaceId: string, task: string): Promise<ProviderTaskChainEntry[] | null> {
    const result = await this.pool.query<{ chain_json: unknown }>(
      `SELECT chain_json FROM provider_task_policies
        WHERE space_id = $1 AND task = $2 AND enabled = true
        LIMIT 1`,
      [spaceId, task],
    );
    const chain = result.rows[0]?.chain_json;
    if (!Array.isArray(chain)) return null;
    const entries = chain
      .filter((e): e is { provider_id: string; model?: string | null } =>
        e !== null && typeof e === "object" && typeof (e as { provider_id?: unknown }).provider_id === "string",
      )
      .map((e) => ({ provider_id: e.provider_id, model: e.model ?? null }));
    return entries.length > 0 ? entries : null;
  }

  async listTaskPolicies(spaceId: string): Promise<unknown[]> {
    const result = await this.pool.query<{
      task: string;
      chain_json: unknown;
      enabled: boolean;
      updated_at: Date;
    }>(
      `SELECT task, chain_json, enabled, updated_at
         FROM provider_task_policies
        WHERE space_id = $1
        ORDER BY task ASC`,
      [spaceId],
    );
    return result.rows.map((row) => ({
      task: row.task,
      chain: Array.isArray(row.chain_json) ? row.chain_json : [],
      enabled: row.enabled,
      updated_at: row.updated_at.toISOString(),
    }));
  }

  async putTaskPolicy(
    spaceId: string,
    task: string,
    chain: ProviderTaskChainEntry[],
    enabled = true,
  ): Promise<unknown> {
    for (const entry of chain) {
      await this.requireProvider(spaceId, entry.provider_id);
    }
    const now = new Date();
    await this.pool.query(
      `INSERT INTO provider_task_policies
        (id, space_id, task, chain_json, enabled, created_at, updated_at)
       VALUES ($1, $2, $3, $4::jsonb, $5, $6, $6)
       ON CONFLICT ON CONSTRAINT uq_provider_task_policies_space_task
       DO UPDATE SET chain_json = EXCLUDED.chain_json,
                     enabled = EXCLUDED.enabled,
                     updated_at = EXCLUDED.updated_at`,
      [randomUUID(), spaceId, task, json(chain), enabled, now],
    );
    return {
      task,
      chain: chain.map((e) => ({ provider_id: e.provider_id, model: e.model ?? null })),
      enabled,
      updated_at: now.toISOString(),
    };
  }

  async deleteTaskPolicy(spaceId: string, task: string): Promise<void> {
    const result = await this.pool.query(
      `DELETE FROM provider_task_policies WHERE space_id = $1 AND task = $2`,
      [spaceId, task],
    );
    if (result.rowCount === 0) {
      throw new ProviderCommandNotFoundError(`Task policy '${task}' not found`);
    }
  }
}

let testOverride: ProviderCommandStore | null = null;
let pgStore: PgProviderCommandStore | null = null;
let pgStoreKey: string | null = null;

export function __setProviderCommandStoreForTests(
  store: ProviderCommandStore | null,
): void {
  testOverride = store;
}

export function resolveProviderCommandStore(config: ControlPlaneConfig): ProviderCommandStore {
  if (testOverride) return testOverride;
  if (!config.databaseUrl) {
    throw new Error("Provider command store requires CONTROL_PLANE_DATABASE_URL");
  }
  const key = `${config.databaseUrl}|${config.agentSpaceHome}`;
  if (!pgStore || pgStoreKey !== key) {
    pgStore = new PgProviderCommandStore(config);
    pgStoreKey = key;
  }
  return pgStore;
}
