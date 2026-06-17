import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { SERVER_MODULES } from "../src/gateway/routeRegistry";
import { frontendSupportModule } from "../src/modules/frontendSupport";
import { __setAuthIdentityForTests } from "../src/modules/auth";
import { __setFrontendSupportServiceFactoryForTests } from "../src/modules/frontendSupport/routes";

let app: FastifyInstance;

afterEach(async () => {
  __setAuthIdentityForTests(null);
  __setFrontendSupportServiceFactoryForTests(null);
  await app?.close();
});

describe("frontend-support read models", () => {
  it("registers as a server-owned module", () => {
    expect(frontendSupportModule.name).toBe("frontend_support");
    expect(SERVER_MODULES).toContain(frontendSupportModule);
  });

  it("serves home as space-scoped and me as user-wide native read models", async () => {
    __setAuthIdentityForTests({ spaceId: "space-active", userId: "user-1" });
    const calls: Array<{ method: string; args: unknown[] }> = [];
    __setFrontendSupportServiceFactoryForTests(() => ({
      async homeSummary(identity: unknown, query: unknown) {
        calls.push({ method: "homeSummary", args: [identity, query] });
        return emptyHomeSummary();
      },
      async meSummary(userId: unknown, query: unknown) {
        calls.push({ method: "meSummary", args: [userId, query] });
        return {
          pending_proposals_count: 0,
          assigned_tasks_count: 0,
          recent_runs: [],
          recent_participation: [],
          accessible_spaces_count: 0,
          spaces: [],
        };
      },
      async meTimeline(userId: unknown, query: unknown) {
        calls.push({ method: "meTimeline", args: [userId, query] });
        return [];
      },
      async mePending(userId: unknown, query: unknown) {
        calls.push({ method: "mePending", args: [userId, query] });
        return [];
      },
    }));
    app = buildServer(loadConfig({}), { logger: false });

    for (const url of [
      "/api/v1/home/summary?recent_runs_limit=3",
      "/api/v1/me/summary?space_id=ignored&recent_runs_limit=4",
      "/api/v1/me/timeline?limit=5",
      "/api/v1/me/pending?limit=6",
    ]) {
      const res = await app.inject({ method: "GET", url });
      expect(res.statusCode).toBe(200);
    }

    expect(calls.map((call) => call.method)).toEqual([
      "homeSummary",
      "meSummary",
      "meTimeline",
      "mePending",
    ]);
    expect(calls[0].args[0]).toEqual({ spaceId: "space-active", userId: "user-1" });
    expect(calls[1].args[0]).toBe("user-1");
    expect(calls[2].args[0]).toBe("user-1");
    expect(calls[3].args[0]).toBe("user-1");
  });

});

function emptyHomeSummary() {
  return {
    recent_runs: [],
    active_runs: [],
    pending_proposals: { count: 0, items: [] },
    recent_artifacts: [],
    task_summary: {
      by_status: {},
      total_open: 0,
      needs_review_count: 0,
      blocked_count: 0,
      done_count: 0,
    },
    active_tasks: [],
    activity_summary: { recent_count: 0, raw_count: 0, today_count: 0 },
    run_stats_today: {
      created: 0,
      queued: 0,
      running: 0,
      succeeded: 0,
      failed: 0,
      cancelled: 0,
      dry_run_count: 0,
    },
    job_queue_status: {
      queued: 0,
      running: 0,
      failed: 0,
      retryable: 0,
      recent_error_preview: null,
    },
    runtime_status: {
      real_adapters_configured_count: 0,
      configured_adapter_types: [],
      message: "No runtime adapters configured.",
    },
    model_provider_status: {
      model_providers_count: 0,
      enabled_model_providers_count: 0,
      missing_model_provider_config: true,
      message: "No enabled model providers configured.",
    },
    suggested_actions: [],
    intake_summary: {
      open_items: 0,
      new_items_today: 0,
      pending_extraction_jobs: 0,
      failed_extraction_jobs: 0,
      candidate_evidence: 0,
      active_evidence: 0,
      due_connections: 0,
    },
  };
}
