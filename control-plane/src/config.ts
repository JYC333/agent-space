/**
 * Control-plane configuration — parsed and validated from the environment at
 * startup.
 *
 * The control plane is the default client-facing TypeScript service. It
 * normally holds no secrets of its own. Provider/credential internal ports use
 * `CONTROL_PLANE_INTERNAL_TOKEN` only for service-to-service calls. This module
 * never logs that token and redacts it from config snapshot hashes. Validation
 * fails fast on a malformed Python upstream URL so a misconfigured proxy never
 * starts silently.
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
  /** Base URL of the Python backend used by the fallback proxy. */
  pythonApiBaseUrl: string;
  enablePythonFallbackProxy: boolean;
  logLevel: string;
  requestTimeoutMs: number;
  /** Absolute path of the built-in `catalog/` directory read by the catalog module. */
  catalogRoot: string;
  /** Poll cadence for the TS-owned run-event SSE edge. */
  runEventStreamPollIntervalMs: number;
  /** Page size used when the SSE edge reads run events from Python. */
  runEventStreamPageLimit: number;
  /** Whether outbound webhook notification egress is enabled. Disabled by default. */
  enableNotificationWebhookEgress: boolean;
  /** Exact, normalized webhook URLs allowed for outbound notification egress. */
  notificationWebhookAllowlist: string[];
  /** Maximum JSON body sent to an outbound notification webhook. */
  notificationMaxPayloadBytes: number;
  /**
   * PostgreSQL connection string for TS-owned reads/commands. Python/Alembic
   * remains the schema owner.
   */
  databaseUrl: string | null;
  /** Instance root used for provider key material and CLI credential profiles. */
  agentSpaceHome: string;
  /** Instance-owned runtime CLI installation root. */
  cliToolsRoot: string;
  /** Root for registered workspace directories. */
  workspaceRoot: string;
  /** Root for short-lived run sandboxes (worktrees, ephemeral working dirs). */
  sandboxRoot: string;
  /** Root for persisted artifact file storage. Artifact.storage_path is relative to this. */
  artifactStorageRoot: string;
  /** Unix socket for the host deployer process. */
  deployerSocketPath: string;
  /** Service-to-service token for internal providers/credentials ports. */
  internalToken: string | null;
  /** Google OAuth client id. Empty means Google login is disabled. */
  googleClientId: string;
  /** Google OAuth client secret. Redacted from diagnostics and snapshots. */
  googleClientSecret: string;
  /** Redirect URI registered with Google. */
  googleRedirectUri: string;
  /** Frontend base URL used for post-login redirects. */
  frontendUrl: string;
  /** Session cookie lifetime in days. */
  sessionExpireDays: number;
  /** Mirrors Python DEBUG for secure cookie defaults. */
  debug: boolean;
  dailyReportSchedulerEnabled: boolean;
  dailyReportSchedulerIntervalSeconds: number;
  automationSchedulerEnabled: boolean;
  automationSchedulerIntervalSeconds: number;
  memoryAccessLogRetentionEnabled: boolean;
  memoryAccessLogRetentionDays: number;
  memoryAccessLogPruneIntervalSeconds: number;
  intakeExtractionSchedulerEnabled: boolean;
  intakeExtractionSchedulerIntervalSeconds: number;
  agentSpaceEnv: string;
  appVersion: string | null;
  backupEnabled: boolean;
  backupIntervalHours: number;
  backupRetentionCount: number;
  backupIncludeLogs: boolean;
  backupOnStartup: boolean;
  backupRoot: string;
  backupAcceptNoBackup: boolean;
  /** Full-privilege database URL used only for full-system backup dumps. */
  backupDatabaseUrl: string | null;
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
  "CONTROL_PLANE_PYTHON_API_BASE_URL",
  "CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY",
  "CONTROL_PLANE_LOG_LEVEL",
  "CONTROL_PLANE_REQUEST_TIMEOUT_MS",
  "CONTROL_PLANE_CATALOG_ROOT",
  "CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS",
  "CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT",
  "CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS",
  "CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST",
  "CONTROL_PLANE_NOTIFICATION_MAX_PAYLOAD_BYTES",
  "CONTROL_PLANE_DATABASE_URL",
  "AGENT_SPACE_HOME",
  "CONTROL_PLANE_CLI_TOOLS_ROOT",
  "WORKSPACE_ROOT",
  "SANDBOX_ROOT",
  "ARTIFACT_STORAGE_ROOT",
  "DEPLOYER_SOCKET_PATH",
  "CONTROL_PLANE_INTERNAL_TOKEN",
  "GOOGLE_CLIENT_ID",
  "GOOGLE_CLIENT_SECRET",
  "GOOGLE_REDIRECT_URI",
  "FRONTEND_URL",
  "SESSION_EXPIRE_DAYS",
  "DEBUG",
  "CONTROL_PLANE_DAILY_REPORT_SCHEDULER_ENABLED",
  "CONTROL_PLANE_DAILY_REPORT_SCHEDULER_INTERVAL_SECONDS",
  "CONTROL_PLANE_AUTOMATION_SCHEDULER_ENABLED",
  "CONTROL_PLANE_AUTOMATION_SCHEDULER_INTERVAL_SECONDS",
  "CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_ENABLED",
  "CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_DAYS",
  "CONTROL_PLANE_MEMORY_ACCESS_LOG_PRUNE_INTERVAL_SECONDS",
  "CONTROL_PLANE_INTAKE_EXTRACTION_SCHEDULER_ENABLED",
  "CONTROL_PLANE_INTAKE_EXTRACTION_SCHEDULER_INTERVAL_SECONDS",
  "AGENT_SPACE_ENV",
  "APP_VERSION",
  "BACKUP_ENABLED",
  "BACKUP_INTERVAL_HOURS",
  "BACKUP_RETENTION_COUNT",
  "BACKUP_INCLUDE_LOGS",
  "BACKUP_ON_STARTUP",
  "BACKUP_ROOT",
  "BACKUP_ACCEPT_NO_BACKUP",
  "BACKUP_DATABASE_URL",
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

