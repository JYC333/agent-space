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
    expect(c.providersAuthority).toBe("python");
    expect(c.providersCredentialsAuthority).toBe("python");
    expect(c.runsAuthority).toBe("python");
    expect(c.policyAuthority).toBe("python");
    expect(c.proposalsAuthority).toBe("python");
    expect(c.sessionsAuthority).toBe("python");
    expect(c.chatTurnAuthority).toBe("python");
    expect(c.contextAuthority).toBe("python");
    expect(c.memoryAuthority).toBe("python");
    expect(c.memoryApplyAuthority).toBe("python");
    expect(c.agentSpaceHome).toBe("/aspace");
    expect(c.cliToolsRoot).toBe("/aspace/runtime-tools");
    expect(c.internalToken).toBeNull();
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
      CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
      CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
      CONTROL_PLANE_RUNS_AUTHORITY: "ts",
      CONTROL_PLANE_POLICY_AUTHORITY: "ts",
      CONTROL_PLANE_PROPOSALS_AUTHORITY: "ts",
      CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
      CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
      CONTROL_PLANE_CONTEXT_AUTHORITY: "ts",
      CONTROL_PLANE_MEMORY_AUTHORITY: "ts",
      CONTROL_PLANE_MEMORY_APPLY_AUTHORITY: "ts",
      CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      CONTROL_PLANE_INTERNAL_TOKEN: "service-token",
      AGENT_SPACE_HOME: "/tmp/aspace",
      CONTROL_PLANE_CLI_TOOLS_ROOT: "/tmp/aspace/tools",
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
    expect(c.providersAuthority).toBe("ts");
    expect(c.providersCredentialsAuthority).toBe("ts");
    expect(c.runsAuthority).toBe("ts");
    expect(c.policyAuthority).toBe("ts");
    expect(c.proposalsAuthority).toBe("ts");
    expect(c.sessionsAuthority).toBe("ts");
    expect(c.chatTurnAuthority).toBe("ts");
    expect(c.contextAuthority).toBe("ts");
    expect(c.memoryAuthority).toBe("ts");
    expect(c.memoryApplyAuthority).toBe("ts");
    expect(c.databaseUrl).toBe("postgresql://cp@db:5432/agent_space");
    expect(c.internalToken).toBe("service-token");
    expect(c.agentSpaceHome).toBe("/tmp/aspace");
    expect(c.cliToolsRoot).toBe("/tmp/aspace/tools");
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
    expect(line).toContain("memoryApplyAuthority=python");
    expect(line).toContain("internalTokenConfigured=false");
    expect(line).not.toMatch(/authorization|cookie|password|secret/i);
    expect(describeConfig(loadConfig({ CONTROL_PLANE_INTERNAL_TOKEN: "secret-token" }))).not
      .toContain("secret-token");
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
    expect(
      codeOf({ CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts" }),
    ).toBe("providers_credentials_requires_provider_read_authority");
    expect(
      codeOf({
        CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
        CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
      }),
    ).toBe("missing_database_url_for_providers");
    expect(
      codeOf({
        CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
        CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      }),
    ).toBe("missing_internal_token_for_providers_credentials");
    expect(codeOf({ CONTROL_PLANE_RUNS_AUTHORITY: "bogus" })).toBe(
      "invalid_runs_authority",
    );
    expect(codeOf({ CONTROL_PLANE_RUNS_AUTHORITY: "ts" })).toBe(
      "runs_requires_providers_credentials_authority",
    );
    expect(codeOf({ CONTROL_PLANE_POLICY_AUTHORITY: "bogus" })).toBe(
      "invalid_policy_authority",
    );
    expect(codeOf({ CONTROL_PLANE_POLICY_AUTHORITY: "ts" })).toBe(
      "missing_database_url_for_policy",
    );
    expect(
      codeOf({
        CONTROL_PLANE_POLICY_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      }),
    ).toBe("missing_internal_token_for_policy");
    expect(codeOf({ CONTROL_PLANE_PROPOSALS_AUTHORITY: "bogus" })).toBe(
      "invalid_proposals_authority",
    );
    expect(codeOf({ CONTROL_PLANE_PROPOSALS_AUTHORITY: "ts" })).toBe(
      "missing_database_url_for_proposals",
    );
    expect(
      codeOf({
        CONTROL_PLANE_PROPOSALS_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      }),
    ).toBe("missing_internal_token_for_proposals");
    expect(codeOf({ CONTROL_PLANE_SESSIONS_AUTHORITY: "ts" })).toBe(
      "missing_database_url_for_sessions",
    );
    expect(
      codeOf({
        CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      }),
    ).toBe("missing_internal_token_for_sessions");
    expect(codeOf({ CONTROL_PLANE_CHAT_TURN_AUTHORITY: "bogus" })).toBe(
      "invalid_chat_turn_authority",
    );
    expect(codeOf({ CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts" })).toBe(
      "chat_turn_requires_sessions_authority",
    );
    expect(
      codeOf({
        CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
        CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
        CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
      }),
    ).toBe("chat_turn_requires_runs_authority");
    expect(codeOf({ CONTROL_PLANE_CONTEXT_AUTHORITY: "bogus" })).toBe(
      "invalid_context_authority",
    );
    expect(codeOf({ CONTROL_PLANE_CONTEXT_AUTHORITY: "ts" })).toBe(
      "context_requires_chat_turn_authority",
    );
    expect(codeOf({ CONTROL_PLANE_MEMORY_AUTHORITY: "bogus" })).toBe(
      "invalid_memory_authority",
    );
    expect(codeOf({ CONTROL_PLANE_MEMORY_AUTHORITY: "ts" })).toBe(
      "memory_requires_policy_authority",
    );
    expect(
      codeOf({
        CONTROL_PLANE_POLICY_AUTHORITY: "ts",
        CONTROL_PLANE_MEMORY_AUTHORITY: "ts",
        CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
        CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
      }),
    ).toBe("memory_requires_proposals_authority");
    expect(
      codeOf({
        CONTROL_PLANE_POLICY_AUTHORITY: "ts",
        CONTROL_PLANE_PROPOSALS_AUTHORITY: "ts",
        CONTROL_PLANE_MEMORY_AUTHORITY: "ts",
      }),
    ).toBe("missing_database_url_for_policy");
    expect(codeOf({ CONTROL_PLANE_MEMORY_APPLY_AUTHORITY: "bogus" })).toBe(
      "invalid_memory_apply_authority",
    );
    expect(codeOf({ CONTROL_PLANE_MEMORY_APPLY_AUTHORITY: "ts" })).toBe(
      "memory_apply_requires_memory_authority",
    );
  });

  it("accepts context=ts once chat-turn/sessions prerequisites are satisfied", () => {
    const config = loadConfig({
      CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
      CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
      CONTROL_PLANE_RUNS_AUTHORITY: "ts",
      CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
      CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
      CONTROL_PLANE_CONTEXT_AUTHORITY: "ts",
      CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
    });
    expect(config.contextAuthority).toBe("ts");
  });
});

