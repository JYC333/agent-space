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
   * Authority switch for provider read routes (list/detail/catalog). `python`
   * forwards to the Python authority; `ts` serves them from the control plane's
   * DB read port behind Python identity introspection.
   */
  providersAuthority: "python" | "ts";
  /**
   * Authority switch for provider commands plus the whole credential channel.
   * `python` leaves those routes unclaimed so the Python fallback proxy remains
   * authoritative. `ts` registers TS handlers for provider commands, provider
   * invocation, CLI credential routes, and internal credential-release ports.
   */
  providersCredentialsAuthority: "python" | "ts";
  /**
   * Authority switch for run execution/cancel commands. `python` leaves command
   * routes to the fallback proxy; `ts` registers TS-owned command handlers while
   * run read models remain Python-owned until separately migrated.
   */
  runsAuthority: "python" | "ts";
  /**
   * Authority switch for the policy enforcement context. `python` leaves
   * enforcement to the Python `PolicyGateway`; `ts` registers the
   * internal policy enforce/proposal-apply ports in the control plane and writes
   * durable audit to `policy_decision_records`. Independent of the other
   * authority switches; local env templates opt into `ts`.
   */
  policyAuthority: "python" | "ts";
  /**
   * Authority switch for public proposal review/read routes. `python` leaves
   * them to the fallback proxy; `ts` registers TS read/list handlers and uses
   * the internal Python proposal port for apply/reject/egress transactions
   * until per-type appliers are split out.
   */
  proposalsAuthority: "python" | "ts";
  /**
   * Authority switch for the public `sessions` command surface. `python` leaves
   * list/get/create sessions and list/add messages to the fallback proxy; `ts`
   * serves those commands from the control-plane DB behind Python identity
   * introspection. Session `reflect` remains Python-owned.
   */
  sessionsAuthority: "python" | "ts";
  /**
   * Authority switch for the synchronous Personal Assistant chat turn.
   * `python` leaves `/api/v1/agents/:id/chat` to the fallback proxy; `ts`
   * registers a TS-owned outer orchestrator while still using explicit Python
   * ports for context/run preparation until those slices move.
   */
  chatTurnAuthority: "python" | "ts";
  /**
   * Authority switch for chat-path context assembly (Stage 6 slice 4). `python`
   * leaves `ChatContextBuilder` (selection + `context_snapshots` /
   * `context_snapshot_items` persistence) to the Python chat-turn preparation
   * port; `ts` makes the TS chat turn own the budget/dedup loop and snapshot
   * persistence, sourcing per-source candidates and run creation through narrow
   * Python read/run-create ports. Requires `chatTurnAuthority` and
   * `sessionsAuthority` to be `ts`.
   */
  contextAuthority: "python" | "ts";
  /**
   * Authority switch for the `memory` context (Stage 6, progressive). `ts` makes
   * the control plane own the memory read model (`/memory` list/get/search) and
   * public memory proposal creation (`POST`/`PATCH`/`DELETE /memory`). Proposal
   * creation writes pending `proposals` rows only; active memory mutation remains
   * proposal-apply authority. Requires the TS policy/proposals authority, DB URL,
   * and internal token.
   */
  memoryAuthority: "python" | "ts";
  /**
   * Authority switch for **memory proposal apply** (Stage 6 slice 7b). `ts` makes
   * the control plane apply accepted `memory_create`/`memory_update`/
   * `memory_archive` proposals itself: the accept route gates the proposal through
   * the Python read-only memory-apply-gate port, then runs `acceptAndApply`
   * (active-memory INSERT/UPDATE + provenance + relations + accept state) in one
   * TS transaction. Run/grant egress-context and workspace/agent-scope proposals
   * fail closed (409, still Python-owned). Requires `memoryAuthority=ts`,
   * the TS policy/proposals authority, DB URL, and internal token. `python`
   * leaves all proposal apply to the Python accept port.
   */
  memoryApplyAuthority: "python" | "ts";
  /**
   * Read-only shadow compare. While Python serves, the TS DB-backed result is
   * computed and divergences are logged. Never affects responses.
   */
  providersShadowCompare: boolean;
  /**
   * PostgreSQL connection string for provider reads and provider/credential
   * commands. Python/Alembic remains the schema owner.
   */
  databaseUrl: string | null;
  /** Instance root used for provider key material and CLI credential profiles. */
  agentSpaceHome: string;
  /** Instance-owned runtime CLI installation root. */
  cliToolsRoot: string;
  /** Root for short-lived run sandboxes (worktrees, ephemeral working dirs). */
  sandboxRoot: string;
  /** Service-to-service token for internal providers/credentials ports. */
  internalToken: string | null;
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
  "CONTROL_PLANE_PROVIDERS_AUTHORITY",
  "CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY",
  "CONTROL_PLANE_RUNS_AUTHORITY",
  "CONTROL_PLANE_POLICY_AUTHORITY",
  "CONTROL_PLANE_PROPOSALS_AUTHORITY",
  "CONTROL_PLANE_SESSIONS_AUTHORITY",
  "CONTROL_PLANE_CHAT_TURN_AUTHORITY",
  "CONTROL_PLANE_CONTEXT_AUTHORITY",
  "CONTROL_PLANE_MEMORY_AUTHORITY",
  "CONTROL_PLANE_MEMORY_APPLY_AUTHORITY",
  "CONTROL_PLANE_PROVIDERS_SHADOW",
  "CONTROL_PLANE_DATABASE_URL",
  "AGENT_SPACE_HOME",
  "CONTROL_PLANE_CLI_TOOLS_ROOT",
  "SANDBOX_ROOT",
  "CONTROL_PLANE_INTERNAL_TOKEN",
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

function parseProvidersAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_PROVIDERS_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_providers_authority",
  );
}

function parseProvidersCredentialsAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_providers_credentials_authority",
  );
}

function parseRunsAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_RUNS_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_runs_authority",
  );
}

function parsePolicyAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_POLICY_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_policy_authority",
  );
}

function parseProposalsAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_PROPOSALS_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_proposals_authority",
  );
}

function parseSessionsAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_SESSIONS_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_sessions_authority",
  );
}

function parseMemoryAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_MEMORY_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_memory_authority",
  );
}

function parseMemoryApplyAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_MEMORY_APPLY_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_memory_apply_authority",
  );
}

function parseChatTurnAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_CHAT_TURN_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_chat_turn_authority",
  );
}

function parseContextAuthority(value: string | undefined): "python" | "ts" {
  const v = (value?.trim() || "python").toLowerCase();
  if (v === "python" || v === "ts") return v;
  throw new ConfigError(
    `CONTROL_PLANE_CONTEXT_AUTHORITY must be "python" or "ts", got ${JSON.stringify(value)}`,
    "invalid_context_authority",
  );
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
  if (
    (config.providersShadowCompare || config.providersAuthority === "ts") &&
    !config.databaseUrl
  ) {
    throw new ConfigError(
      "CONTROL_PLANE_DATABASE_URL is required when providers shadow compare or TS read authority is enabled",
      "missing_database_url_for_providers",
    );
  }
  if (config.providersCredentialsAuthority === "ts") {
    if (config.providersAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_PROVIDERS_AUTHORITY must be ts before providers/credentials authority can be ts",
        "providers_credentials_requires_provider_read_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when providers/credentials TS authority is enabled",
        "missing_database_url_for_providers_credentials",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when providers/credentials TS authority is enabled",
        "missing_internal_token_for_providers_credentials",
      );
    }
  }
  if (config.runsAuthority === "ts") {
    if (config.providersCredentialsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY must be ts before runs authority can be ts",
        "runs_requires_providers_credentials_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when runs TS authority is enabled",
        "missing_database_url_for_runs",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when runs TS authority is enabled",
        "missing_internal_token_for_runs",
      );
    }
  }
  if (config.policyAuthority === "ts") {
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when policy TS authority is enabled",
        "missing_database_url_for_policy",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when policy TS authority is enabled",
        "missing_internal_token_for_policy",
      );
    }
  }
  if (config.proposalsAuthority === "ts") {
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when proposals TS authority is enabled",
        "missing_database_url_for_proposals",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when proposals TS authority is enabled",
        "missing_internal_token_for_proposals",
      );
    }
  }
  if (config.sessionsAuthority === "ts") {
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when sessions TS authority is enabled",
        "missing_database_url_for_sessions",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when sessions TS authority is enabled",
        "missing_internal_token_for_sessions",
      );
    }
  }
  if (config.chatTurnAuthority === "ts") {
    if (config.sessionsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_SESSIONS_AUTHORITY must be ts before chat-turn authority can be ts",
        "chat_turn_requires_sessions_authority",
      );
    }
    if (config.runsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_RUNS_AUTHORITY must be ts before chat-turn authority can be ts",
        "chat_turn_requires_runs_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when chat-turn TS authority is enabled",
        "missing_database_url_for_chat_turn",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when chat-turn TS authority is enabled",
        "missing_internal_token_for_chat_turn",
      );
    }
  }
  if (config.contextAuthority === "ts") {
    if (config.chatTurnAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_CHAT_TURN_AUTHORITY must be ts before context authority can be ts",
        "context_requires_chat_turn_authority",
      );
    }
    if (config.sessionsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_SESSIONS_AUTHORITY must be ts before context authority can be ts",
        "context_requires_sessions_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when context TS authority is enabled",
        "missing_database_url_for_context",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when context TS authority is enabled",
        "missing_internal_token_for_context",
      );
    }
  }
  if (config.memoryAuthority === "ts") {
    // Stage 6 slices 5-6: TS owns memory reads and proposal-only public memory
    // writes. Later memory slices extend this switch to proposal apply/quality.
    if (config.policyAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_POLICY_AUTHORITY must be ts before memory authority can be ts",
        "memory_requires_policy_authority",
      );
    }
    if (config.proposalsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_PROPOSALS_AUTHORITY must be ts before memory authority can be ts",
        "memory_requires_proposals_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when memory TS authority is enabled",
        "missing_database_url_for_memory",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when memory TS authority is enabled",
        "missing_internal_token_for_memory",
      );
    }
  }
  if (config.memoryApplyAuthority === "ts") {
    // Stage 6 slice 7b: TS applies accepted memory proposals. Requires the memory
    // read/proposal authority (so the same DB role + ports are in place) plus the
    // policy/proposals authority for the apply gate, the DB URL, and the internal
    // token for the Python memory-apply-gate port.
    if (config.memoryAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_MEMORY_AUTHORITY must be ts before memory apply authority can be ts",
        "memory_apply_requires_memory_authority",
      );
    }
    if (config.policyAuthority !== "ts" || config.proposalsAuthority !== "ts") {
      throw new ConfigError(
        "CONTROL_PLANE_POLICY_AUTHORITY and CONTROL_PLANE_PROPOSALS_AUTHORITY must be ts before memory apply authority can be ts",
        "memory_apply_requires_policy_and_proposals_authority",
      );
    }
    if (!config.databaseUrl) {
      throw new ConfigError(
        "CONTROL_PLANE_DATABASE_URL is required when memory apply TS authority is enabled",
        "missing_database_url_for_memory_apply",
      );
    }
    if (!config.internalToken) {
      throw new ConfigError(
        "CONTROL_PLANE_INTERNAL_TOKEN is required when memory apply TS authority is enabled",
        "missing_internal_token_for_memory_apply",
      );
    }
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
  const providersAuthority = parseProvidersAuthority(
    env.CONTROL_PLANE_PROVIDERS_AUTHORITY,
  );
  const providersCredentialsAuthority = parseProvidersCredentialsAuthority(
    env.CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY,
  );
  const runsAuthority = parseRunsAuthority(env.CONTROL_PLANE_RUNS_AUTHORITY);
  const policyAuthority = parsePolicyAuthority(env.CONTROL_PLANE_POLICY_AUTHORITY);
  const proposalsAuthority = parseProposalsAuthority(env.CONTROL_PLANE_PROPOSALS_AUTHORITY);
  const sessionsAuthority = parseSessionsAuthority(env.CONTROL_PLANE_SESSIONS_AUTHORITY);
  const chatTurnAuthority = parseChatTurnAuthority(env.CONTROL_PLANE_CHAT_TURN_AUTHORITY);
  const contextAuthority = parseContextAuthority(env.CONTROL_PLANE_CONTEXT_AUTHORITY);
  const memoryAuthority = parseMemoryAuthority(env.CONTROL_PLANE_MEMORY_AUTHORITY);
  const memoryApplyAuthority = parseMemoryApplyAuthority(env.CONTROL_PLANE_MEMORY_APPLY_AUTHORITY);
  const providersShadowCompare = parseBool(env.CONTROL_PLANE_PROVIDERS_SHADOW, false);
  const rawDatabaseUrl = env.CONTROL_PLANE_DATABASE_URL?.trim();
  const databaseUrl = rawDatabaseUrl ? validateDatabaseUrl(rawDatabaseUrl) : null;
  const agentSpaceHome = resolve(env.AGENT_SPACE_HOME?.trim() || "/aspace");
  const cliToolsRoot = resolve(
    env.CONTROL_PLANE_CLI_TOOLS_ROOT?.trim() || resolve(agentSpaceHome, "runtime-tools"),
  );
  // Mirrors the Python `settings.sandbox_root` default (SANDBOX_ROOT or
  // AGENT_SPACE_HOME/sandboxes) so TS-provisioned ephemeral dirs and Python
  // worktrees share one sandbox root.
  const sandboxRoot = resolve(
    env.SANDBOX_ROOT?.trim() || resolve(agentSpaceHome, "sandboxes"),
  );
  const internalToken = env.CONTROL_PLANE_INTERNAL_TOKEN?.trim() || null;

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
    providersAuthority,
    providersCredentialsAuthority,
    runsAuthority,
    policyAuthority,
    proposalsAuthority,
    sessionsAuthority,
    chatTurnAuthority,
    contextAuthority,
    memoryAuthority,
    memoryApplyAuthority,
    providersShadowCompare,
    databaseUrl,
    agentSpaceHome,
    cliToolsRoot,
    sandboxRoot,
    internalToken,
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
    `providersAuthority=${config.providersAuthority}`,
    `providersCredentialsAuthority=${config.providersCredentialsAuthority}`,
    `runsAuthority=${config.runsAuthority}`,
    `policyAuthority=${config.policyAuthority}`,
    `proposalsAuthority=${config.proposalsAuthority}`,
    `sessionsAuthority=${config.sessionsAuthority}`,
    `chatTurnAuthority=${config.chatTurnAuthority}`,
    `contextAuthority=${config.contextAuthority}`,
    `memoryAuthority=${config.memoryAuthority}`,
    `memoryApplyAuthority=${config.memoryApplyAuthority}`,
    `providersShadowCompare=${config.providersShadowCompare}`,
    `agentSpaceHome=${config.agentSpaceHome}`,
    `cliToolsRoot=${config.cliToolsRoot}`,
    `sandboxRoot=${config.sandboxRoot}`,
    `internalTokenConfigured=${config.internalToken !== null}`,
    // The connection string may embed a password — never print it.
    `databaseUrlConfigured=${config.databaseUrl !== null}`,
  ].join(" ");
}

