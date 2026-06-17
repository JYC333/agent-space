import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";

// Fallback-disabled route ownership checklist.
//
// With the fallback proxy DISABLED, any `/api/v1/*` route the control plane does
// not own itself hits the catch-all and returns 503 `python_fallback_proxy_disabled`.
// That set of 503s is the live list of HTTP surfaces still owned by fallback
// routing. It is not a complete inventory of Python context ports or internal
// Python dependencies.
//
// This test asserts (a) the mechanism works — an always-on TS route does NOT 503 —
// and (b) a curated list of known fallback-owned routes still 503 today. As each
// domain migrates, move its entry from FALLBACK_OWNED_ROUTES into a
// migrated assertion (or delete it) so this test tracks real progress.

// Known fallback-owned `/api/v1/*` surfaces (method + representative path).
// These are not yet registered as TS routes in any authority configuration; keep
// this aligned with .agent/architecture/TS_CONTROL_PLANE_OWNERSHIP.md.
const FALLBACK_OWNED_ROUTES: Array<{ method: "GET" | "POST"; url: string }> = [];

const TS_OWNED_LEAF_DOMAIN_ROUTES: Array<{
  method: "GET" | "POST" | "PATCH" | "DELETE";
  url: string;
}> = [
  { method: "GET", url: "/api/v1/activity" },
  { method: "POST", url: "/api/v1/activity" },
  { method: "POST", url: "/api/v1/activity/upload" },
  { method: "PATCH", url: "/api/v1/activity/activity-id/review" },
  { method: "GET", url: "/api/v1/activity/activity-id" },
  { method: "PATCH", url: "/api/v1/activity/activity-id/archive" },
  { method: "POST", url: "/api/v1/activity/activity-id/consolidate" },
  { method: "POST", url: "/api/v1/activity/summary-runs" },
  { method: "GET", url: "/api/v1/intake" },
  { method: "GET", url: "/api/v1/intake/connectors" },
  { method: "GET", url: "/api/v1/intake/items" },
  { method: "POST", url: "/api/v1/intake/items/manual-url" },
  { method: "GET", url: "/api/v1/intake/items/item-id" },
  { method: "POST", url: "/api/v1/intake/items/item-id/actions" },
  { method: "GET", url: "/api/v1/intake/connections" },
  { method: "POST", url: "/api/v1/intake/connections" },
  { method: "GET", url: "/api/v1/intake/connections/conn-id" },
  { method: "PATCH", url: "/api/v1/intake/connections/conn-id" },
  { method: "DELETE", url: "/api/v1/intake/connections/conn-id" },
  { method: "POST", url: "/api/v1/intake/connections/conn-id/scan" },
  { method: "GET", url: "/api/v1/intake/jobs" },
  { method: "POST", url: "/api/v1/intake/jobs/job-id/run" },
  { method: "GET", url: "/api/v1/intake/evidence" },
  { method: "POST", url: "/api/v1/intake/evidence" },
  { method: "GET", url: "/api/v1/intake/evidence/evidence-id" },
  { method: "PATCH", url: "/api/v1/intake/evidence/evidence-id" },
  { method: "GET", url: "/api/v1/intake/evidence-links" },
  { method: "POST", url: "/api/v1/intake/evidence-links" },
  { method: "GET", url: "/api/v1/intake/workspace-profiles" },
  { method: "POST", url: "/api/v1/intake/workspace-profiles" },
  { method: "GET", url: "/api/v1/intake/workspace-source-bindings" },
  { method: "POST", url: "/api/v1/intake/workspace-source-bindings" },
  { method: "POST", url: "/api/v1/intake/summary-runs" },
  { method: "GET", url: "/api/v1/intake/summary-runs" },
  { method: "GET", url: "/api/v1/knowledge" },
  { method: "GET", url: "/api/v1/knowledge/summary" },
  { method: "GET", url: "/api/v1/knowledge/items" },
  { method: "POST", url: "/api/v1/knowledge/items/proposals" },
  { method: "GET", url: "/api/v1/knowledge/items/item-id" },
  { method: "GET", url: "/api/v1/knowledge/items/item-id/relations" },
  { method: "GET", url: "/api/v1/knowledge/items/item-id/backlinks" },
  { method: "PATCH", url: "/api/v1/knowledge/items/item-id/proposals" },
  { method: "DELETE", url: "/api/v1/knowledge/items/item-id" },
  { method: "POST", url: "/api/v1/knowledge/relations/proposals" },
  { method: "DELETE", url: "/api/v1/knowledge/relations/relation-id" },
  { method: "GET", url: "/api/v1/knowledge/sources" },
  { method: "POST", url: "/api/v1/knowledge/sources" },
  { method: "GET", url: "/api/v1/knowledge/sources/source-id" },
  { method: "PATCH", url: "/api/v1/knowledge/sources/source-id" },
  { method: "DELETE", url: "/api/v1/knowledge/sources/source-id" },
  { method: "GET", url: "/api/v1/knowledge/sources/source-id/items" },
  { method: "GET", url: "/api/v1/knowledge/items/item-id/sources" },
  { method: "POST", url: "/api/v1/knowledge/items/item-id/sources" },
  { method: "DELETE", url: "/api/v1/knowledge/items/item-id/sources/link-id" },
  { method: "GET", url: "/api/v1/knowledge/entity-links" },
  { method: "GET", url: "/api/v1/knowledge/notes" },
  { method: "POST", url: "/api/v1/knowledge/notes" },
  { method: "POST", url: "/api/v1/knowledge/notes/deleted/purge" },
  { method: "GET", url: "/api/v1/knowledge/notes/note-id" },
  { method: "PATCH", url: "/api/v1/knowledge/notes/note-id" },
  { method: "DELETE", url: "/api/v1/knowledge/notes/note-id" },
  { method: "GET", url: "/api/v1/knowledge/notes/note-id/links" },
  { method: "GET", url: "/api/v1/knowledge/notes/note-id/backlinks" },
  { method: "POST", url: "/api/v1/knowledge/notes/note-id/links" },
  { method: "DELETE", url: "/api/v1/knowledge/notes/note-id/links/link-id" },
  { method: "GET", url: "/api/v1/tasks" },
  { method: "POST", url: "/api/v1/tasks" },
  { method: "GET", url: "/api/v1/tasks/task-id" },
  { method: "PATCH", url: "/api/v1/tasks/task-id" },
  { method: "GET", url: "/api/v1/tasks/task-id/runs" },
  { method: "POST", url: "/api/v1/tasks/task-id/runs" },
  { method: "GET", url: "/api/v1/tasks/task-id/artifacts" },
  { method: "GET", url: "/api/v1/tasks/task-id/proposals" },
  { method: "GET", url: "/api/v1/tasks/task-id/evaluations" },
  { method: "POST", url: "/api/v1/tasks/task-id/evaluations" },
  { method: "GET", url: "/api/v1/boards" },
  { method: "POST", url: "/api/v1/boards" },
  { method: "GET", url: "/api/v1/boards/board-id" },
  { method: "PATCH", url: "/api/v1/boards/board-id" },
  { method: "GET", url: "/api/v1/boards/board-id/tasks" },
  { method: "GET", url: "/api/v1/me/tasks" },
];

