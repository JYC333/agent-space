import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";
import { frontendSupportModule } from "../src/modules/frontendSupport";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

afterEach(async () => {
  await app?.close();
  const current = upstream;
  upstream = undefined;
  await current?.close();
});

describe("frontend-support read model facades", () => {
  it("registers as a TS-owned module", () => {
    expect(frontendSupportModule.name).toBe("frontend_support");
    expect(TS_OWNED_MODULES).toContain(frontendSupportModule);
  });

  it("forwards home, me, and workspace-console read models through the explicit Python port", async () => {
    upstream = await startMockUpstream();
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const requests = [
      "/api/v1/home/summary?space_id=personal&user_id=default_user",
      "/api/v1/me/summary",
      "/api/v1/workspace-console/workspaces?space_id=personal",
    ];
    for (const url of requests) {
      const res = await app.inject({
        method: "GET",
        url,
        headers: {
          authorization: "Bearer token-123",
          cookie: "session=abc",
          "x-request-id": "req-read-model",
        },
      });
      expect(res.statusCode).toBe(200);
      expect(res.headers["x-upstream"]).toBe("python");
      expect(res.json()).toEqual({ ok: true, seen_path: url });
    }

    expect(upstream.requests.map((r) => r.url)).toEqual(requests);
    expect(upstream.requests[0].headers.authorization).toBe("Bearer token-123");
    expect(upstream.requests[0].headers.cookie).toBe("session=abc");
    expect(upstream.requests[0].headers["x-agent-space-control-plane"]).toBe("ts");
    expect(upstream.requests[0].headers["x-request-id"]).toBe("req-read-model");
  });

  it("returns a sanitized TS error envelope on Python transport failure", async () => {
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: "http://127.0.0.1:9" }), {
      logger: false,
    });
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/home/summary",
      headers: { authorization: "Bearer secret-token-123", "x-request-id": "req-down" },
    });

    expect(res.statusCode).toBe(502);
    expect(res.json()).toEqual({
      error: "python_authority_unavailable",
      message: "Python authority is unavailable",
      request_id: "req-down",
    });
    expect(res.payload).not.toContain("secret-token-123");
    expect(res.payload).not.toContain("127.0.0.1");
  });
});
