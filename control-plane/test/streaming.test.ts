import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";
import { streamingModule, RUN_EVENT_APPENDED_TYPE } from "../src/modules/streaming";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

afterEach(async () => {
  await app?.close();
  const current = upstream;
  upstream = undefined;
  await current?.close();
});

function runEvent(index: number) {
  return {
    id: `event-${index}`,
    space_id: "personal",
    run_id: "run-1",
    event_index: index,
    event_type: "adapter_completed",
    status: "succeeded",
    step_id: null,
    actor_id: null,
    summary: `event ${index}`,
    error_code: null,
    error_message: null,
    artifact_id: null,
    proposal_id: null,
    created_at: `2026-06-11T12:00:0${index}Z`,
  };
}

function parseSseEvents(payload: string): Array<{ id?: string; event?: string; data: unknown }> {
  return payload
    .split("\n\n")
    .map((block) => block.trim())
    .filter((block) => block.includes("data: "))
    .map((block) => {
      const lines = block.split("\n");
      const idLine = lines.find((line) => line.startsWith("id: "));
      const eventLine = lines.find((line) => line.startsWith("event: "));
      const dataLine = lines.find((line) => line.startsWith("data: "));
      return {
        id: idLine?.slice(4),
        event: eventLine?.slice(7),
        data: JSON.parse(dataLine?.slice(6) ?? "null") as unknown,
      };
    });
}

describe("run-event SSE streaming edge", () => {
  it("registers as a TS-owned module", () => {
    expect(streamingModule.name).toBe("streaming");
    expect(TS_OWNED_MODULES).toContain(streamingModule);
  });

  it("replays Python run events as canonical SSE envelopes", async () => {
    const events = [runEvent(0), runEvent(1)];
    upstream = await startMockUpstream((req, res) => {
      expect(req.url).toBe("/api/v1/runs/run-1/events?offset=0&limit=100&space_id=personal");
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ items: events, total: 2, limit: 100, offset: 0 }));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/runs/run-1/events/stream?space_id=personal&tail=false",
      headers: { "x-request-id": "req-stream" },
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toContain("text/event-stream");
    expect(res.headers["x-request-id"]).toBe("req-stream");
    const blocks = parseSseEvents(res.payload);
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ id: "0", event: RUN_EVENT_APPENDED_TYPE });
    expect(blocks[0].data).toEqual({
      event_id: "event-0",
      type: RUN_EVENT_APPENDED_TYPE,
      occurred_at: "2026-06-11T12:00:00Z",
      space_id: "personal",
      payload: { event: events[0] },
    });
    expect(upstream.requests[0].headers["x-agent-space-control-plane"]).toBe("ts");
  });

  it("uses Last-Event-ID to resume at the next run event index", async () => {
    upstream = await startMockUpstream((req, res) => {
      expect(req.url).toBe("/api/v1/runs/run-1/events?offset=3&limit=100");
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ items: [], total: 3, limit: 100, offset: 3 }));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/runs/run-1/events/stream?tail=false",
      headers: { "last-event-id": "2" },
    });

    expect(res.statusCode).toBe(200);
    expect(parseSseEvents(res.payload)).toEqual([]);
  });

  it("passes Python authorization failures through before opening SSE", async () => {
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "Run not found" }));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/runs/missing/events/stream?tail=false",
    });

    expect(res.statusCode).toBe(404);
    expect(res.headers["content-type"]).toContain("application/json");
    expect(res.json()).toEqual({ detail: "Run not found" });
  });
});
