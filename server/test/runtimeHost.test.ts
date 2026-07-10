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
import type { UsageObservation } from "../src/modules/usage";
import { resolveTestUsageAttribution } from "./support/usageAttribution";

let app: FastifyInstance;

afterEach(async () => {
  __setProviderCommandStoreForTests(null);
  __setProviderHttpClientForTests(null);
  await app?.close();
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
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

function fakeStore(
  calls: string[],
  providerType = "openai",
  usageObservations: UsageObservation[] = [],
): ProviderCommandStore {
  return {
    async getInvocationTarget(_spaceId: string, providerId?: string | null) {
      calls.push(`target:${providerId}`);
      return {
        provider: {
          id: providerId ?? "provider-1",
          space_id: "space-1",
          name: "Main",
          provider_type: providerType,
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
    resolveUsageAttribution: resolveTestUsageAttribution,
    async recordUsageObservation(input: UsageObservation) {
      usageObservations.push(input);
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
    const usageObservations: UsageObservation[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls, "openai", usageObservations));
    __setProviderHttpClientForTests(fakeHttpClient(calls));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        max_tokens: 64,
        session_id: "session-1",
        root_run_id: "root-1",
        parent_run_id: "parent-1",
        run_group_id: "group-1",
        agent_id: "agent-1",
        project_id: "project-1",
        workspace_id: "workspace-1",
        trigger_origin: "manual",
      }),
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
    expect(usageObservations).toEqual([
      expect.objectContaining({
        space_id: "space-1",
        event_type: "llm.generation",
        source_type: "local_run",
        execution_channel: "managed_api",
        meter_subject_type: "run",
        meter_subject_id: "run-1",
        run_id: "run-1",
        root_run_id: "root-1",
        parent_run_id: "parent-1",
        run_group_id: "group-1",
        session_id: "session-1",
        agent_id: "agent-1",
        project_id: "project-1",
        workspace_id: "workspace-1",
        trigger_origin: "manual",
        adapter_type: "ts_agent_host",
        provider_id: "provider-1",
        provider_type: "openai",
        provider_name_snapshot: "Main",
        model: "gpt-4o-mini",
        task: "runtime_host",
        provider_usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
        usage_accuracy: "provider_reported",
        dimensions: { mode: "live", tool_mode: "disabled" },
      }),
    ]);
  });

  it("returns provider network errors instead of a generic runtime host failure", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests({
      async fetch(_url, init) {
        calls.push(`fetch:${JSON.parse(String(init?.body)).model}`);
        const error = new Error("fetch failed") as Error & { cause?: Error };
        error.cause = new Error("getaddrinfo ENOTFOUND api.example.test");
        throw error;
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody(),
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: false,
      error_code: "provider_network_error",
      exit_code: 1,
    });
    expect(res.json().error_text).toContain("Provider network request failed");
    expect(res.json().error_text).toContain("getaddrinfo ENOTFOUND api.example.test");
    expect(res.json().error_text).not.toContain("server runtime host provider invocation failed");
    expect(calls).toEqual([
      "task:runtime_host",
      "target:provider-1",
      "fetch:gpt-4o-mini",
      "fetch:gpt-4o-mini",
      "outcome:member-1:failure",
    ]);
  });

  it("forwards native messages to the provider when supplied", async () => {
    const calls: string[] = [];
    const bodies: Array<Record<string, unknown>> = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests({
      async fetch(_url, init) {
        bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return new Response(
          JSON.stringify({
            choices: [{ message: { content: "native output" } }],
            model: "gpt-4o-mini",
            usage: { prompt_tokens: 7, completion_tokens: 2, total_tokens: 9 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        prompt: "fallback prompt",
        messages: [
          { role: "user", content: "Earlier question" },
          { role: "assistant", content: "Earlier answer" },
          { role: "user", content: "Continue" },
        ],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ success: true, output_text: "native output" });
    expect(bodies[0]).toMatchObject({
      messages: [
        { role: "system", content: "Be direct." },
        { role: "user", content: "Earlier question" },
        { role: "assistant", content: "Earlier answer" },
        { role: "user", content: "Continue" },
      ],
    });
    expect(JSON.stringify(bodies[0])).not.toContain("fallback prompt");
  });

  it("rejects tool definitions when tool mode is disabled", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests(fakeHttpClient(calls));
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        tool_mode: "disabled",
        tools: [{ name: "retrieval.search", input_schema: { type: "object" } }],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: false,
      error_code: "runtime_tools_disabled",
      exit_code: 1,
    });
    expect(calls).toEqual([]);
  });

  it("passes authorized tool definitions to OpenAI-compatible providers and returns tool calls", async () => {
    const calls: string[] = [];
    const bodies: Array<Record<string, unknown>> = [];
    __setProviderCommandStoreForTests(fakeStore(calls));
    __setProviderHttpClientForTests({
      async fetch(_url, init) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        bodies.push(body);
        return new Response(
          JSON.stringify({
            choices: [
              {
                finish_reason: "tool_calls",
                message: {
                  content: null,
                  tool_calls: [
                    {
                      id: "call-1",
                      type: "function",
                      function: {
                        name: "retrieval_search",
                        arguments: "{\"query\":\"alpha\"}",
                      },
                    },
                  ],
                },
              },
            ],
            model: "gpt-4o-mini",
            usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        tool_mode: "authorized_bindings",
        tools: [
          {
            name: "retrieval.search",
            description: "Search knowledge",
            input_schema: { type: "object", properties: { query: { type: "string" } } },
          },
        ],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(bodies[0]).toMatchObject({
      tool_choice: "auto",
      tools: [
        {
          type: "function",
          function: { name: "retrieval_search" },
        },
      ],
    });
    expect(res.json()).toMatchObject({
      success: true,
      output_json: {
        tool_calls: [
          {
            id: "call-1",
            name: "retrieval.search",
            arguments_json: "{\"query\":\"alpha\"}",
          },
        ],
      },
      adapter_metadata: {
        tool_mode: "authorized_bindings",
        tool_count: 1,
      },
    });
    expect(res.json().events.map((event: { type: string }) => event.type)).toEqual([
      "model.message_start",
      "model.tool_call_delta",
      "model.usage",
      "model.message_stop",
    ]);
  });

  it("passes authorized tool definitions to Anthropic providers and returns tool_use calls", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls, "anthropic"));
    const bodies: Array<Record<string, unknown>> = [];
    __setProviderHttpClientForTests({
      async fetch(_url, init) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        bodies.push(body);
        return new Response(
          JSON.stringify({
            content: [
              { type: "text", text: "I should search first." },
              {
                type: "tool_use",
                id: "toolu_1",
                name: "retrieval_search",
                input: { query: "alpha" },
              },
            ],
            model: "claude-3-5-sonnet-latest",
            stop_reason: "tool_use",
            usage: { input_tokens: 3, output_tokens: 2 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        model: "claude-3-5-sonnet-latest",
        tool_mode: "authorized_bindings",
        tools: [
          {
            name: "retrieval.search",
            description: "Search knowledge",
            input_schema: { type: "object", properties: { query: { type: "string" } } },
          },
        ],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(bodies[0]).toMatchObject({
      model: "claude-3-5-sonnet-latest",
      tool_choice: { type: "auto" },
      tools: [
        {
          name: "retrieval_search",
          input_schema: { type: "object", properties: { query: { type: "string" } } },
        },
      ],
      messages: [{ role: "user", content: "Say hello" }],
    });
    expect(res.json()).toMatchObject({
      success: true,
      output_text: "I should search first.",
      output_json: {
        tool_calls: [
          {
            id: "toolu_1",
            name: "retrieval.search",
            arguments_json: "{\"query\":\"alpha\"}",
          },
        ],
      },
      adapter_metadata: {
        tool_mode: "authorized_bindings",
        tool_count: 1,
      },
    });
    expect(res.json().events.map((event: { type: string }) => event.type)).toEqual([
      "model.message_start",
      "model.text_delta",
      "model.tool_call_delta",
      "model.usage",
      "model.message_stop",
    ]);
  });

  it("formats Anthropic tool results as immediately-following user tool_result blocks", async () => {
    const calls: string[] = [];
    const bodies: Array<Record<string, unknown>> = [];
    __setProviderCommandStoreForTests(fakeStore(calls, "anthropic"));
    __setProviderHttpClientForTests({
      async fetch(_url, init) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        bodies.push(body);
        return new Response(
          JSON.stringify({
            content: [{ type: "text", text: "final answer" }],
            model: "claude-3-5-sonnet-latest",
            stop_reason: "end_turn",
            usage: { input_tokens: 8, output_tokens: 3 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        model: "claude-3-5-sonnet-latest",
        messages: [
          { role: "user", content: "Find alpha" },
          {
            role: "assistant",
            content: null,
            tool_calls: [
              {
                id: "toolu_1",
                name: "retrieval.search",
                arguments_json: "{\"query\":\"alpha\"}",
              },
            ],
          },
          {
            role: "tool",
            tool_call_id: "toolu_1",
            name: "retrieval.search",
            content: "{\"ok\":true}",
          },
        ],
        tool_mode: "authorized_bindings",
        tools: [
          {
            name: "retrieval.search",
            description: "Search knowledge",
            input_schema: { type: "object", properties: { query: { type: "string" } } },
          },
        ],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(bodies[0]).toMatchObject({
      messages: [
        { role: "user", content: "Find alpha" },
        {
          role: "assistant",
          content: [
            {
              type: "tool_use",
              id: "toolu_1",
              name: "retrieval_search",
              input: { query: "alpha" },
            },
          ],
        },
        {
          role: "user",
          content: [
            {
              type: "tool_result",
              tool_use_id: "toolu_1",
              content: "{\"ok\":true}",
            },
          ],
        },
      ],
    });
    expect(res.json()).toMatchObject({
      success: true,
      output_text: "final answer",
      output_json: {},
    });
  });

  it("fails explicitly when authorized tools target an unsupported provider type", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(fakeStore(calls, "ollama"));
    __setProviderHttpClientForTests({
      async fetch() {
        throw new Error("unsupported provider should not receive tool request");
      },
    });
    app = buildServer(config(), { logger: false });

    const res = await app.inject({
      method: "POST",
      url: "/internal/runtime-host/execute",
      headers: { "x-agent-space-internal-token": "internal-token" },
      payload: requestBody({
        tool_mode: "authorized_bindings",
        tools: [
          {
            name: "retrieval.search",
            description: "Search knowledge",
            input_schema: { type: "object", properties: { query: { type: "string" } } },
          },
        ],
      }),
    });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      success: false,
      // Specific code so the managed-run tool loop can degrade to a no-tool turn.
      error_code: "runtime_tool_provider_unsupported",
      exit_code: 1,
    });
    expect(res.json().error_text).toContain("does not support runtime-host tools");
    expect(calls).toEqual([
      "task:runtime_host",
      "target:provider-1",
      "outcome:member-1:failure",
    ]);
  });

  it("advertises the runtime host only with server credential authority", async () => {
    app = buildServer(config(), { logger: false });

    const res = await app.inject({ method: "GET", url: "/api/v1/server/features" });

    expect(res.statusCode).toBe(200);
    expect((res.json() as { features: string[] }).features).toContain(
      "server_agent_runtime_host",
    );
  });
});
