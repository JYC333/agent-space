/**
 * DB column allowlist for the provider reader.
 *
 * This is the cross-language schema-drift ratchet: the TS reader SELECTs
 * exactly these columns, and a Python contract test asserts this list matches
 * the `ModelProvider` ORM table. Adding, renaming, or dropping a column on
 * either side fails tests instead of breaking requests.
 *
 * Python/alembic remains the exclusive schema owner; this file grants no write
 * capability and is not a wire contract.
 */

export const MODEL_PROVIDERS_TABLE = "model_providers" as const;

export const MODEL_PROVIDERS_READ_COLUMNS = [
  "id",
  "space_id",
  "name",
  "provider_type",
  "base_url",
  "default_model",
  "enabled",
  "credential_id",
  "capabilities_json",
  "config_json",
  "created_at",
  "updated_at",
] as const;
export type ModelProvidersReadColumn = (typeof MODEL_PROVIDERS_READ_COLUMNS)[number];
