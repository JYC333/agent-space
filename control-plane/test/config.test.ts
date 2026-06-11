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
    expect(c.legacyPythonApiBaseUrl).toBe("http://backend:8000");
    expect(c.enableLegacyProxy).toBe(true);
    expect(c.logLevel).toBe("info");
    expect(c.requestTimeoutMs).toBe(300000);
  });

  it("honors CONTROL_PLANE_* overrides and normalizes a trailing slash", () => {
    const c = loadConfig({
      CONTROL_PLANE_HOST: "127.0.0.1",
      CONTROL_PLANE_PORT: "9100",
      LEGACY_PYTHON_API_BASE_URL: "http://backend:8000/",
      CONTROL_PLANE_ENABLE_LEGACY_PROXY: "false",
      CONTROL_PLANE_LOG_LEVEL: "debug",
      CONTROL_PLANE_REQUEST_TIMEOUT_MS: "1000",
    });
    expect(c.host).toBe("127.0.0.1");
    expect(c.port).toBe(9100);
    expect(c.legacyPythonApiBaseUrl).toBe("http://backend:8000");
    expect(c.enableLegacyProxy).toBe(false);
    expect(c.logLevel).toBe("debug");
    expect(c.requestTimeoutMs).toBe(1000);
  });

  it("fails fast on a malformed LEGACY_PYTHON_API_BASE_URL", () => {
    expect(() => loadConfig({ LEGACY_PYTHON_API_BASE_URL: "not a url" })).toThrow(ConfigError);
    expect(() => loadConfig({ LEGACY_PYTHON_API_BASE_URL: "ftp://x:1" })).toThrow(ConfigError);
  });

  it("rejects invalid port, boolean and log level", () => {
    expect(() => loadConfig({ CONTROL_PLANE_PORT: "0" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_PORT: "abc" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_ENABLE_LEGACY_PROXY: "maybe" })).toThrow(ConfigError);
    expect(() => loadConfig({ CONTROL_PLANE_LOG_LEVEL: "loud" })).toThrow(ConfigError);
  });

  it("describeConfig is a single line with no secret-bearing fields", () => {
    const line = describeConfig(loadConfig({}));
    expect(line).toContain("port=8010");
    expect(line).not.toMatch(/authorization|cookie|password|secret/i);
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
    expect(codeOf({ CONTROL_PLANE_ENABLE_LEGACY_PROXY: "maybe" })).toBe("invalid_boolean");
    expect(codeOf({ LEGACY_PYTHON_API_BASE_URL: "not a url" })).toBe("invalid_base_url");
    expect(codeOf({ LEGACY_PYTHON_API_BASE_URL: "ftp://x:1" })).toBe("invalid_url_protocol");
    expect(codeOf({ CONTROL_PLANE_LOG_LEVEL: "loud" })).toBe("invalid_log_level");
  });
});

describe("config snapshot", () => {
  it("is immutable and identifies the config by schema version + content hash", () => {
    const snapshot = loadConfigSnapshot({});
    expect(snapshot.schema_version).toBe(1);
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
});