const FALLBACK_DISABLED_ERROR = "python_fallback_proxy_disabled";

function errorCode(res: { payload: string; json: () => unknown }): string | undefined {
  if (!res.payload) return undefined;
  try {
    const body = res.json() as { error?: string };
    return body.error;
  } catch {
    return undefined;
  }
}

function fallbackDisabledServer(): FastifyInstance {
  // Default (python) authorities + fallback disabled. The dead upstream URL is
  // never contacted: a disabled fallback answers 503 before forwarding.
  const config = loadConfig({
    CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false",
    CONTROL_PLANE_PYTHON_API_BASE_URL: "http://127.0.0.1:9",
  });
  return buildServer(config, { logger: false });
}

let app: FastifyInstance | undefined;
afterEach(async () => {
  await app?.close();
  app = undefined;
});

describe("fallback route checklist", () => {
  it("an always-on TS route is served locally (not a fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    const res = await server.inject({ method: "GET", url: "/api/v1/control-plane/features" });
    expect(res.statusCode).toBe(200);
  });

  it("native auth and spaces routes are served locally (not fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    for (const route of [
      { method: "GET", url: "/api/v1/auth/google-configured" },
      { method: "GET", url: "/api/v1/auth/google" },
      { method: "GET", url: "/api/v1/auth/google/callback" },
      { method: "GET", url: "/api/v1/auth/keys" },
      { method: "POST", url: "/api/v1/auth/keys" },
      { method: "DELETE", url: "/api/v1/auth/keys/key-1" },
      { method: "GET", url: "/api/v1/auth/introspect" },
      { method: "GET", url: "/api/v1/me" },
      { method: "GET", url: "/api/v1/me/spaces" },
      { method: "POST", url: "/api/v1/spaces" },
      { method: "GET", url: "/api/v1/spaces/s1" },
      { method: "GET", url: "/api/v1/spaces/s1/members" },
      { method: "POST", url: "/api/v1/spaces/s1/invitations" },
      { method: "POST", url: "/api/v1/invitations/tok/accept" },
    ] as const) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      expect(
        res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR,
        `${route.method} ${route.url} should be TS-owned, got fallback 503`,
      ).toBe(false);
    }
  });

  it("native artifact routes are served locally (not fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    for (const route of [
      { method: "GET", url: "/api/v1/artifacts" },
      { method: "GET", url: "/api/v1/artifacts/artifact-1" },
      { method: "GET", url: "/api/v1/artifacts/artifact-1/export" },
    ] as const) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      expect(
        res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR,
        `${route.method} ${route.url} should be TS-owned, got fallback 503`,
      ).toBe(false);
    }
  });

  it("leaf-domain routes are served locally (not fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    for (const route of TS_OWNED_LEAF_DOMAIN_ROUTES) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      expect(
        res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR,
        `${route.method} ${route.url} should be TS-owned edge, got fallback 503`,
      ).toBe(false);
    }
  });

  it("scheduler, automation, daily-report, backup, and consolidation routes are served locally (not fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    for (const route of [
      { method: "GET", url: "/api/v1/spaces/s1/automations" },
      { method: "GET", url: "/api/v1/jobs" },
      { method: "GET", url: "/api/v1/jobs/handlers" },
      { method: "GET", url: "/api/v1/daily-capture-report/settings" },
      { method: "GET", url: "/api/v1/daily-capture-report/reports" },
      { method: "GET", url: "/api/v1/system/backups" },
      { method: "POST", url: "/api/v1/memory/consolidation/run" },
    ] as const) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      expect(
        res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR,
        `${route.method} ${route.url} should be TS-owned edge, got fallback 503`,
      ).toBe(false);
    }
  });

  it("workspace, workspace-console, and deployment routes are served locally (not fallback 503)", async () => {
    const server = (app = fallbackDisabledServer());
    for (const route of [
      { method: "GET", url: "/api/v1/workspaces" },
      { method: "POST", url: "/api/v1/workspaces" },
      { method: "POST", url: "/api/v1/workspaces/scan" },
      { method: "GET", url: "/api/v1/workspaces/workspace-id" },
      { method: "PATCH", url: "/api/v1/workspaces/workspace-id" },
      { method: "DELETE", url: "/api/v1/workspaces/workspace-id" },
      { method: "GET", url: "/api/v1/workspace-console/workspaces" },
      { method: "GET", url: "/api/v1/workspace-console/workspaces/workspace-id/tree" },
      { method: "GET", url: "/api/v1/workspace-console/workspaces/workspace-id/file?path=README.md" },
      { method: "GET", url: "/api/v1/workspace-console/workspaces/workspace-id/git/status" },
      { method: "GET", url: "/api/v1/workspace-console/workspaces/workspace-id/git/diff" },
      { method: "GET", url: "/api/v1/workspace-console/runtimes" },
      { method: "GET", url: "/api/v1/workspace-console/sessions" },
      { method: "POST", url: "/api/v1/workspace-console/sessions" },
      { method: "GET", url: "/api/v1/deployments/jobs" },
      { method: "POST", url: "/api/v1/deployments/jobs" },
      { method: "GET", url: "/api/v1/deployments/jobs/job-id" },
    ] as const) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      expect(
        res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR,
        `${route.method} ${route.url} should be TS-owned edge, got fallback 503`,
      ).toBe(false);
    }
  });

  it("every known fallback-owned route still falls through to the disabled fallback", async () => {
    const server = (app = fallbackDisabledServer());
    const stillFallbackOwned: string[] = [];
    for (const route of FALLBACK_OWNED_ROUTES) {
      const res = await server.inject({ method: route.method, url: route.url });
      const error = errorCode(res);
      if (res.statusCode === 503 && error === FALLBACK_DISABLED_ERROR) {
        stillFallbackOwned.push(`${route.method} ${route.url}`);
      } else {
        // A route dropping off this list (because it became TS-owned) is good news:
        // surface it loudly so the checklist gets updated.
        expect.fail(
          `${route.method} ${route.url} no longer falls through to fallback ` +
            `(status=${res.statusCode}, error=${error}). It may be migrated — ` +
            `update FALLBACK_OWNED_ROUTES in this checklist.`,
        );
      }
    }
    // Living checklist: what still lacks an explicit TS route.
    console.log(
      `[fallback-route-checklist] ${stillFallbackOwned.length} fallback-owned route(s) remain:\n  ` +
        stillFallbackOwned.join("\n  "),
    );
    expect(stillFallbackOwned).toEqual(FALLBACK_OWNED_ROUTES.map((r) => `${r.method} ${r.url}`));
  });
});
