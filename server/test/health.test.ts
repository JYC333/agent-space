import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";

let app: FastifyInstance;

afterEach(async () => {
  await app?.close();
});

describe("server-owned health routes", () => {
  it("GET /health returns server liveness", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok", service: "server" });
  });

  it("GET /api/v1/server/health returns server liveness", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/server/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok", service: "server" });
  });

  it("does not serve the old /api/v1/gateway/health route", async () => {
    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/gateway/health" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ detail: "Route not found" });
  });
});
