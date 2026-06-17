/**
 * Tests for the gateway conventions: route registry ordering, the error
 * envelope for TS-owned routes, request-id continuity, safe header access, and
 * the composition-root discipline of server.ts.
 */

import { describe, it, expect, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  registerControlPlaneRoutes,
  TS_OWNED_MODULES,
} from "../src/gateway/routeRegistry";
import { readHeader } from "../src/gateway/requestContext";
import { systemModule } from "../src/modules/system";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("route registry", () => {
  it("registers TS-owned module routes before the Python fallback catch-all (proxy last)", () => {
    const registered: Array<{ method: string; url: string }> = [];
    const fakeApp = {
      get: (url: string) => registered.push({ method: "GET", url }),
      post: (url: string) => registered.push({ method: "POST", url }),
      put: (url: string) => registered.push({ method: "PUT", url }),
      patch: (url: string) => registered.push({ method: "PATCH", url }),
      delete: (url: string) => registered.push({ method: "DELETE", url }),
      all: (url: string) => registered.push({ method: "ALL", url }),
      setErrorHandler: () => undefined,
      addHook: () => undefined,
    } as unknown as FastifyInstance;

    registerControlPlaneRoutes(fakeApp, loadConfig({}));

    const urls = registered.map((r) => r.url);
    expect(urls).toContain("/health");
    expect(urls).toContain("/api/v1/control-plane/health");
    expect(urls).toContain("/api/v1/control-plane/features");
    expect(urls).toContain("/api/v1/auth/google-configured");
    expect(urls).toContain("/api/v1/auth/google");
    expect(urls).toContain("/api/v1/auth/google/callback");
    expect(urls).toContain("/api/v1/auth/keys");
    expect(urls).toContain("/api/v1/auth/introspect");
    expect(urls).toContain("/api/v1/me");
    expect(urls).toContain("/api/v1/me/spaces");
    expect(urls).toContain("/api/v1/spaces");
    expect(urls).toContain("/api/v1/spaces/:spaceId");
    expect(urls).toContain("/api/v1/spaces/:spaceId/members");
    expect(urls).toContain("/api/v1/spaces/:spaceId/invitations");
    expect(urls).toContain("/api/v1/invitations/:token/accept");
    expect(urls).toContain("/api/v1/runs/:runId/events/stream");
    expect(urls).toContain("/api/v1/control-plane/notifications/webhooks/dispatch");
    expect(urls).toContain("/api/v1/providers");
    expect(urls).toContain("/api/v1/providers/catalog");
    expect(urls).toContain("/api/v1/providers/litellm-providers");
    expect(urls).toContain("/api/v1/providers/:configId");
    expect(urls).toContain("/api/v1/artifacts");
    expect(urls).toContain("/api/v1/activity");
    expect(urls).toContain("/api/v1/intake");
    expect(urls).toContain("/api/v1/knowledge");
    expect(urls).toContain("/api/v1/tasks");
    expect(urls).toContain("/api/v1/boards");
    expect(urls).toContain("/api/v1/me/tasks");
    expect(urls).toContain("/api/v1/workspaces");
    expect(urls).toContain("/api/v1/home/summary");
    expect(urls).toContain("/api/v1/me/summary");
    expect(urls).toContain("/api/v1/workspace-console/workspaces");
    expect(urls).toContain("/api/v1/deployments/jobs");
    // The Python fallback proxy catch-all must be the very last registration.
    expect(registered[registered.length - 1]).toEqual({ method: "ALL", url: "/api/v1/*" });
    expect(urls.filter((u) => u === "/api/v1/*")).toHaveLength(1);
  });

  it("exposes the system module through the standard module convention", () => {
    expect(systemModule.name).toBe("system");
    expect(typeof systemModule.registerRoutes).toBe("function");
    expect(TS_OWNED_MODULES).toContain(systemModule);
    expect(TS_OWNED_MODULES.map((m) => m.name)).toEqual([
      "system",
      "auth",
      "spaces",
      "catalog",
      "streaming",
      "notifications",
      "runtimeTools",
      "providers",
      "runtime_host",
      "runs",
      "artifacts",
      "policy",
      "proposals",
      "sessions",
      "agents",
      "memory",
      "activity",
      "intake",
      "knowledge",
      "tasks",
      "workspaces",
      "jobs",
      "automations",
      "dailyReports",
      "backups",
      "deployment",
      "frontend_support",
    ]);
    // The Python fallback proxy is bridge code, not a TS-owned module.
    expect(TS_OWNED_MODULES.map((m) => m.name)).not.toContain("pythonFallback");
  });
});

