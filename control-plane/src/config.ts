/**
 * Control-plane configuration — parsed and validated from the environment at
 * startup.
 *
 * The control plane is the default client-facing TypeScript service. It
 * holds NO secrets of its own (auth/credentials remain server-side in Python);
 * this config only describes how to bind and where the legacy Python authority
 * lives. Validation fails fast on a malformed `LEGACY_PYTHON_API_BASE_URL` so a
 * misconfigured proxy never starts silently.
 *
 * Beyond the validated config object, this module provides:
 * - {@link ConfigError} with a machine `code` for every validation failure.
 * - {@link ConfigSnapshot} — an immutable snapshot (schema version + content
 *   hash + load timestamp) distributed to TS-owned modules via `ModuleContext`.
 * - {@link collectConfigDiagnostics} — non-fatal startup diagnostics with
 *   severity + machine codes (e.g. unrecognized `CONTROL_PLANE_*` variables).
 */

import { createHash } from "node:crypto";
import { resolve } from "node:path";

export interface ControlPlaneConfig {
  host: string;
  port: number;
  /** Base URL of the legacy Python authority used by the temporary fallback proxy. */
  legacyPythonApiBaseUrl: string;
  enableLegacyProxy: boolean;
  logLevel: string;
  requestTimeoutMs: number;
  /** Absolute path of the built-in `catalog/` directory read by the catalog module. */
  catalogRoot: string;
}

export interface RawEnv {
  [key: string]: string | undefined;
}

const VALID_LOG_LEVELS = new Set([
  "fatal",
  "error",
  "warn",
  "info",
  "debug",
  "trace",
  "silent",
]);

/** Environment variables this config recognizes (used by diagnostics). */
const KNOWN_ENV_KEYS = new Set([
  "CONTROL_PLANE_HOST",
  "CONTROL_PLANE_PORT",
  "LEGACY_PYTHON_API_BASE_URL",
  "CONTROL_PLANE_ENABLE_LEGACY_PROXY",
  "CONTROL_PLANE_LOG_LEVEL",
  "CONTROL_PLANE_REQUEST_TIMEOUT_MS",
  "CONTROL_PLANE_CATALOG_ROOT",
]);

export class ConfigError extends Error {
  /** Machine-readable error code (e.g. `invalid_log_level`). */
  readonly code: string;

  constructor(message: string, code = "invalid_config") {
    super(message);
    this.name = "ConfigError";
    this.code = code;
  }
}

function parseBool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value === "") return fallback;
  const v = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(v)) return true;
  if (["0", "false", "no", "off"].includes(v)) return false;
  throw new ConfigError(
    `Invalid boolean value: ${JSON.stringify(value)}`,
    "invalid_boolean",
  );
}

function parseIntStrict(
  value: string | undefined,
  fallback: number,
  name: string,
): number {
  if (value === undefined || value === "") return fallback;
  const n = Number(value);
  if (!Number.isInteger(n) || n <= 0) {
    throw new ConfigError(
      `${name} must be a positive integer, got ${JSON.stringify(value)}`,
      "invalid_positive_integer",
    );
  }
  return n;
}

function validateBaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(
      `LEGACY_PYTHON_API_BASE_URL is not a valid URL: ${JSON.stringify(value)}`,
      "invalid_base_url",
    );
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError(
      `LEGACY_PYTHON_API_BASE_URL must be http(s), got ${JSON.stringify(url.protocol)}`,
      "invalid_url_protocol",
    );
  }
  // Normalise: drop a trailing slash so we can concatenate request paths cleanly.
  return value.replace(/\/+$/, "");
}

/**
 * Build a validated config from an environment map. Throws {@link ConfigError}
 * on any invalid value (fail-fast).
 */
