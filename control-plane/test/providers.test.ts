import { describe, it, expect, afterEach } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import { TS_OWNED_MODULES } from "../src/gateway/routeRegistry";
import { providersModule } from "../src/modules/providers";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

let app: FastifyInstance;
let upstream: MockUpstream | undefined;

afterEach(async () => {
  await app?.close();
  const current = upstream;
  upstream = undefined;
  await current?.close();
});

function provider(id: string) {
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
  };
}

describe("providers read-only facade", () => {
  it("registers as a TS-owned module and advertises the feature", async () => {
    expect(providersModule.name).toBe("providers");
    expect(TS_OWNED_MODULES).toContain(providersModule);

    app = buildServer(loadConfig({}), { logger: false });
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/control-plane/features",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().features).toContain("providers_readonly_python_facade");
  });

  it("forwards provider list and detail reads through Python authority", async () => {
    upstream = await startMockUpstream((req, res) => {
      res.writeHead(200, { "content-type": "application/json", "x-upstream": "python" });
      if (req.url.startsWith("/api/v1/providers/mp-1")) {
        res.end(JSON.stringify(provider("mp-1")));
        return;
      }
      res.end(JSON.stringify([provider("mp-1"), provider("mp-2")]));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const list = await app.inject({
      method: "GET",
      url: "/api/v1/providers?space_id=space-1",
      headers: {
        authorization: "Bearer token-123",
        cookie: "session=abc",
        "x-request-id": "req-providers",
      },
    });
    expect(list.statusCode).toBe(200);
    expect(list.headers["x-upstream"]).toBe("python");
    expect(list.json()).toHaveLength(2);

    const detail = await app.inject({
      method: "GET",
      url: "/api/v1/providers/mp-1?space_id=space-1",
      headers: { "x-request-id": "req-provider-detail" },
    });
    expect(detail.statusCode).toBe(200);
    expect(detail.json().id).toBe("mp-1");

    expect(upstream.requests.map((r) => r.url)).toEqual([
      "/api/v1/providers?space_id=space-1",
      "/api/v1/providers/mp-1?space_id=space-1",
    ]);
    expect(upstream.requests[0].headers.authorization).toBe("Bearer token-123");
    expect(upstream.requests[0].headers.cookie).toBe("session=abc");
    expect(upstream.requests[0].headers["x-agent-space-control-plane"]).toBe("ts");
    expect(upstream.requests[0].headers["x-request-id"]).toBe("req-providers");
  });

  it("forwards the static catalog and litellm-providers reads with their own shapes", async () => {
    const catalogInfo = {
      id: "litellm",
      name: "LiteLLM (Open Format)",
      description: "Configure OpenAI, Anthropic, OpenRouter, Ollama, or custom endpoints.",
      model_hint: "Set default_model and/or available_models on the provider",
      supported_params: ["model", "temperature", "max_tokens", "system"],
    };
    upstream = await startMockUpstream((req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      if (req.url.startsWith("/api/v1/providers/litellm-providers")) {
        res.end(JSON.stringify(["openai", "anthropic", "openrouter"]));
        return;
      }
      res.end(JSON.stringify(catalogInfo));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    // Before the static claims, the parametric :configId route swallowed these
    // paths and mis-validated their payloads as provider DTOs (502).
    const catalog = await app.inject({
      method: "GET",
      url: "/api/v1/providers/catalog?space_id=space-1",
    });
    expect(catalog.statusCode).toBe(200);
    expect(catalog.json()).toEqual(catalogInfo);

    const litellm = await app.inject({
      method: "GET",
      url: "/api/v1/providers/litellm-providers?space_id=space-1",
    });
    expect(litellm.statusCode).toBe(200);
    expect(litellm.json()).toEqual(["openai", "anthropic", "openrouter"]);

    expect(upstream.requests.map((r) => r.url)).toEqual([
      "/api/v1/providers/catalog?space_id=space-1",
      "/api/v1/providers/litellm-providers?space_id=space-1",
    ]);
  });

  it("rejects secret material leaking through the static catalog read", async () => {
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          id: "litellm",
          name: "LiteLLM",
          description: "d",
          model_hint: "m",
          supported_params: [],
          api_key: "sk-should-not-leak",
        }),
      );
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({ method: "GET", url: "/api/v1/providers/catalog" });
    expect(res.statusCode).toBe(502);
    expect(res.json().error).toBe("provider_contract_violation");
    expect(res.payload).not.toContain("sk-should-not-leak");
  });

  it("passes Python read authorization failures through before validating", async () => {
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "not found" }));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/providers/mp-missing?space_id=space-1",
    });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toEqual({ detail: "not found" });
  });

  it("returns a sanitized error when Python 2xx violates the read contract", async () => {
    upstream = await startMockUpstream((_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ id: "mp-1", api_key: "sk-should-not-leak" }));
    });
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const res = await app.inject({
      method: "GET",
      url: "/api/v1/providers/mp-1",
      headers: { "x-request-id": "req-invalid-provider" },
    });
    expect(res.statusCode).toBe(502);
    expect(res.json()).toEqual({
      error: "provider_contract_violation",
      message: "Python provider response violated the provider read contract",
      request_id: "req-invalid-provider",
    });
    expect(res.payload).not.toContain("sk-should-not-leak");
    expect(res.payload).not.toContain("api_key");
  });

  it("does not claim provider write routes", async () => {
    upstream = await startMockUpstream();
    app = buildServer(loadConfig({ CONTROL_PLANE_PYTHON_API_BASE_URL: upstream.baseUrl }), {
      logger: false,
    });

    const payload = JSON.stringify({ name: "Main", provider_type: "openai" });
    const res = await app.inject({
      method: "POST",
      url: "/api/v1/providers",
      headers: { "content-type": "application/json" },
      payload,
    });

    expect(res.statusCode).toBe(200);
    expect(upstream.requests[0].method).toBe("POST");
    expect(upstream.requests[0].url).toBe("/api/v1/providers");
    expect(upstream.requests[0].body).toBe(payload);
  });
});