// ---------------------------------------------------------------------------
// Immutable config snapshot
// ---------------------------------------------------------------------------

/** Bumped when the shape of {@link ControlPlaneConfig} changes incompatibly. */
export const CONFIG_SCHEMA_VERSION = 8 as const;

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
  for (const key of Object.keys(record).sort()) {
    sorted[key] = key === "internalToken" ? "<redacted>" : record[key];
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
    if (
      config.databaseUrl !== null &&
      !config.providersShadowCompare &&
      config.providersAuthority === "python" &&
      config.providersCredentialsAuthority === "python" &&
      config.runsAuthority === "python" &&
      config.policyAuthority === "python" &&
      config.proposalsAuthority === "python" &&
      config.sessionsAuthority === "python" &&
      config.chatTurnAuthority === "python" &&
      config.memoryAuthority === "python" &&
      config.memoryApplyAuthority === "python"
    ) {
      diagnostics.push({
        severity: "info",
        code: "database_url_inactive",
        message:
          "CONTROL_PLANE_DATABASE_URL is configured but neither providers shadow compare nor TS read authority is enabled",
      });
    }
    if (config.providersAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "providers_read_authority_ts",
        message:
          "Provider read routes are served by the TS authority; confirm the ownership decision is recorded before using this in a shared stack",
      });
    }
    if (config.providersCredentialsAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "providers_credentials_authority_ts",
        message:
          "Provider commands and credential routes are served by the TS authority; confirm the ownership decision is recorded before using this in a shared stack",
      });
    }
    if (config.runsAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "runs_authority_ts",
        message:
          "Run execution commands are served by the TS authority; run read models still use Python unless separately routed",
      });
    }
    if (config.policyAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "policy_authority_ts",
        message:
          "Policy enforcement ports are served by the TS authority; confirm the ownership decision is recorded before using this in a shared stack",
      });
    }
    if (config.proposalsAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "proposals_authority_ts",
        message:
          "Proposal review routes are served by the TS authority; proposal apply still dispatches through the internal Python proposal port",
      });
    }
    if (config.sessionsAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "sessions_authority_ts",
        message:
          "Public session routes (list/get/create sessions, list/add messages) and session_summary.get_latest are served by the TS authority; session reflect and summary condense remain Python-owned",
      });
    }
    if (config.chatTurnAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "chat_turn_authority_ts",
        message:
          "Personal Assistant chat turns are served by the TS authority; context/run preparation still dispatches through the internal Python chat port",
      });
    }
    if (config.memoryAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "memory_authority_ts",
        message:
          "Memory read routes and public memory proposal creation are served by the TS authority; active-memory apply remains proposal-gated",
      });
    }
    if (config.memoryApplyAuthority === "ts") {
      diagnostics.push({
        severity: "info",
        code: "memory_apply_authority_ts",
        message:
          "Accepted memory proposals are applied by the TS authority (gated through the Python memory-apply-gate port); run/grant-egress and workspace/agent-scope proposals fail closed to Python",
      });
    }
  }
  return diagnostics;
}