function parseBoundedInt(
  value: string | undefined,
  fallback: number,
  name: string,
  min: number,
  max: number,
): number {
  const n = parseIntStrict(value, fallback, name);
  if (n < min || n > max) {
    throw new ConfigError(
      `${name} must be between ${min} and ${max}, got ${JSON.stringify(n)}`,
      "invalid_bounded_integer",
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
      `CONTROL_PLANE_PYTHON_API_BASE_URL is not a valid URL: ${JSON.stringify(value)}`,
      "invalid_base_url",
    );
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError(
      `CONTROL_PLANE_PYTHON_API_BASE_URL must be http(s), got ${JSON.stringify(url.protocol)}`,
      "invalid_url_protocol",
    );
  }
  // Normalise: drop a trailing slash so we can concatenate request paths cleanly.
  return value.replace(/\/+$/, "");
}

function isLocalHttpWebhookHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function normalizeWebhookUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(
      `Notification webhook URL is not valid: ${JSON.stringify(value)}`,
      "invalid_notification_webhook_url",
    );
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new ConfigError(
      `Notification webhook URL must be http(s), got ${JSON.stringify(url.protocol)}`,
      "invalid_notification_webhook_protocol",
    );
  }
  if (url.protocol === "http:" && !isLocalHttpWebhookHost(url.hostname)) {
    throw new ConfigError(
      "Notification webhook URL may use http only for localhost targets",
      "insecure_notification_webhook_url",
    );
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new ConfigError(
      "Notification webhook URL must not include credentials, query strings, or fragments",
      "secret_bearing_notification_webhook_url",
    );
  }
  return url.toString();
}

function parseWebhookAllowlist(value: string | undefined): string[] {
  if (value === undefined || value.trim() === "") return [];
  const urls = value
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .map(normalizeWebhookUrl);
  return [...new Set(urls)].sort();
}

function validateDatabaseUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(
      "CONTROL_PLANE_DATABASE_URL is not a valid URL",
      "invalid_database_url",
    );
  }
  if (url.protocol !== "postgres:" && url.protocol !== "postgresql:") {
    throw new ConfigError(
      `CONTROL_PLANE_DATABASE_URL must be postgres(ql)://, got ${JSON.stringify(url.protocol)}`,
      "invalid_database_url_protocol",
    );
  }
  return value;
}

function validateConfigSemantics(config: ControlPlaneConfig): void {
  if (
    config.enableNotificationWebhookEgress &&
    config.notificationWebhookAllowlist.length === 0
  ) {
    throw new ConfigError(
      "CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST is required when notification webhook egress is enabled",
      "missing_notification_webhook_allowlist",
    );
  }
}

/**
 * Build a validated config from an environment map. Throws {@link ConfigError}
 * on any invalid value (fail-fast).
 */
