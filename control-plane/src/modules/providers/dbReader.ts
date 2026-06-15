/**
 * Provider DB read port.
 *
 * SELECTs exactly the columns in the protocol package's
 * `MODEL_PROVIDERS_READ_COLUMNS` allowlist (a Python contract test pins that
 * list to the ORM schema) and maps rows to the public `ModelProviderDTO`
 * wire shape with the same semantics as Python's `ModelProviderOut.from_db_row`:
 * `available_models` from `capabilities_json`, `is_default` from
 * `config_json`, `has_api_key` from `credential_id`. This reader does not
 * perform writes; Python/alembic owns the schema.
 */

import { getDbPool, type Pool } from "./db";
import type { ControlPlaneConfig } from "../../config";
import { loadProtocol } from "./protocolRuntime";

export interface ProvidersDbPort {
  listProviders(spaceId: string): Promise<unknown[]>;
  getProvider(spaceId: string, configId: string): Promise<unknown | null>;
}

interface ProviderRow {
  id: string;
  space_id: string;
  name: string;
  provider_type: string;
  base_url: string | null;
  default_model: string | null;
  enabled: boolean;
  credential_id: string | null;
  capabilities_json: unknown;
  config_json: unknown;
  created_at: Date;
  updated_at: Date;
}

function availableModels(capabilities: unknown): string[] {
  if (Array.isArray(capabilities)) {
    return capabilities.filter((m): m is string => typeof m === "string");
  }
  if (capabilities !== null && typeof capabilities === "object") {
    const models = (capabilities as { models?: unknown }).models;
    if (Array.isArray(models)) {
      return models.filter((m): m is string => typeof m === "string");
    }
  }
  return [];
}

function isDefault(config: unknown): boolean {
  if (config !== null && typeof config === "object") {
    return Boolean((config as { is_default?: unknown }).is_default);
  }
  return false;
}

export function mapProviderRowToDto(row: ProviderRow): Record<string, unknown> {
  return {
    id: row.id,
    space_id: row.space_id,
    name: row.name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    default_model: row.default_model,
    available_models: availableModels(row.capabilities_json),
    enabled: Boolean(row.enabled),
    is_default: isDefault(row.config_json),
    has_api_key: row.credential_id !== null && row.credential_id !== undefined,
    created_at: row.created_at.toISOString(),
    updated_at: row.updated_at.toISOString(),
  };
}

class PgProvidersDbPort implements ProvidersDbPort {
  private pool: Pool;

  constructor(databaseUrl: string) {
    this.pool = getDbPool(databaseUrl);
  }

  private async selectClause(): Promise<{ table: string; columns: string }> {
    const protocol = await loadProtocol();
    return {
      table: protocol.MODEL_PROVIDERS_TABLE,
      columns: protocol.MODEL_PROVIDERS_READ_COLUMNS.map((c) => `"${c}"`).join(", "),
    };
  }

  async listProviders(spaceId: string): Promise<unknown[]> {
    const { table, columns } = await this.selectClause();
    const result = await this.pool.query<ProviderRow>(
      `SELECT ${columns} FROM "${table}" WHERE space_id = $1 ORDER BY created_at DESC`,
      [spaceId],
    );
    return result.rows.map(mapProviderRowToDto);
  }

  async getProvider(spaceId: string, configId: string): Promise<unknown | null> {
    const { table, columns } = await this.selectClause();
    const result = await this.pool.query<ProviderRow>(
      `SELECT ${columns} FROM "${table}" WHERE space_id = $1 AND id = $2 LIMIT 1`,
      [spaceId, configId],
    );
    if (result.rows.length === 0) return null;
    return mapProviderRowToDto(result.rows[0]);
  }
}

let testOverride: ProvidersDbPort | null = null;
let pgPort: PgProvidersDbPort | null = null;
let pgPortUrl: string | null = null;

/** Test helper: inject a fake DB port (pass null to restore the real one). */
export function __setProvidersDbPortForTests(port: ProvidersDbPort | null): void {
  testOverride = port;
}

/** Resolve the DB port for this config, or null when no database is configured. */
export function resolveProvidersDbPort(config: ControlPlaneConfig): ProvidersDbPort | null {
  if (testOverride) return testOverride;
  if (!config.databaseUrl) return null;
  if (!pgPort || pgPortUrl !== config.databaseUrl) {
    pgPort = new PgProvidersDbPort(config.databaseUrl);
    pgPortUrl = config.databaseUrl;
  }
  return pgPort;
}
