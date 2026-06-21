import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  executeManagedApiNoToolAdapter,
  type RuntimeHostExecutor,
} from "../src/modules/runs/managedApiAdapter";
import type { RunRecord } from "../src/modules/runs/repository";
import {
  __setProviderCommandStoreForTests,
  __setProviderHttpClientForTests,
  type ProviderCommandStore,
  type ProviderHttpClient,
} from "../src/modules/providers";

afterEach(() => {
  __setProviderCommandStoreForTests(null);
  __setProviderHttpClientForTests(null);
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
  });
}

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    space_id: "space-1",
    agent_id: "agent-1",
    agent_version_id: "agent-version-1",
    status: "running",
    mode: "live",
    prompt: "Say hello",
    instruction: "Be concise.",
    workspace_id: null,
    session_id: null,
    project_id: null,
    adapter_type: "model_api",
    model_provider_id: "provider-1",
    required_sandbox_level: "none",
    trigger_origin: "manual",
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

describe("executeManagedApiNoToolAdapter", () => {
  it("builds an explicit no-tool runtime-host request and maps success", async () => {
    const calls: unknown[] = [];
    const executor: RuntimeHostExecutor = async (_config, request) => {
      calls.push(request);
      return {
        success: true,
        stdout: "host output",
        stderr: "",
        output_text: "host output",
        output_json: { adapter_type: "ts_agent_host", stdout: "raw" },
        exit_code: 0,
        error_text: null,
        error_code: null,
        started_at: "2026-06-12T10:00:00.000Z",
        completed_at: "2026-06-12T10:00:01.000Z",
        model: "gpt-4o-mini",
        usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5 },
        events: [],
        adapter_metadata: { adapter_type: "ts_agent_host" },
        adapter_log_json: null,
      };
    };

    const result = await executeManagedApiNoToolAdapter(
      config(),
      { run: run(), model: "gpt-4o-mini", max_tokens: 64 },
      { executeRuntimeHost: executor },
    );

    expect(calls).toEqual([
      {
        run_id: "run-1",
        space_id: "space-1",
        model_provider_id: "provider-1",
        model: "gpt-4o-mini",
        system_prompt: "Be concise.",
        prompt: "Say hello",
        mode: "live",
        instruction: "Be concise.",
        project_id: null,
        workspace_id: null,
        capability_id: null,
        context_snapshot_id: null,
        max_tokens: 64,
        tool_mode: "disabled",
        tool_bindings: [],
      },
    ]);
    expect(result).toMatchObject({
      adapter_type: "model_api",
      adapter_kind: "managed_api",
      success: true,
      output_text: "host output",
      exit_code: 0,
      usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5 },
      metadata_json: {
        adapter_type: "model_api",
        runtime_host_adapter_type: "ts_agent_host",
        model_provider_id: "provider-1",
      },
    });
    expect(result.output_json).toEqual({
      adapter_type: "model_api",
      stdout: "[REDACTED_EVIDENCE_FIELD]",
      model: "gpt-4o-mini",
      usage: { input_tokens: 3, output_tokens: 2, total_tokens: 5 },
    });
  });

  it("passes native chat messages to runtime-host for managed API runs", async () => {
    const calls: unknown[] = [];
    const executor: RuntimeHostExecutor = async (_config, request) => {
      calls.push(request);
      return {
        success: true,
        stdout: "ok",
        stderr: "",
        output_text: "ok",
        output_json: { adapter_type: "ts_agent_host" },
        exit_code: 0,
        error_text: null,
        error_code: null,
        started_at: "2026-06-12T10:00:00.000Z",
        completed_at: "2026-06-12T10:00:01.000Z",
        model: "gpt-4o-mini",
        usage: null,
        events: [],
        adapter_metadata: { adapter_type: "ts_agent_host" },
        adapter_log_json: null,
      };
    };

    await executeManagedApiNoToolAdapter(
      config(),
      {
        run: run({
          model_override_json: {
            chat_context_preamble: "Relevant memory.",
            messages: [
              { role: "user", content: "Earlier question" },
              { role: "assistant", content: "Earlier answer" },
              { role: "user", content: "Continue" },
            ],
          },
        }),
        model: "gpt-4o-mini",
      },
      { executeRuntimeHost: executor },
    );

    expect(calls).toEqual([
      expect.objectContaining({
        system_prompt: "Be concise.\n\nRelevant memory.",
        prompt: "Say hello",
        messages: [
          { role: "user", content: "Earlier question" },
          { role: "assistant", content: "Earlier answer" },
          { role: "user", content: "Continue" },
        ],
      }),
    ]);
  });

  // Policy enforcement (runtime.execute / runtime.use_credential) lives upstream
  // in RunOrchestrationService.enforceRuntimePolicy — see
  // runOrchestrationService.test.ts "fails closed before adapter invocation when
  // policy denies". The adapter no longer carries its own policy seam.

  it("fails before runtime-host invocation without an explicit provider grant", async () => {
    const calls: unknown[] = [];

    const result = await executeManagedApiNoToolAdapter(
      config(),
      { run: run({ model_provider_id: null }) },
      {
        executeRuntimeHost: async (_config, request) => {
          calls.push(request);
          throw new Error("runtime host should not run");
        },
      },
    );

    expect(calls).toEqual([]);
    expect(result).toMatchObject({
      success: false,
      error_code: "model_provider_required",
      adapter_type: "model_api",
    });
  });

  it("maps runtime-host failures into managed adapter failures", async () => {
    const result = await executeManagedApiNoToolAdapter(
      config(),
      { run: run({ adapter_type: "ts_agent_host" }) },
      {
        executeRuntimeHost: async () => ({
          success: false,
          stdout: "",
          stderr: "bad",
          output_text: "",
          output_json: { adapter_type: "ts_agent_host" },
          exit_code: 1,
          error_text: "provider token=secret failed",
          error_code: "provider_invocation_failed",
          started_at: "2026-06-12T10:00:00.000Z",
          completed_at: "2026-06-12T10:00:01.000Z",
          model: null,
          usage: null,
          events: [],
          adapter_metadata: { adapter_type: "ts_agent_host" },
          adapter_log_json: null,
        }),
      },
    );

    expect(result).toMatchObject({
      adapter_type: "ts_agent_host",
      success: false,
      error_code: "provider_invocation_failed",
      error_message: "provider [REDACTED_SECRET] failed",
    });
  });

  it("does not send provider HTTP requests when credentials are unavailable", async () => {
    const calls: string[] = [];
    __setProviderCommandStoreForTests(emptyCredentialStore(calls));
    __setProviderHttpClientForTests(fakeHttpClient(calls));

    const result = await executeManagedApiNoToolAdapter(config(), {
      run: run(),
      model: "gpt-4o-mini",
    });

    expect(result).toMatchObject({
      success: false,
      error_code: "provider_invocation_failed",
      exit_code: 1,
    });
    expect(calls).toEqual(["task:runtime_host", "target:provider-1"]);
  });
});

function emptyCredentialStore(calls: string[]): ProviderCommandStore {
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
        candidates: [],
      };
    },
    async recordPoolOutcome() {
      calls.push("outcome");
    },
    async getTaskChain(_spaceId: string, task: string) {
      calls.push(`task:${task}`);
      return null;
    },
  } as unknown as ProviderCommandStore;
}

function fakeHttpClient(calls: string[]): ProviderHttpClient {
  return {
    async fetch() {
      calls.push("fetch");
      return new Response("{}", { status: 200 });
    },
  };
}
