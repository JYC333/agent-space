import { describe, it, expect } from "vitest";
import {
  collectConfigDiagnostics,
  ConfigError,
  createConfigSnapshot,
  describeConfig,
  loadConfig,
  loadConfigSnapshot,
} from "../src/config";

describe("loadConfig", () => {
  it("applies documented defaults from an empty env", () => {
    const c = loadConfig({});
    expect(c.host).toBe("0.0.0.0");
    expect(c.port).toBe(8010);
    expect(c.pythonApiBaseUrl).toBe("http://backend:8000");
    expect(c.enablePythonFallbackProxy).toBe(true);
    expect(c.logLevel).toBe("info");
    expect(c.requestTimeoutMs).toBe(300000);
    expect(c.runEventStreamPollIntervalMs).toBe(1000);
    expect(c.runEventStreamPageLimit).toBe(100);
    expect(c.enableNotificationWebhookEgress).toBe(false);
    expect(c.notificationWebhookAllowlist).toEqual([]);
    expect(c.notificationMaxPayloadBytes).toBe(65536);
    expect(c.backupDatabaseUrl).toBeNull();
    expect(c.agentSpaceHome).toBe("/aspace");
    expect(c.cliToolsRoot).toBe("/aspace/runtime-tools");
    expect(c.workspaceRoot).toBe("/aspace/workspaces");
    expect(c.artifactStorageRoot).toBe("/aspace/storage/artifacts");
    expect(c.deployerSocketPath).toBe("/aspace/run/deployer.sock");
    expect(c.internalToken).toBeNull();
    expect(c.googleClientId).toBe("");
    expect(c.googleClientSecret).toBe("");
    expect(c.googleRedirectUri).toBe("http://localhost:5173/api/v1/auth/google/callback");
    expect(c.frontendUrl).toBe("http://localhost:5173");
    expect(c.sessionExpireDays).toBe(30);
    expect(c.debug).toBe(false);
  });

  it("honors CONTROL_PLANE_* overrides and normalizes a trailing slash", () => {
    const c = loadConfig({
      CONTROL_PLANE_HOST: "127.0.0.1",
      CONTROL_PLANE_PORT: "9100",
      CONTROL_PLANE_PYTHON_API_BASE_URL: "http://backend:8000/",
      CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false",
      CONTROL_PLANE_LOG_LEVEL: "debug",
      CONTROL_PLANE_REQUEST_TIMEOUT_MS: "1000",
      CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS: "250",
      CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT: "25",
      CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true",
      CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST: "https://hooks.example.com/proposal",
      CONTROL_PLANE_NOTIFICATION_MAX_PAYLOAD_BYTES: "4096",
      CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      BACKUP_DATABASE_URL: "postgresql://backup:secret@db:5432/agent_space",
      CONTROL_PLANE_INTERNAL_TOKEN: "service-token",
      GOOGLE_CLIENT_ID: "google-client",
      GOOGLE_CLIENT_SECRET: "google-secret",
      GOOGLE_REDIRECT_URI: "http://localhost:8010/api/v1/auth/google/callback",
      FRONTEND_URL: "http://localhost:5173/",
      SESSION_EXPIRE_DAYS: "7",
      DEBUG: "true",
      AGENT_SPACE_HOME: "/tmp/aspace",
      CONTROL_PLANE_CLI_TOOLS_ROOT: "/tmp/aspace/tools",
      WORKSPACE_ROOT: "/tmp/aspace/workspaces-root",
      ARTIFACT_STORAGE_ROOT: "/tmp/aspace/artifacts-root",
      DEPLOYER_SOCKET_PATH: "/tmp/aspace/run/deployer.sock",
    });
    expect(c.host).toBe("127.0.0.1");
    expect(c.port).toBe(9100);
    expect(c.pythonApiBaseUrl).toBe("http://backend:8000");
    expect(c.enablePythonFallbackProxy).toBe(false);
    expect(c.logLevel).toBe("debug");
    expect(c.requestTimeoutMs).toBe(1000);
    expect(c.runEventStreamPollIntervalMs).toBe(250);
    expect(c.runEventStreamPageLimit).toBe(25);
    expect(c.enableNotificationWebhookEgress).toBe(true);
    expect(c.notificationWebhookAllowlist).toEqual([
      "https://hooks.example.com/proposal",
    ]);
    expect(c.notificationMaxPayloadBytes).toBe(4096);
    expect(c.databaseUrl).toBe("postgresql://cp@db:5432/agent_space");
    expect(c.backupDatabaseUrl).toBe("postgresql://backup:secret@db:5432/agent_space");
    expect(c.internalToken).toBe("service-token");
    expect(c.googleClientId).toBe("google-client");
    expect(c.googleClientSecret).toBe("google-secret");
    expect(c.googleRedirectUri).toBe("http://localhost:8010/api/v1/auth/google/callback");
    expect(c.frontendUrl).toBe("http://localhost:5173");
    expect(c.sessionExpireDays).toBe(7);
    expect(c.debug).toBe(true);
    expect(c.agentSpaceHome).toBe("/tmp/aspace");
    expect(c.cliToolsRoot).toBe("/tmp/aspace/tools");
    expect(c.workspaceRoot).toBe("/tmp/aspace/workspaces-root");
    expect(c.artifactStorageRoot).toBe("/tmp/aspace/artifacts-root");
    expect(c.deployerSocketPath).toBe("/tmp/aspace/run/deployer.sock");
  });

  it("fails fast on a malformed CONTROL_PLANE_PYTHON_API_BASE_URL", () => {
    expect(() => loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: "not a url" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: "ftp://x:1" })).toThrow(ConfigError);
  });

  it("rejects invalid port, boolean and log level", () => {
    expect(() => loadConfig({ CONTROL_PLANE_PORT: "0" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_PORT: "abc" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "maybe" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_LOG_LEVEL: "loud" })).toThrow(ConfigError);
    expect(() =>
      loadConfig({ CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS: "50" }),
    ).toThrow(ConfigError);
    expect(() =>
      loadConfig({ CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT: "999" }),
    ).toThrow(ConfigError);
    expect(() =>
      loadConfig({ CONTROL_PLANE_NOTIFICATION_MAX_PAYLOAD_BYTES: "64" }),
    ).toThrow(ConfigError);
  });

  it("validates notification webhook egress semantics", () => {
    expect(() =>
      loadConfig({ CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true" }),
    ).toThrow(ConfigError);
    expect(() =>
      loadConfig({
        CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST:
          "https://user:pass@hooks.example.com/proposal",
      }),
    ).toThrow(ConfigError);
    expect(() =>
      loadConfig({
        CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST:
          "http://hooks.example.com/proposal",
      }),
    ).toThrow(ConfigError);
    expect(
      loadConfig({
        CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true",
        CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST:
          "http://127.0.0.1:9123/proposal",
      }).notificationWebhookAllowlist,
    ).toEqual(["http://127.0.0.1:9123/proposal"]);
  });

  it("describeConfig is a single line with no secret-bearing fields", () => {
    const line = describeConfig(loadConfig({}));
    expect(line).toContain("port=8010");
    expect(line).toContain("internalTokenConfigured=false");
    expect(line).toContain("googleOAuthConfigured=false");
    expect(line).not.toMatch(/authorization|cookie|password|secret/i);
    expect(describeConfig(loadConfig({ CONTROL_PLANE_INTERNAL_TOKEN: "secret-token" }))).not
      .toContain("secret-token");
    expect(describeConfig(loadConfig({ GOOGLE_CLIENT_SECRET: "google-secret" }))).not
      .toContain("google-secret");
    expect(describeConfig(loadConfig({ BACKUP_DATABASE_URL: "postgresql://backup:secret@db/app" }))).not
      .toContain("secret");
  });

  it("carries a machine code on every validation failure", () => {
    const codeOf = (env: Record<string, string>): string => {
      try {
        loadConfig(env);
      } catch (err) {
        if (err instanceof ConfigError) return err.code;
        throw err;
      }
      throw new Error("expected ConfigError");
    };
    expect(codeOf({ CONTROL_PLANE_PORT: "abc" })).toBe("invalid_positive_integer");
    expect(codeOf({ CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "maybe" })).toBe("invalid_boolean");
    expect(codeOf({ CONTROL_PLANE_PYTHON_API_BASE_URL: "not a url" })).toBe("invalid_base_url");
    expect(codeOf({ CONTROL_PLANE_PYTHON_API_BASE_URL: "ftp://x:1" })).toBe("invalid_url_protocol");
    expect(codeOf({ CONTROL_PLANE_LOG_LEVEL: "loud" })).toBe("invalid_log_level");
    expect(codeOf({ CONTROL_PLANE_RUN_EVENT_STREAM_PAGE_LIMIT: "999" })).toBe(
      "invalid_bounded_integer",
    );
    expect(
      codeOf({ CONTROL_PLANE_ENABLE_NOTIFICATION_WEBHOOK_EGRESS: "true" }),
    ).toBe("missing_notification_webhook_allowlist");
  });
});

