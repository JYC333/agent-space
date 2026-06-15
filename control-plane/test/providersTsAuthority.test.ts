/**
 * TS provider-read authority path: list/detail/catalog served by the control
 * plane behind the Python identity-introspection port. Uses a fake DB port;
 * PostgreSQL access is covered by stack smoke checks.
 */

import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setProvidersDbPortForTests,
  type ProvidersDbPort,
} from "../src/modules/providers/dbReader";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

afterEach(async () => {
  __setProvidersDbPortForTests(null);
  await app?.close();
  const current = upstream;
  upstream = undefined;
  await current?.close();
});

function provider(id: string, spaceId = "space-1") {
  return {
    id,
    space_id: spaceId,
    name: "Main",
    provider_type: "openai",
    base_url: null,
    default_model: "gpt-4o",
    available_models: ["gpt-4o"],
    enabled: true,
    is_default: true,
    has_api_key: true,
    created_at: "2026-06-11T12:00:00.000Z",
    updated_at: "2026-06-11T12:00:00.000Z",
  };
}

function fakeDb(rowsBySpace: Record<string, ReturnType<typeof provider>[]>): ProvidersDbPort {
  return {
    async listProviders(spaceId) {
      return rowsBySpace[spaceId] ?? [];
    },
    async getProvider(spaceId, configId) {
      return (rowsBySpace[spaceId] ?? []).find((r) => r.id === configId) ?? null;
    },
  };
}

function introspectUpstream(
  handler?: (req: { url: string }, res: import("node:http").ServerResponse) => boolean,
) {
  return startMockUpstream((req, res) => {
    if (handler?.(req, res)) return;
    if (req.url.startsWith("/api/v1/auth/introspect")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ space_id: "space-1", user_id: "user-1" }));
      return;
    }
    if (req.url.startsWith("/api/v1/providers/litellm-providers")) {
      res.writeHead(200, { "content-type": "application/json", "x-upstream": "python" });
      res.end(JSON.stringify(["openai", "anthropic"]));
      return;
    }
    res.writeHead(500, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "unexpected python call in ts authority mode" }));
  });
}

function tsAuthorityConfig(baseUrl: string) {
  return loadConfig({
    CONTROL_PLANE_PYTHON_API_BASE_URL: baseUrl,
    CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp_ro@db:5432/agent_space",
  });
}

describe("providers TS read authority", () => {
  it("serves list and detail from the DB port scoped by introspected identity", async () => {
    upstream = await introspectUpstream();
    __setProvidersDbPortForTests(
      fakeDb({ "space-1": [provider("mp-2"), provider("mp-1")] }),
    );
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    const list = await app.inject({
      method: "GET",
      url: "/api/v1/providers?space_id=space-1",
      headers: { cookie: "session_id=abc" },
    });
    expect(list.statusCode).toBe(200);
    expect(list.json().map((r: { id: string }) => r.id)).toEqual(["mp-2", "mp-1"]);

    const detail = await app.inject({
      method: "GET",
      url: "/api/v1/providers/mp-1?space_id=space-1",
    });
    expect(detail.statusCode).toBe(200);
    expect(detail.json().id).toBe("mp-1");

    // Identity resolution went through the Python introspection port with the
    // caller's space_id query forwarded.
    const introspects = upstream.requests.filter((r) =>
      r.url.startsWith("/api/v1/auth/introspect"),
    );
    expect(introspects).toHaveLength(2);
    expect(introspects[0].url).toBe("/api/v1/auth/introspect?space_id=space-1");
    expect(introspects[0].headers.cookie).toBe("session_id=abc");
  });

  it("returns the Python-style 404 detail for a missing provider", async () => {
    upstream = await introspectUpstream();
    __setProvidersDbPortForTests(fakeDb({ "space-1": [] }));
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers/mp-missing" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ detail: "ModelProvider 'mp-missing' not found" });
  });

  it("passes Python authentication denials through unchanged", async () => {
    upstream = await introspectUpstream((req, res) => {
      if (req.url.startsWith("/api/v1/auth/introspect")) {
        res.writeHead(401, { "content-type": "application/json" });
        res.end(JSON.stringify({ detail: "Authentication required" }));
        return true;
      }
      return false;
    });
    __setProvidersDbPortForTests(fakeDb({ "space-1": [provider("mp-1")] }));
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toEqual({ detail: "Authentication required" });
  });

  it("serves the catalog constant and keeps litellm-providers Python-forwarded", async () => {
    upstream = await introspectUpstream();
    __setProvidersDbPortForTests(fakeDb({}));
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    // Dynamic import: the typecheck runs this CJS test against the ESM package.
    const { PROVIDER_CATALOG_INFO } = await import("@agent-space/protocol");
    const catalog = await app.inject({ method: "GET", url: "/api/v1/providers/catalog" });
    expect(catalog.statusCode).toBe(200);
    expect(catalog.json()).toEqual(PROVIDER_CATALOG_INFO);

    const litellm = await app.inject({
      method: "GET",
      url: "/api/v1/providers/litellm-providers",
    });
    expect(litellm.statusCode).toBe(200);
    expect(litellm.headers["x-upstream"]).toBe("python");
    expect(litellm.json()).toEqual(["openai", "anthropic"]);
  });

  it("answers 503 when the DB read fails, without leaking the error", async () => {
    upstream = await introspectUpstream();
    __setProvidersDbPortForTests({
      async listProviders() {
        throw new Error("connection refused at db:5432 password=hunter2");
      },
      async getProvider() {
        return null;
      },
    });
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers" });
    expect(res.statusCode).toBe(503);
    expect(res.json().error).toBe("providers_db_unavailable");
    expect(res.payload).not.toContain("hunter2");
  });

  it("advertises the TS authority feature and requires the database URL", async () => {
    upstream = await introspectUpstream();
    __setProvidersDbPortForTests(fakeDb({}));
    app = buildServer(tsAuthorityConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/features" });
    const features = res.json().features as string[];
    expect(features).toContain("providers_read_ts_authority");
    expect(features).not.toContain("providers_readonly_python_facade");

    expect(() =>
      loadConfig({ CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts" }),
    ).toThrowError(/CONTROL_PLANE_DATABASE_URL is required/);
  });
});
