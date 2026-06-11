import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("TS-owned health routes", () => {
  it("GET /health returns control-plane liveness", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok", service: "control-plane" });
  });

  it("GET /api/v1/control-plane/health returns control-plane liveness", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok", service: "control-plane" });
  });

  it("does not serve the old /api/v1/gateway/health route (proxies it instead)", async () => {
    // With the legacy proxy disabled, an unowned path returns 503 rather than 200,
    // proving /api/v1/gateway/health is NOT a TS-owned route anymore.
    app = buildServer(loadConfig({ CONTROL_PLANE_ENABLE_LEGACY_PROXY: "false" }), {
      logger: false,
    });
    const res = await app.inject({ method: "GET", url: "/api/v1/gateway/health" });
    expect(res.statusCode).toBe(503);
  });
});
