import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setProviderCommandStoreForTests,
  __setProviderHttpClientForTests,
  type ProviderCommandStore,
  type ProviderHttpClient,
} from "../src/modules/providers";

let app: FastifyInstance;

afterEach(async () => {
  __setProviderCommandStoreForTests(null);
  __setProviderHttpClientForTests(null);
  await app?.close();
});

function config() {
  return loadConfig({
    CONTROL_PLANE_PYTHON_API_BASE_URL: "http://python.test",
    CONTROL_PLANE_PROVIDERS_AUTHORITY: "ts",
    CONTROL_PLANE_PROVIDERS_CREDENTIALS_AUTHORITY: "ts",
    CONTROL_PLANE_DATABASE_URL: "postgresql://cp@db:5432/agent_space",
    CONTROL_PLANE_INTERNAL_TOKEN: "internal-token",
  });
}

function requestBody(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run-1",
    space_id: "space-1",
    model_provider_id: "provider-1",
    model: "gpt-4o-mini",
    system_prompt: "Be direct.",
    prompt: "Say hello",
    mode: "live",
    ...overrides,
  };
}

function fakeStore(calls: string[]): ProviderCommandStore {
  return {
    async getInvocationTarget(_spaceId: string, providerId?: string | null) {
      calls.push(`target:${providerId}`);
      return {
        provider: {
          id: providerId ?? "provider-1",
          space_id: "space-1",
          name: "Main",
          provider_type: "openai",
          base_url: "https://api.example.test/v1",
          default_model: "gpt-4o-mini",
          available_models: ["gpt-4o-mini"],
          enabled: true,
          is_default: true,
        },
        rotation_strategy: "fill_first",
        fallback_provider_ids: [],
        candidates: [
          {
            member_id: "member-1",
            credential_id: "credential-1",
            api_key: "sk-test-provider",
          },
        ],
      };
    },
    async recordPoolOutcome(memberId: string, outcome: { kind: string }) {
      calls.push(`outcome:${memberId}:${outcome.kind}`);
    },
    async getTaskChain(_spaceId: string, task: string) {
      calls.push(`task:${task}`);
      return null;
    },
  } as unknown as ProviderCommandStore;
}

function fakeHttpClient(calls: string[]): ProviderHttpClient {
  return {
    async fetch(_url, init) {
      calls.push(`fetch:${JSON.parse(String(init?.body)).model}`);
      return new Response(
        JSON.stringify({
          choices: [{ message: { content: "host output" } }],
          model: "gpt-4o-mini",
          usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  };
}

describe("runtime host internal route", () => {
  it("requires the internal service token", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests(fakeHttpClient(calls));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      payload: requestBody(),
    });

    expect(res.statusCode).toBe(401);
    expect(calls).toEqual([]);
  });

  it("executes a provider-backed tool-disabled host turn", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests(fakeHttpClient(calls));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({ max_tokens: 64 }),
    });

    expect(res.statusCode).toBe(200);
    expect(res.payload).not.toContain("sk-test-provider");
    expect(res.json()).toMatchObject({
      success: true,
      stdout: "host output",
      output_text: "host output",
      model: "gpt-4o-mini",
      usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5 },
      adapter_metadata: {
        adapter_type: "ts_agent_host",
        model_provider_id: "provider-1",
        tool_mode: "disabled",
      },
    });
    expect(res.json().events.map((event: { type: string }) => event.type)).toEqual([
      "model.message_start",
      "model.text_delta",
      "model.usage",
      "model.message_stop",
    ]);
    expect(calls).toEqual([
      "task:runtime_host",
      "target:provider-1",
      "fetch:gpt-4o-mini",
      "outcome:member-1:success",
    ]);
  });

  it("fails closed for tool execution until the tool scheduler is implemented", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests(fakeHttpClient(calls));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({ tool_mode: "authorized_bindings" }),
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: false,
      error_code: "runtime_tools_not_implemented",
      exit_code: 1,
    });
    expect(calls).toEqual([]);
  });

  it("advertises the runtime host only with TS credential authority", async () => {
    app = buildServer(config(), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/control-plane/features" });

    expect(res.statusCode).toBe(200);
    expect((res.json() as { features: string[] }).features).toContain(
      "ts_agent_runtime_host",
    );
  });
});