export function loadConfig(env: RawEnv = process.env): ControlPlaneConfig {
  const host = env.CONTROL_PLANE_HOST?.trim() || "0.0.0.0";
  const port = parseIntStrict(env.CONTROL_PLANE_PORT, 8010, "CONTROL_PLANE_PORT");
  const legacyPythonApiBaseUrl = validateBaseUrl(
    env.LEGACY_PYTHON_API_BASE_URL?.trim() || "http://backend:8000",
  );
  const enableLegacyProxy = parseBool(env.CONTROL_PLANE_ENABLE_LEGACY_PROXY, true);
  const logLevel = (env.CONTROL_PLANE_LOG_LEVEL?.trim() || "info").toLowerCase();
  if (!VALID_LOG_LEVELS.has(logLevel)) {
    throw new ConfigError(
      `CONTROL_PLANE_LOG_LEVEL must be one of ${[...VALID_LOG_LEVELS].join(", ")}, got ${JSON.stringify(logLevel)}`,
      "invalid_log_level",
    );
  }
  const requestTimeoutMs = parseIntStrict(
    env.CONTROL_PLANE_REQUEST_TIMEOUT_MS,
    300_000,
    "CONTROL_PLANE_REQUEST_TIMEOUT_MS",
  );
  // Default: the repo/image layout places `catalog/` next to `control-plane/`
  // (locally: <repo>/catalog; in the image: /app/catalog with cwd /app/control-plane).
  const catalogRoot = resolve(
    env.CONTROL_PLANE_CATALOG_ROOT?.trim() || resolve(process.cwd(), "..", "catalog"),
  );

  return {
    host,
    port,
    legacyPythonApiBaseUrl,
    enableLegacyProxy,
    logLevel,
    requestTimeoutMs,
    catalogRoot,
  };
}

/** A one-line, secret-free description of the effective config for startup logs. */
export function describeConfig(config: ControlPlaneConfig): string {
  return [
    `host=${config.host}`,
    `port=${config.port}`,
    `legacyPythonApiBaseUrl=${config.legacyPythonApiBaseUrl}`,
    `legacyProxy=${config.enableLegacyProxy}`,
    `logLevel=${config.logLevel}`,
    `requestTimeoutMs=${config.requestTimeoutMs}`,
    `catalogRoot=${config.catalogRoot}`,
  ].join(" ");
}

// ---------------------------------------------------------------------------
// Immutable config snapshot
// ---------------------------------------------------------------------------

/** Bumped when the shape of {@link ControlPlaneConfig} changes incompatibly. */
export const CONFIG_SCHEMA_VERSION = 1 as const;

/**
 * An immutable, hash-identified view of the validated config. Built once at
 * startup and handed to every TS-owned module via `ModuleContext`. The hash is
 * deterministic over the config content (it excludes `loaded_at`), so two
 * snapshots of the same config always agree.
 */
export interface ConfigSnapshot {
  schema_version: typeof CONFIG_SCHEMA_VERSION;
  /** SHA-256 hex of the canonical (key-sorted) config JSON. No secrets exist in this config. */
  content_hash: string;
  /** ISO-8601 timestamp of when this snapshot was created. */
  loaded_at: string;
  config: Readonly<ControlPlaneConfig>;
}

function canonicalConfigJson(config: ControlPlaneConfig): string {
  const record = config as unknown as Record<string, unknown>;
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) sorted[key] = record[key];
  return JSON.stringify(sorted);
}

export function createConfigSnapshot(
  config: ControlPlaneConfig,
  now: () => Date = () => new Date(),
): ConfigSnapshot {
  const frozen = Object.freeze({ ...config });
  return Object.freeze({
    schema_version: CONFIG_SCHEMA_VERSION,
    content_hash: createHash("sha256").update(canonicalConfigJson(frozen)).digest("hex"),
    loaded_at: now().toISOString(),
    config: frozen,
  });
}

/** Load + validate config from the environment and wrap it in a snapshot. */
export function loadConfigSnapshot(env: RawEnv = process.env): ConfigSnapshot {
  return createConfigSnapshot(loadConfig(env));
}

// ---------------------------------------------------------------------------
// Startup diagnostics
// ---------------------------------------------------------------------------

export type ConfigDiagnosticSeverity = "info" | "warning" | "error" | "fatal";

export interface ConfigDiagnostic {
  severity: ConfigDiagnosticSeverity;
  /** Machine-readable code (e.g. `unknown_config_key`). */
  code: string;
  message: string;
}

/**
 * Non-fatal configuration diagnostics. Currently flags `CONTROL_PLANE_*`
 * variables this config does not recognize (likely typos), so a misspelled
 * override never gets silently ignored. Fatal problems are not diagnostics —
 * they throw {@link ConfigError} in {@link loadConfig}.
 */
export function collectConfigDiagnostics(env: RawEnv = process.env): ConfigDiagnostic[] {
  const diagnostics: ConfigDiagnostic[] = [];
  for (const key of Object.keys(env).sort()) {
    if (!key.startsWith("CONTROL_PLANE_")) continue;
    if (KNOWN_ENV_KEYS.has(key)) continue;
    diagnostics.push({
      severity: "warning",
      code: "unknown_config_key",
      message: `Unrecognized environment variable ${key} (ignored)`,
    });
  }
  return diagnostics;
}