describe("config snapshot", () => {
  it("is immutable and identifies the config by schema version + content hash", () => {
    const snapshot = loadConfigSnapshot({});
    expect(snapshot.schema_version).toBe(17);
    expect(snapshot.content_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(snapshot.loaded_at).toBeTruthy();
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.config)).toBe(true);
    expect(() => {
      (snapshot.config as { port: number }).port = 1;
    }).toThrow();
  });

  it("hashes deterministically over content (not load time) and changes with the config", () => {
    const a = createConfigSnapshot(loadConfig({}));
    const b = createConfigSnapshot(loadConfig({}));
    expect(a.content_hash).toBe(b.content_hash);
    const c = createConfigSnapshot(loadConfig({ CONTROL_PLANE_PORT: "9100" }));
    expect(c.content_hash).not.toBe(a.content_hash);
  });
});

describe("config diagnostics", () => {
  it("flags unrecognized CONTROL_PLANE_* variables as warnings with a machine code", () => {
    const diagnostics = collectConfigDiagnostics({
      CONTROL_PLANE_PROT: "8010", // typo of PORT
      CONTROL_PLANE_LOG_LEVEL: "info", // known — not flagged
      CONTROL_PLANE_MEMORY_APPLY_AUTHORITY: "python", // retired — flagged
      CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts", // retired — flagged
      CONTROL_PLANE_CONTEXT_AUTHORITY: "ts", // retired — flagged
      CONTROL_PLANE_MEMORY_AUTHORITY: "ts", // retired — flagged
      CONTROL_PLANE_PROPOSALS_AUTHORITY: "ts", // retired — flagged
      CONTROL_PLANE_RUNS_AUTHORITY: "ts", // retired — flagged
      UNRELATED_VAR: "x", // outside the namespace — not flagged
    });
    expect(diagnostics).toEqual([
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_CHAT_TURN_AUTHORITY (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_CONTEXT_AUTHORITY (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_MEMORY_APPLY_AUTHORITY (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_MEMORY_AUTHORITY (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_PROPOSALS_AUTHORITY (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_PROT (ignored)",
      },
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_RUNS_AUTHORITY (ignored)",
      },
    ]);
  });

  it("returns no diagnostics for a fully-known environment", () => {
    expect(collectConfigDiagnostics({ CONTROL_PLANE_PORT: "8010" })).toEqual([]);
  });

  it("adds semantic diagnostics for control-plane-owned config relationships", () => {
    const config = loadConfig({
      CONTROL_PLANE_REQUEST_TIMEOUT_MS: "1000",
      CONTROL_PLANE_RUN_EVENT_STREAM_POLL_INTERVAL_MS: "1000",
      CONTROL_PLANE_NOTIFICATION_WEBHOOK_ALLOWLIST:
        "https://hooks.example.com/proposal",
    });
    const diagnostics = collectConfigDiagnostics({}, config);
    expect(diagnostics).toContainEqual({
      severity: "info",
      code: "notification_webhook_allowlist_inactive",
      message: "Notification webhook allowlist is configured but egress is disabled",
    });
    expect(diagnostics).toContainEqual({
      severity: "warning",
      code: "stream_poll_interval_exceeds_timeout",
      message:
        "Run-event stream poll interval is greater than or equal to the Python request timeout",
    });
  });

  it("describes fixed TS authorities in diagnostics", () => {
    const config = loadConfig({});

    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "chat_turn_ts_authority",
      message: "Personal Assistant chat turns are served by the fixed TS authority",
    });
    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "context_assembly_ts_authority",
      message:
        "Chat-path and full-run context assembly are served by the fixed TS authority",
    });
    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "memory_ts_authority",
      message:
        "Memory read routes, public memory proposal creation, and supported active-memory apply are served by the fixed TS authority",
    });
    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "proposals_ts_authority",
      message:
        "Proposal review and supported proposal apply routes are served by the fixed TS authority",
    });
  });
});