describe("config snapshot", () => {
  it("is immutable and identifies the config by schema version + content hash", () => {
    const snapshot = loadConfigSnapshot({});
    expect(snapshot.schema_version).toBe(8);
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
      CONTROL_PLANE_MEMORY_APPLY_AUTHORITY: "python", // known — not flagged
      UNRELATED_VAR: "x", // outside the namespace — not flagged
    });
    expect(diagnostics).toEqual([
      {
        severity: "warning",
        code: "unknown_config_key",
        message: "Unrecognized environment variable CONTROL_PLANE_PROT (ignored)",
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
    expect(collectConfigDiagnostics({}, config)).toEqual([
      {
        severity: "info",
        code: "notification_webhook_allowlist_inactive",
        message: "Notification webhook allowlist is configured but egress is disabled",
      },
      {
        severity: "warning",
        code: "stream_poll_interval_exceeds_timeout",
        message:
          "Run-event stream poll interval is greater than or equal to the Python request timeout",
      },
    ]);
  });

  it("describes TS sessions authority as the full public session surface", () => {
    const config = loadConfig({
      CONTROL_PLANE_SESSIONS_AUTHORITY: "ts",
      CONTROL_PLANE_CHAT_TURN_AUTHORITY: "ts",
      CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
      CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
      CONTROL_PLANE_RUNS_AUTHORITY: "ts",
      CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
      CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
    });

    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "sessions_authority_ts",
      message:
        "Public session routes (list/get/create sessions, list/add messages) and session_summary.get_latest are served by the TS authority; session reflect and summary condense remain Python-owned",
    });
    expect(collectConfigDiagnostics({}, config)).toContainEqual({
      severity: "info",
      code: "chat_turn_authority_ts",
      message:
        "Personal Assistant chat turns are served by the TS authority; context/run preparation still dispatches through the internal Python chat port",
    });
  });
});