describe("request id on TS-owned routes", () => {
  it("preserves an incoming x-request-id on the response", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({
      method: "GET",
      url: "/health",
      headers: { "x-request-id": "req-abc" },
    });
    expect(res.statusCode).toBe(200);
    expect(res.headers["x-request-id"]).toBe("req-abc");
  });

  it("generates an x-request-id when the client did not send one", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/health" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["x-request-id"]).toBeTruthy();
  });
});

describe("error envelope for TS-owned routes", () => {
  function buildAppWithThrowingRoute(message: string, statusCode?: number) {
    // A static route beats the /api/v1/* wildcard, so this simulates a TS-owned
    // module route that throws.
    const server = buildServer(loadConfig({}), { logger: false });
    server.get("/api/v1/control-plane/boom", async () => {
      const err = new Error(message);
      if (statusCode !== undefined) Object.assign(err, { statusCode });
      throw err;
    });
    return server;
  }

  it("returns { error, message, request_id } with a generic message for 5xx", async () => {
    app = buildAppWithThrowingRoute("kaboom with internals: db at 10.0.0.5");
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/boom",
      headers: { "x-request-id": "req-err-1" },
    });
    expect(res.statusCode).toBe(500);
    expect(res.json()).toEqual({
      error: "internal_error",
      message: "Internal control-plane error",
      request_id: "req-err-1",
    });
    // No stack traces or internal detail in the body.
    expect(res.payload).not.toContain("kaboom");
    expect(res.payload).not.toContain("10.0.0.5");
    expect(res.payload).not.toContain("at "); // stack frame marker
  });

  it("keeps intentional client-safe messages for 4xx", async () => {
    app = buildAppWithThrowingRoute("unknown feature flag", 404);
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/boom" });
    expect(res.statusCode).toBe(404);
    const body = res.json() as Record<string, string>;
    expect(body.error).toBe("request_error");
    expect(body.message).toBe("unknown feature flag");
    expect(body.request_id).toBeTruthy();
  });

  it("never echoes Authorization or Cookie values in error bodies", async () => {
    app = buildAppWithThrowingRoute("boom");
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/boom",
      headers: {
        authorization: "Bearer secret-token-123",
        cookie: "session=topsecret",
      },
    });
    expect(res.statusCode).toBe(500);
    expect(res.payload).not.toContain("secret-token-123");
    expect(res.payload).not.toContain("topsecret");
  });

  it("does not change the fallback proxy's sanitized 502 body shape", async () => {
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: "http://127.0.0.1:9" }), {
      logger: false,
    });
    const res = await app.inject({ method: "GET", url: "/api/v1/python-only-smoke" });
    expect(res.statusCode).toBe(502);
    expect(res.json()).toEqual({
      error: "python_backend_unavailable",
      message: "Python backend is unavailable",
    });
  });
});

describe("safe header access", () => {
  function fakeRequest(headers: Record<string, string | string[]>): FastifyRequest {
    return { headers } as unknown as FastifyRequest;
  }

  it("returns ordinary headers and normalizes arrays", () => {
    expect(readHeader(fakeRequest({ accept: "application/json" }), "Accept")).toBe(
      "application/json",
    );
    expect(readHeader(fakeRequest({ "x-thing": ["a", "b"] }), "x-thing")).toBe("a");
    expect(readHeader(fakeRequest({}), "x-missing")).toBeUndefined();
  });

  it("refuses to return Authorization, Cookie and Proxy-Authorization", () => {
    const request = fakeRequest({
      authorization: "Bearer secret-token-123",
      cookie: "session=topsecret",
      "proxy-authorization": "Basic secret",
    });
    expect(readHeader(request, "authorization")).toBeUndefined();
    expect(readHeader(request, "Authorization")).toBeUndefined();
    expect(readHeader(request, "cookie")).toBeUndefined();
    expect(readHeader(request, "proxy-authorization")).toBeUndefined();
  });
});

describe("composition root discipline", () => {
  it("server.ts contains no direct route registrations", () => {
    const source = readFileSync(join(__dirname, "..", "src", "server.ts"), "utf8");
    for (const marker of ["app.get(", "app.post(", "app.put(", "app.delete(", "app.all(", "app.route("]) {
      expect(source).not.toContain(marker);
    }
  });
});