export function loadConfig(env: RawEnv = process.env): ControlPlaneConfig {
  const host = env.CONTROL_PLANE_HOST?.trim() || "0.0.0.0";
  const port = parseIntStrict(env.CONTROL_PLANE_PORT, 8010, "CONTROL_PLANE_PORT");
  const pythonApiBaseUrl = validateBaseUrl(
    env.CONTROL_PLANE_PYTHON_API_BASE_URL?.trim() || "http://backend:8000",
  );
  const enablePythonFallbackProxy = parseBool(env.CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY, true);
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
  const runEventStreamPollIntervalMs = parseBoundedInt(
    env.CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS,
    1_000,
    "CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS",
    100,
    60_000,
  );
  const runEventStreamPageLimit = parseBoundedInt(
    env.CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT,
    100,
    "CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT",
    1,
    500,
  );
  const enableNotificationWebhookEgress = parseBool(
    env.CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS,
    false,
  );
  const notificationWebhookAllowlist = parseWebhookAllowlist(
    env.CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST,
  );
  const notificationMaxPayloadBytes = parseBoundedInt(
    env.CONTROL_PLANE_NOTIFICATION_MAX_PAYLOAD_BYTES,
    64 * 1024,
    "CONTROL_PLANE_NOTIFICATION_MAX_PAYLOAD_BYTES",
    1_024,
    1024 * 1024,
  );
  const rawDatabaseUrl = env.CONTROL_PLANE_DATABASE_URL?.trim();
  const databaseUrl = rawDatabaseUrl ? validateDatabaseUrl(rawDatabaseUrl) : null;
  const agentSpaceHome = resolve(env.AGENT_SPACE_HOME?.trim() || "/aspace");
  const cliToolsRoot = resolve(
    env.CONTROL_PLANE_CLI_TOOLS_ROOT?.trim() || resolve(agentSpaceHome, "runtime-tools"),
  );
  const workspaceRoot = resolve(
    env.WORKSPACE_ROOT?.trim() || resolve(agentSpaceHome, "workspaces"),
  );
  // Mirrors the Python `settings.sandbox_root` default (SANDBOX_ROOT or
  // AGENT_SPACE_HOME/sandboxes) so TS-provisioned ephemeral dirs and Python
  // worktrees share one sandbox root.
  const sandboxRoot = resolve(
    env.SANDBOX_ROOT?.trim() || resolve(agentSpaceHome, "sandboxes"),
  );
  const artifactStorageRoot = resolve(
    env.ARTIFACT_STORAGE_ROOT?.trim() || resolve(agentSpaceHome, "storage", "artifacts"),
  );
  const deployerSocketPath = resolve(
    env.DEPLOYER_SOCKET_PATH?.trim() || resolve(agentSpaceHome, "run", "deployer.sock"),
  );
  const internalToken = env.CONTROL_PLANE_INTERNAL_TOKEN?.trim() || null;
  const googleClientId = env.GOOGLE_CLIENT_ID?.trim() || "";
  const googleClientSecret = env.GOOGLE_CLIENT_SECRET?.trim() || "";
  const googleRedirectUri =
    env.GOOGLE_REDIRECT_URI?.trim() ||
    "http://localhost:5173/api/v1/auth/google/callback";
  const frontendUrl = validateBaseUrl(env.FRONTEND_URL?.trim() || "http://localhost:5173");
  const sessionExpireDays = parseIntStrict(
    env.SESSION_EXPIRE_DAYS,
    30,
    "SESSION_EXPIRE_DAYS",
  );
  const debug = parseBool(env.DEBUG, false);
  const dailyReportSchedulerEnabled = parseBool(
    env.CONTROL_PLANE_DAILY_REPORT_SCHEDULER_ENABLED,
    true,
  );
  const dailyReportSchedulerIntervalSeconds = parseBoundedInt(
    env.CONTROL_PLANE_DAILY_REPORT_SCHEDULER_INTERVAL_SECONDS,
    60,
    "CONTROL_PLANE_DAILY_REPORT_SCHEDULER_INTERVAL_SECONDS",
    30,
    86_400,
  );
  const automationSchedulerEnabled = parseBool(
    env.CONTROL_PLANE_AUTOMATION_SCHEDULER_ENABLED,
    true,
  );
  const automationSchedulerIntervalSeconds = parseBoundedInt(
    env.CONTROL_PLANE_AUTOMATION_SCHEDULER_INTERVAL_SECONDS,
    60,
    "CONTROL_PLANE_AUTOMATION_SCHEDULER_INTERVAL_SECONDS",
    30,
    86_400,
  );
  const memoryAccessLogRetentionEnabled = parseBool(
    env.CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_ENABLED,
    true,
  );
  const memoryAccessLogRetentionDays = parseBoundedInt(
    env.CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_DAYS,
    90,
    "CONTROL_PLANE_MEMORY_ACCESS_LOG_RETENTION_DAYS",
    1,
    3650,
  );
  const memoryAccessLogPruneIntervalSeconds = parseBoundedInt(
    env.CONTROL_PLANE_MEMORY_ACCESS_LOG_PRUNE_INTERVAL_SECONDS,
    3600,
    "CONTROL_PLANE_MEMORY_ACCESS_LOG_PRUNE_INTERVAL_SECONDS",
    300,
    86_400,
  );
  const intakeExtractionSchedulerEnabled = parseBool(
    env.CONTROL_PLANE_INTAKE_EXTRACTION_SCHEDULER_ENABLED,
    true,
  );
  const intakeExtractionSchedulerIntervalSeconds = parseBoundedInt(
    env.CONTROL_PLANE_INTAKE_EXTRACTION_SCHEDULER_INTERVAL_SECONDS,
    30,
    "CONTROL_PLANE_INTAKE_EXTRACTION_SCHEDULER_INTERVAL_SECONDS",
    5,
    3600,
  );
  const agentSpaceEnv = env.AGENT_SPACE_ENV?.trim() || "";
  const appVersion = env.APP_VERSION?.trim() || null;
  const backupEnabled = parseBool(env.BACKUP_ENABLED, false);
  const backupIntervalHours = parseBoundedInt(
    env.BACKUP_INTERVAL_HOURS,
    24,
    "BACKUP_INTERVAL_HOURS",
    1,
    168,
  );
  const backupRetentionCount = parseBoundedInt(
    env.BACKUP_RETENTION_COUNT,
    7,
    "BACKUP_RETENTION_COUNT",
    1,
    365,
  );
  const backupIncludeLogs = parseBool(env.BACKUP_INCLUDE_LOGS, false);
  const backupOnStartup = parseBool(env.BACKUP_ON_STARTUP, true);
  const backupRoot = resolve(
    env.BACKUP_ROOT?.trim() || resolve(agentSpaceHome, "backups"),
  );
  const backupAcceptNoBackup = parseBool(env.BACKUP_ACCEPT_NO_BACKUP, false);
  const backupDatabaseUrl = env.BACKUP_DATABASE_URL?.trim() || null;

  const config: ControlPlaneConfig = {
    host,
    port,
    pythonApiBaseUrl,
    enablePythonFallbackProxy,
    logLevel,
    requestTimeoutMs,
    catalogRoot,
    runEventStreamPollIntervalMs,
    runEventStreamPageLimit,
    enableNotificationWebhookEgress,
    notificationWebhookAllowlist,
    notificationMaxPayloadBytes,
    databaseUrl,
    agentSpaceHome,
    cliToolsRoot,
    workspaceRoot,
    sandboxRoot,
    artifactStorageRoot,
    deployerSocketPath,
    internalToken,
    googleClientId,
    googleClientSecret,
    googleRedirectUri,
    frontendUrl,
    sessionExpireDays,
    debug,
    dailyReportSchedulerEnabled,
    dailyReportSchedulerIntervalSeconds,
    automationSchedulerEnabled,
    automationSchedulerIntervalSeconds,
    memoryAccessLogRetentionEnabled,
    memoryAccessLogRetentionDays,
    memoryAccessLogPruneIntervalSeconds,
    intakeExtractionSchedulerEnabled,
    intakeExtractionSchedulerIntervalSeconds,
    agentSpaceEnv,
    appVersion,
    backupEnabled,
    backupIntervalHours,
    backupRetentionCount,
    backupIncludeLogs,
    backupOnStartup,
    backupRoot,
    backupAcceptNoBackup,
    backupDatabaseUrl,
  };
  validateConfigSemantics(config);
  return config;
}

