import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setRunsCommandServicesFactoryForTests,
  __setRunsIdentityForTests,
  __setRunsReadResponseForTests,
} from "../src/modules/runs";
import type { RunRecord } from "../src/modules/runs/repository";

let app: FastifyInstance;

afterEach(async () => {
  __setRunsCommandServicesFactoryForTests(null);
  __setRunsIdentityForTests(null);
  __setRunsReadResponseForTests(null);
  await app?.close();
});

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "agent-version-1",
    run_type: "agent",
    status: "running",
    mode: "live",
    prompt: "Say hello",
    instruction: null,
    workspace_id: null,
    session_id: null,
    project_id: null,
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    required_sandbox_level: "none",
    trigger_origin: "manual",
    error_message: null,
    started_at: "2026-06-12T10:00:00.000Z",
    ended_at: null,
    ...overrides,
  };
}

function runsConfig() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

describe("runs command routes", () => {
  it("dispatches execute through the server run command service", async () => {
    const calls: string[] = [];
    __setRunsIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    const executeInputs: Array<Record<string, unknown>> = [];
    __setRunsCommandServicesFactoryForTests(() => ({
      repository: {
        async getRun() {
          return run({ status: "succeeded", ended_at: "2026-06-12T10:00:01.000Z" });
        },
      },
      orchestration: {
        async executeRun(input) {
          calls.push(`execute:${input.run_id}:${input.space_id}:${input.command_source}`);
          executeInputs.push(input as unknown as Record<string, unknown>);
          return { run_id: input.run_id, status: "succeeded" };
        },
        async cancelRun() {
          throw new Error("cancel should not run");
        },
      },
    }));
    app = buildServer(runsConfig(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/runs/run-1/execute?space_id=space-1",
      payload: {
        prompt: "override",
        adapter_config: { executable_path: "/tmp/attacker-binary", permission_bypass: true },
        sandbox_cwd: "/tmp/attacker-cwd",
      },
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers["x-legacy-read"]).toBeUndefined();
    expect(res.json()).toMatchObject({
      id: "run-1",
      space_id: "space-1",
      agent_id: "agent-1",
      status: "succeeded",
      mode: "live",
      resolved_model: {
        provider_id: "provider-1",
        provider_name: null,
        adapter_model_support: "uses_model",
      },
    });
    expect(calls).toEqual(["execute:run-1:space-1:http"]);
    // The Run row + policy-owned resolution are authoritative; request-body
    // execution parameters are never forwarded into orchestration.
    expect(executeInputs[0].prompt).toBeUndefined();
    expect(executeInputs[0].adapter_config).toBeUndefined();
    expect(executeInputs[0].sandbox_cwd).toBeUndefined();
  });

  it("executes via the service-authenticated internal route", async () => {
    const calls: string[] = [];
    __setRunsCommandServicesFactoryForTests(() => ({
      repository: {
        async getRun() {
          return run();
        },
      },
      orchestration: {
        async executeRun(input) {
          calls.push(`execute:${input.run_id}:${input.space_id}:${input.command_source}`);
          return { run_id: input.run_id, status: "succeeded" };
        },
        async cancelRun() {
          throw new Error("cancel should not run");
        },
      },
    }));
    app = buildServer(runsConfig(), { logger: false });

    const unauthorized = await app.inject({
      method: "POST",
      url: "/internal/runs/execute",
      payload: { run_id: "run-1", space_id: "space-1" },
    });
    expect(unauthorized.statusCode).toBe(401);

    const missingIds = await app.inject({
      method: "POST",
      url: "/internal/runs/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: { run_id: "run-1" },
    });
    expect(missingIds.statusCode).toBe(422);

    const res = await app.inject({
      method: "POST",
      url: "/internal/runs/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: { run_id: "run-1", space_id: "space-1", worker_id: "chat-worker" },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ run_id: "run-1", status: "succeeded" });
    expect(calls).toEqual(["execute:run-1:space-1:internal"]);
  });

  it("dispatches stop through the server run command service", async () => {
    const calls: string[] = [];
    __setRunsIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setRunsCommandServicesFactoryForTests(() => ({
      repository: {
        async getRun() {
          return run({ status: "cancelled", ended_at: "2026-06-12T10:00:02.000Z" });
        },
      },
      orchestration: {
        async executeRun() {
          throw new Error("execute should not run");
        },
        async cancelRun(input) {
          calls.push(`cancel:${input.run_id}:${input.space_id}:${input.requested_by_user_id}`);
          return { run_id: input.run_id, status: "cancelled", error_code: "run_cancelled" };
        },
      },
    }));
    app = buildServer(runsConfig(), { logger: false });

    const res = await app.inject({
      method: "PATCH",
      url: "/api/v1/runs/run-1/stop?space_id=space-1",
      payload: { reason: "stop" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      id: "run-1",
      status: "cancelled",
      mode: "live",
      run_type: "agent",
      trigger_origin: "manual",
      changed: true,
    });
    expect(calls).toEqual(["cancel:run-1:space-1:user-1"]);
  });

  it("serves execute through the registered route without config flags", async () => {
    __setRunsIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setRunsCommandServicesFactoryForTests(() => ({
      repository: {
        async getRun() {
          return run({ status: "succeeded", ended_at: "2026-06-12T10:00:01.000Z" });
        },
      },
      orchestration: {
        async executeRun(input) {
          return { run_id: input.run_id, status: "succeeded" };
        },
        async cancelRun() {
          throw new Error("cancel should not run");
        },
      },
    }));
    app = buildServer(loadConfig({}), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/runs/run-1/execute?space_id=space-1",
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ id: "run-1", status: "succeeded" });
  });
});
