import { describe, it, expect, afterEach, beforeEach } from "vitest";
import http from "node:http";
import { Writable } from "node:stream";
import type { AddressInfo } from "node:net";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig, type ControlPlaneConfig } from "../src/config";

interface CapturedRequest {
  method: string;
  url: string;
  headers: http.IncomingHttpHeaders;
  body: string;
  rawBody: Buffer;
}

interface MockUpstream {
  baseUrl: string;
  requests: CapturedRequest[];
  close: () => Promise<void>;
}

async function startMockUpstream(
  handler?: (req: CapturedRequest, res: http.ServerResponse) => void,
): Promise<MockUpstream> {
  const requests: CapturedRequest[] = [];
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => {
      const rawBody = Buffer.concat(chunks);
      const captured: CapturedRequest = {
        method: req.method ?? "",
        url: req.url ?? "",
        headers: req.headers,
        body: rawBody.toString("utf8"),
        rawBody,
      };
      requests.push(captured);
      if (handler) {
        handler(captured, res);
        return;
      }
      res.writeHead(200, { "content-type": "application/json", "x-upstream": "python" });
      res.end(JSON.stringify({ ok: true, seen_path: captured.url }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    baseUrl: `http://127.0.0.1:${port}`,
    requests,
    close: () =>
      new Promise<void>((resolve, reject) =>
        server.close((e) => (e ? reject(e) : resolve())),
      ),
  };
}

/** A Writable that accumulates everything the built-in logger emits. */
function captureStream(): { stream: Writable; dump: () => string } {
  let buf = "";
  const stream = new Writable({
    write(chunk, _enc, cb) {
      buf += chunk.toString();
      cb();
    },
  });
  return { stream, dump: () => buf };
}

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

beforeEach(() => {
  upstream = undefined;
});
afterEach(async () => {
  await app?.close();
  await upstream?.close();
});

function configFor(baseUrl: string, extra: Record<string, string> = {}): ControlPlaneConfig {
  return loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: baseUrl, ...extra });
}