/** A one-line, secret-free description of the effective config for startup logs. */
export function describeConfig(config: ControlPlaneConfig): string {
  return [
    `host=${config.host}`,
    `port=${config.port}`,
    `pythonApiBaseUrl=${config.pythonApiBaseUrl}`,
    `pythonFallbackProxy=${config.enablePythonFallbackProxy}`,
    `logLevel=${config.logLevel}`,
    `requestTimeoutMs=${config.requestTimeoutMs}`,
    `catalogRoot=${config.catalogRoot}`,
    `runEventStreamPollIntervalMs=${config.runEventStreamPollIntervalMs}`,
    `runEventStreamPageLimit=${config.runEventStreamPageLimit}`,
    `notificationWebhookEgress=${config.enableNotificationWebhookEgress}`,
    `notificationWebhookAllowlistCount=${config.notificationWebhookAllowlist.length}`,
    `notificationMaxPayloadBytes=${config.notificationMaxPayloadBytes}`,
    `agentSpaceHome=${config.agentSpaceHome}`,
    `cliToolsRoot=${config.cliToolsRoot}`,
    `workspaceRoot=${config.workspaceRoot}`,
    `sandboxRoot=${config.sandboxRoot}`,
    `artifactStorageRoot=${config.artifactStorageRoot}`,
    `deployerSocketPath=${config.deployerSocketPath}`,
    `internalTokenConfigured=${config.internalToken !== null}`,
    `googleOAuthConfigured=${Boolean(config.googleClientId && config.googleClientSecret)}`,
    `frontendUrl=${config.frontendUrl}`,
    `sessionExpireDays=${config.sessionExpireDays}`,
    `debug=${config.debug}`,
    // The connection string may embed a password — never print it.
    `databaseUrlConfigured=${config.databaseUrl !== null}`,
    `backupDatabaseUrlConfigured=${config.backupDatabaseUrl !== null}`,
  ].join(" ");
}

