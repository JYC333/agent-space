/**
 * The read-only shadow compare observes Python-served provider reads, compares
 * them against the TS DB-backed result, and never affects the response —
 * including when the DB or introspection port fails.
 */

import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { __setProvidersDbPortForTests } from "../src/modules/providers/dbReader";
import {
  __setShadowReporterForTests,
  compareProviderPayloads,
  type ShadowReport,
} from "../src/modules/providers/shadow";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

afterEach(async () => {
  __setProvidersDbPortForTests(null);
  __setShadowReporterForTests(null);
  await app?.close();
  const current = upstream;
  upstream = undefined;
  await current?.close();
});

function provider(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    space_id: "space-1",
    name: "Main",
    provider_type: "openai",
    base_url: null,
    default_model: "gpt-4o",
    available_models: ["gpt-4o"],
    enabled: true,
    is_default: true,
    has_api_key: true,
    created_at: "2026-06-11T12:00:00+00:00",
    updated_at: "2026-06-11T12:00:00+00:00",
    ...overrides,
  };
}

function shadowConfig(baseUrl: string) {
  return loadConfig({
    CONTROL_PLANE_PYTHON_API_BASE_URL: baseUrl,
    CONTROL_PLANE_PROVIDERS_SHADOW: "true",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp_ro@db:5432/agent_space",
  });
}

function collectReports(): { reports: ShadowReport[]; next: () => Promise<ShadowReport> } {
  const reports: ShadowReport[] = [];
  let resolvers: Array<(r: ShadowReport) => void> = [];
  __setShadowReporterForTests((report) => {
    reports.push(report);
    const pending = resolvers;
    resolvers = [];
    for (const resolve of pending) resolve(report);
  });
  return {
    reports,
    next: () =>
      new Promise<ShadowReport>((resolve) => {
        if (reports.length > 0) {
          resolve(reports[reports.length - 1]);
          return;
        }
        resolvers.push(resolve);
      }),
  };
}

function pythonAndIntrospectUpstream(listBody: unknown) {
  return startMockUpstream((req, res) => {
    if (req.url.startsWith("/api/v1/auth/introspect")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ space_id: "space-1", user_id: "user-1" }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json", "x-upstream": "python" });
    res.end(JSON.stringify(listBody));
  });
}

describe("providers shadow compare", () => {
  it("reports a match while Python keeps serving, tolerating timestamp formats", async () => {
    const served = [provider("mp-1")];
    upstream = await pythonAndIntrospectUpstream(served);
    __setProvidersDbPortForTests({
      async listProviders() {
        // Same instant, TS serialization.
        return [provider("mp-1", { created_at: "2026-06-11T12:00:00.000Z", updated_at: "2026-06-11T12:00:00.000Z" })];
      },
      async getProvider() {
        return null;
      },
    });
    const { next } = collectReports();
    app = buildServer(shadowConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers?space_id=space-1" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["x-upstream"]).toBe("python");
    expect(res.json()).toEqual(served);

    const report = await next();
    expect(report).toEqual({ route: "list", outcome: "match" });
  });

  it("reports divergences with field paths when the TS result differs", async () => {
    upstream = await pythonAndIntrospectUpstream([provider("mp-1")]);
    __setProvidersDbPortForTests({
      async listProviders() {
        return [provider("mp-1", { has_api_key: false })];
      },
      async getProvider() {
        return null;
      },
    });
    const { next } = collectReports();
    app = buildServer(shadowConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers?space_id=space-1" });
    expect(res.statusCode).toBe(200);

    const report = await next();
    expect(report.outcome).toBe("divergence");
    expect(report.divergences).toEqual(["$[0].has_api_key"]);
  });

  it("skips without affecting the response when the DB read fails", async () => {
    upstream = await pythonAndIntrospectUpstream([provider("mp-1")]);
    __setProvidersDbPortForTests({
      async listProviders() {
        throw new Error("db down");
      },
      async getProvider() {
        return null;
      },
    });
    const { next } = collectReports();
    app = buildServer(shadowConfig(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers?space_id=space-1" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual([provider("mp-1")]);

    const report = await next();
    expect(report.outcome).toBe("error");
  });

  it("does not run the compare when shadow is disabled", async () => {
    upstream = await pythonAndIntrospectUpstream([provider("mp-1")]);
    const { reports } = collectReports();
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers?space_id=space-1" });
    expect(res.statusCode).toBe(200);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(reports).toEqual([]);
    expect(
      upstream.requests.filter((r) => r.url.startsWith("/api/v1/auth/introspect")),
    ).toHaveLength(0);
  });
});

describe("compareProviderPayloads", () => {
  it("treats equal instants in different serializations as equal", () => {
    expect(
      compareProviderPayloads(
        { created_at: "2026-06-11T12:00:00+00:00", name: "a" },
        { created_at: "2026-06-11T12:00:00.000Z", name: "a" },
      ),
    ).toEqual([]);
  });

  it("reports paths for nested and missing-field divergences", () => {
    expect(
      compareProviderPayloads(
        [{ id: "a", available_models: ["x"] }],
        [{ id: "a", available_models: ["y"], extra: 1 }],
      ).sort(),
    ).toEqual(["$[0].available_models[0]", "$[0].extra"]);
    expect(compareProviderPayloads([{ id: "a" }], [])).toEqual(["$.length"]);
  });
});