describe("python fallback proxy", () => {
  it("forwards GET method, path and query string unchanged", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/features?scope=team&x=1" });

    expect(res.statusCode).toBe(200);
    expect(upstream.requests).toHaveLength(1);
    expect(upstream.requests[0].method).toBe("GET");
    expect(upstream.requests[0].url).toBe("/api/v1/features?scope=team&x=1");
    expect(res.json()).toEqual({ ok: true, seen_path: "/api/v1/features?scope=team&x=1" });
  });

  it("forwards POST body and content-type unchanged", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const payload = JSON.stringify({ title: "hi", n: 2 });
    const res = await app.inject({
      method: "POST",
      url: "/api/v1/workspaces",
      headers: { "content-type": "application/json" },
      payload,
    });

    expect(res.statusCode).toBe(200);
    expect(upstream!.requests[0].method).toBe("POST");
    expect(upstream!.requests[0].body).toBe(payload);
    expect(upstream!.requests[0].headers["content-type"]).toContain("application/json");
  });

  it("forwards Authorization and Cookie, and stamps control-plane + request-id headers", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/workspaces",
      headers: {
        authorization: "Bearer secret-token-123",
        cookie: "session=abc123",
        "x-request-id": "req-xyz",
        accept: "application/json",
      },
    });

    const seen = upstream!.requests[0].headers;
    expect(seen.authorization).toBe("Bearer secret-token-123");
    expect(seen.cookie).toBe("session=abc123");
    expect(seen.accept).toBe("application/json");
    expect(seen["x-agent-space-control-plane"]).toBe("ts");
    expect(seen["x-request-id"]).toBe("req-xyz"); // preserved
    expect(res.headers["x-request-id"]).toBe("req-xyz");
  });

  it("strips client hop-by-hop request headers without dropping required end-to-end headers", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/workspaces",
      headers: {
        host: "attacker.example",
        connection: "upgrade",
        "keep-alive": "timeout=5",
        "proxy-authenticate": "Basic realm=upstream",
        "proxy-authorization": "Basic secret",
        te: "trailers",
        trailer: "x-trailer",
        upgrade: "websocket",
        authorization: "Bearer secret-token-123",
        cookie: "session=abc123",
        accept: "application/json",
      },
    });

    expect(res.statusCode).toBe(200);
    const seen = upstream!.requests[0].headers;
    expect(seen.host).not.toBe("attacker.example");
    expect(seen.connection).not.toBe("upgrade");
    expect(seen["keep-alive"]).toBeUndefined();
    expect(seen["proxy-authenticate"]).toBeUndefined();
    expect(seen["proxy-authorization"]).toBeUndefined();
    expect(seen.te).toBeUndefined();
    expect(seen.trailer).toBeUndefined();
    expect(seen.upgrade).toBeUndefined();
    expect(seen.authorization).toBe("Bearer secret-token-123");
    expect(seen.cookie).toBe("session=abc123");
    expect(seen.accept).toBe("application/json");
  });

  it("preserves auth/session response headers and strips hop-by-hop response headers", async () => {
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(302, {
        "set-cookie": [
          "session_id=abc123; HttpOnly; Path=/",
          "post_login_next=/spaces; HttpOnly; Path=/",
        ],
        location: "https://auth.example/login",
        "content-type": "text/plain; charset=utf-8",
        "www-authenticate": 'Bearer realm="agent-space"',
        "cache-control": "no-cache",
        connection: "close",
        "proxy-authenticate": "Basic realm=upstream",
        upgrade: "websocket",
      });
      res.end("redirecting");
    });
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/workspaces/oauth-redirect" });

    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toBe("https://auth.example/login");
    expect(res.headers["content-type"]).toContain("text/plain");
    expect(res.headers["www-authenticate"]).toBe('Bearer realm="agent-space"');
    expect(res.headers["cache-control"]).toBe("no-cache");
    expect(res.headers["set-cookie"]).toEqual([
      "session_id=abc123; HttpOnly; Path=/",
      "post_login_next=/spaces; HttpOnly; Path=/",
    ]);
    expect(res.headers.connection).not.toBe("close");
    expect(res.headers["proxy-authenticate"]).toBeUndefined();
    expect(res.headers.upgrade).toBeUndefined();
  });

  it("generates an x-request-id when the client did not send one", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });
    await app.inject({ method: "GET", url: "/api/v1/workspaces" });
    expect(upstream!.requests[0].headers["x-request-id"]).toBeTruthy();
  });

  it("does not strip hop-by-hop request headers in a way that breaks the body", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });
    const res = await app.inject({
      method: "POST",
      url: "/api/v1/x",
      headers: { "content-type": "text/plain" },
      payload: "raw-bytes",
    });
    expect(res.statusCode).toBe(200);
    expect(upstream!.requests[0].body).toBe("raw-bytes");
  });

  it("forwards multipart upload bodies and content-type verbatim above Fastify's default body limit", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const boundary = "----agent-space-control-plane-test";
    const fileBytes = Buffer.alloc(1024 * 1024 + 16, "a");
    const prefix = Buffer.from(
      `--${boundary}\r\n` +
        'Content-Disposition: form-data; name="file"; filename="capture.txt"\r\n' +
        "Content-Type: text/plain\r\n\r\n",
      "utf8",
    );
    const suffix = Buffer.from(`\r\n--${boundary}--\r\n`, "utf8");
    const payload = Buffer.concat([prefix, fileBytes, suffix]);

    const res = await app.inject({
      method: "POST",
      url: "/api/v1/workspaces/upload",
      headers: { "content-type": `multipart/form-data; boundary=${boundary}` },
      payload,
    });

    expect(res.statusCode).toBe(200);
    expect(upstream!.requests[0].headers["content-type"]).toBe(
      `multipart/form-data; boundary=${boundary}`,
    );
    expect(upstream!.requests[0].rawBody.equals(payload)).toBe(true);
  });

  it("preserves binary download response headers and body", async () => {
    const body = "binary-payload";
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(200, {
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="artifact.bin"',
        "cache-control": "private, max-age=0",
      });
      res.end(body);
    });
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/workspaces/a1/artifact" });

    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toBe("application/octet-stream");
    expect(res.headers["content-disposition"]).toBe('attachment; filename="artifact.bin"');
    expect(res.headers["cache-control"]).toBe("private, max-age=0");
    expect(res.payload).toBe(body);
  });

  it("passes text/event-stream responses through without transforming the event body", async () => {
    const events = 'data: {"type":"output","text":"hello"}\n\n' + 'data: {"type":"done"}\n\n';
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        "x-accel-buffering": "no",
      });
      res.write(events.slice(0, 20));
      res.end(events.slice(20));
    });
    app = buildServer(configFor(upstream.baseUrl), { logger: false });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/workspaces/events/stream?runtime=claude_code",
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toContain("text/event-stream");
    expect(res.headers["cache-control"]).toBe("no-cache");
    expect(res.headers["x-accel-buffering"]).toBe("no");
    expect(res.payload).toBe(events);
  });

  it("returns a sanitized 502 when the Python backend is unavailable", async () => {
    // Point at a closed port — connection refused.
    app = buildServer(configFor("http://127.0.0.1:9"), { logger: false });
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/workspaces",
      headers: { authorization: "Bearer secret-token-123" },
    });
    expect(res.statusCode).toBe(502);
    expect(res.json()).toEqual({
      error: "python_backend_unavailable",
      message: "Python backend is unavailable",
    });
    // The error body must not echo the upstream target or the auth token.
    expect(res.payload).not.toContain("secret-token-123");
    expect(res.payload).not.toContain("127.0.0.1");
  });

  it("does not write Authorization or Cookie values to the logs (real logger)", async () => {
    upstream = await startMockUpstream();
    const cap = captureStream();
    // Use the production built-in logger (default serializers + redaction),
    // redirected to a capture stream at the most verbose level.
    app = buildServer(configFor(upstream.baseUrl), {
      logger: { level: "trace", stream: cap.stream },
    });

    await app.inject({
      method: "GET",
      url: "/api/v1/workspaces",
      headers: {
        authorization: "Bearer secret-token-123",
        cookie: "session=topsecret",
      },
    });

    // Exercise the failure log path too (proxy.warn on unavailable upstream).
    const down = buildServer(configFor("http://127.0.0.1:9"), {
      logger: { level: "trace", stream: cap.stream },
    });
    await down.inject({
      method: "GET",
      url: "/api/v1/workspaces",
      headers: { authorization: "Bearer secret-token-123" },
    });
    await down.close();

    const logged = cap.dump();
    expect(logged.length).toBeGreaterThan(0); // we did capture logs
    expect(logged).not.toContain("secret-token-123");
    expect(logged).not.toContain("topsecret");
  });

  it("returns 503 sanitized when the Python fallback proxy is disabled", async () => {
    app = buildServer(
      configFor("http://127.0.0.1:9", { CONTROL_PLANE_ENABLE_PYTHON_FALLBACK_PROXY: "false" }),
      { logger: false },
    );
    const res = await app.inject({ method: "GET", url: "/api/v1/workspaces" });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({ error: "python_fallback_proxy_disabled" });
  });

  it("serves TS-owned control-plane routes ahead of the proxy", async () => {
    upstream = await startMockUpstream();
    app = buildServer(configFor(upstream.baseUrl), { logger: false });
    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/health" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: "ok", service: "control-plane" });
    // The control-plane route must NOT have been proxied upstream.
    expect(upstream.requests).toHaveLength(0);
  });
});