// ---------------------------------------------------------------------------
// Immutable config snapshot
// ---------------------------------------------------------------------------

/** Bumped when the shape of {@link ControlPlaneConfig} changes incompatibly. */
export const CONFIG_SCHEMA_VERSION = 17 as const;

/**
 * An immutable, hash-identified view of the validated config. Built once at
 * startup and handed to every TS-owned module via `ModuleContext`. The hash is
 * deterministic over the config content (it excludes `loaded_at`), so two
 * snapshots of the same config always agree.
 */
export interface ConfigSnapshot {
  schema_version: typeof CONFIG_SCHEMA_VERSION;
  /** SHA-256 hex of the canonical (key-sorted) config JSON with secrets redacted. */
  content_hash: string;
  /** ISO-8601 timestamp of when this snapshot was created. */
  loaded_at: string;
  config: Readonly<ControlPlaneConfig>;
}

function canonicalConfigJson(config: ControlPlaneConfig): string {
  const record = config as unknown as Record<string, unknown>;
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) {
    sorted[key] =
      key === "internalToken" || key === "googleClientSecret" || key === "backupDatabaseUrl"
        ? "<redacted>"
        : record[key];
  }
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
export function collectConfigDiagnostics(
  env: RawEnv = process.env,
  config?: ControlPlaneConfig,
): ConfigDiagnostic[] {
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
  if (config) {
    if (
      config.notificationWebhookAllowlist.length > 0 &&
      !config.enableNotificationWebhookEgress
    ) {
      diagnostics.push({
        severity: "info",
        code: "notification_webhook_allowlist_inactive",
        message:
          "Notification webhook allowlist is configured but egress is disabled",
      });
    }
    if (config.requestTimeoutMs <= config.runEventStreamPollIntervalMs) {
      diagnostics.push({
        severity: "warning",
        code: "stream_poll_interval_exceeds_timeout",
        message:
          "Run-event stream poll interval is greater than or equal to the Python request timeout",
      });
    }
    diagnostics.push({
      severity: "info",
      code: "proposals_ts_authority",
      message:
        "Proposal review and supported proposal apply routes are served by the fixed TS authority",
    });
    diagnostics.push({
      severity: "info",
      code: "chat_turn_ts_authority",
      message:
        "Personal Assistant chat turns are served by the fixed TS authority",
    });
    diagnostics.push({
      severity: "info",
      code: "context_assembly_ts_authority",
      message:
        "Chat-path and full-run context assembly are served by the fixed TS authority",
    });
    diagnostics.push({
      severity: "info",
      code: "memory_ts_authority",
      message:
        "Memory read routes, public memory proposal creation, and supported active-memory apply are served by the fixed TS authority",
    });
  }
  return diagnostics;
}
