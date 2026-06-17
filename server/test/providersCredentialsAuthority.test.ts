import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildServer } from "../src/server";
import { loadConfig } from "../src/config";
import {
  __setProviderCommandStoreForTests,
  __setProviderHttpClientForTests,
  type ProviderCommandStore,
} from "../src/modules/providers";
import { __setAuthIdentityForTests } from "../src/modules/auth";

let app: FastifyInstance;
let tempHome: string | undefined;

afterEach(async () => {
  __setProviderCommandStoreForTests(null);
  __setProviderHttpClientForTests(null);
  __setAuthIdentityForTests(null);
  await app?.close();
  if (tempHome) await rm(tempHome, { recursive: true, force: true });
  tempHome = undefined;
});

function providerDto(overrides: Record<string, unknown> = {}) {
  return {
    id: "provider-1",
    space_id: "space-1",
    name: "Main",
    provider_type: "openai",
    base_url: null,
    default_model: "gpt-4o-mini",
    available_models: ["gpt-4o-mini"],
    enabled: true,
    is_default: true,
    has_api_key: true,
    created_at: "2026-06-11T12:00:00.000Z",
    updated_at: "2026-06-11T12:00:00.000Z",
    ...overrides,
  };
}

function fakeStore(calls: string[] = []): ProviderCommandStore {
  return {
    async createProvider(_spaceId, input) {
      calls.push(`create:${input.name}`);
      return providerDto({ name: input.name, provider_type: input.provider_type });
    },
    async updateProvider(_spaceId, providerId, input) {
      calls.push(`update:${providerId}:${input.name ?? ""}`);
      return providerDto({ id: providerId, name: input.name ?? "Main" });
    },
    async deleteProvider(_spaceId, providerId) {
      calls.push(`delete:${providerId}`);
    },
    async getInvocationTarget(_spaceId, providerId) {
      calls.push(`invoke:${providerId ?? "default"}`);
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
          { member_id: "member-1", credential_id: "credential-1", api_key: "sk-test-provider" },
        ],
      };
    },
    async recordPoolOutcome(memberId, outcome) {
      calls.push(`outcome:${memberId}:${outcome.kind}`);
    },
    async resolveProviderApiKey(_spaceId, providerId) {
      calls.push(`resolve-key:${providerId}`);
      return "sk-test-provider";
    },
    async listPool(_spaceId, providerId) {
      calls.push(`pool:${providerId}`);
      return {
        provider_id: providerId,
        rotation_strategy: "fill_first",
        fallback_provider_ids: [],
        members: [],
      };
    },
    async addPoolCredential(_spaceId, providerId, input) {
      calls.push(`pool-add:${providerId}:${input.name ?? ""}`);
      return {
        id: "member-2",
        credential_id: "credential-2",
        name: input.name ?? "pool key",
        position: 1,
        enabled: true,
        healthy: true,
        cooldown_until: null,
        last_failure_class: null,
        request_count: 0,
        failure_count: 0,
        last_used_at: null,
        created_at: "2026-06-11T12:00:00.000Z",
        updated_at: "2026-06-11T12:00:00.000Z",
      };
    },
    async removePoolCredential(_spaceId, providerId, memberId) {
      calls.push(`pool-remove:${providerId}:${memberId}`);
    },
    async updatePoolConfig(_spaceId, providerId, input) {
      calls.push(`pool-config:${providerId}:${input.rotation_strategy ?? ""}`);
      return {
        provider_id: providerId,
        rotation_strategy: input.rotation_strategy ?? "fill_first",
        fallback_provider_ids: input.fallback_provider_ids ?? [],
        members: [],
      };
    },
    async getTaskChain(_spaceId, task) {
      calls.push(`task-chain:${task}`);
      return null;
    },
    async listTaskPolicies(_spaceId) {
      calls.push("task-policies");
      return [];
    },
    async putTaskPolicy(_spaceId, task, chain, enabled) {
      calls.push(`task-put:${task}:${chain.length}:${enabled ?? true}`);
      return { task, chain, enabled: enabled ?? true, updated_at: "2026-06-11T12:00:00.000Z" };
    },
    async deleteTaskPolicy(_spaceId, task) {
      calls.push(`task-delete:${task}`);
    },
    async resolveCredentialApiKey(_spaceId, credentialId) {
      calls.push(`resolve-credential:${credentialId}`);
      return "sk-test-credential";
    },
    async listConfiguredModels(_spaceId, providerId) {
      calls.push(`models:${providerId}`);
      return ["gpt-4o-mini"];
    },
    async recordCliCredentialUsage(input) {
      calls.push(`audit:${input.action ?? "grant"}`);
      return "event-1";
    },
  };
}

async function authorityConfig() {
  tempHome = await mkdtemp(join(tmpdir(), "aspace-server-"));
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
    SERVER_INTERNAL_TOKEN: "internal-token",
    AGENT_SPACE_HOME: tempHome,
  });
}

describe("providers and credentials server authority", () => {
  it("serves provider commands through the server store behind native identity", async () => {
    const calls: string[] = [];
    __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProviderCommandStoreForTests(fakeStore(calls));
    app = buildServer(await authorityConfig(), { logger: false });

    const create = await app.inject({
      method: "POST",
      url: "/api/v1/providers?space_id=space-1",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({
        name: "Main",
        provider_type: "openai",
        api_key: "request-only",
        default_model: "gpt-4o-mini",
        is_default: true,
      }),
    });
    expect(create.statusCode).toBe(201);
    expect(create.json()).toMatchObject({ name: "Main", has_api_key: true });
    expect(create.payload).not.toContain("request-only");

    const supported = await app.inject({
      method: "GET",
      url: "/api/v1/providers/litellm-providers?space_id=space-1",
    });
    expect(supported.statusCode).toBe(200);
    expect(supported.json()).toContain("anthropic");

    expect(calls).toEqual(["create:Main"]);
  });

  it("serves the credential pool and task-policy surfaces", async () => {
    const calls: string[] = [];
    __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProviderCommandStoreForTests(fakeStore(calls));
    app = buildServer(await authorityConfig(), { logger: false });

    const pool = await app.inject({
      method: "GET",
      url: "/api/v1/providers/provider-1/credentials?space_id=space-1",
    });
    expect(pool.statusCode).toBe(200);
    expect(pool.json()).toMatchObject({ provider_id: "provider-1", rotation_strategy: "fill_first" });

    const added = await app.inject({
      method: "POST",
      url: "/api/v1/providers/provider-1/credentials?space_id=space-1",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ api_key: "sk-pool-request-only", name: "backup key" }),
    });
    expect(added.statusCode).toBe(201);
    expect(added.payload).not.toContain("sk-pool-request-only");

    const config = await app.inject({
      method: "PATCH",
      url: "/api/v1/providers/provider-1/credentials/config?space_id=space-1",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ rotation_strategy: "round_robin" }),
    });
    expect(config.statusCode).toBe(200);
    expect(config.json()).toMatchObject({ rotation_strategy: "round_robin" });

    const removed = await app.inject({
      method: "DELETE",
      url: "/api/v1/providers/provider-1/credentials/member-2?space_id=space-1",
    });
    expect(removed.statusCode).toBe(204);

    // Static sibling: task-policies must not be swallowed by /:configId.
    const policies = await app.inject({
      method: "GET",
      url: "/api/v1/providers/task-policies?space_id=space-1",
    });
    expect(policies.statusCode).toBe(200);
    expect(policies.json()).toEqual([]);

    const put = await app.inject({
      method: "PUT",
      url: "/api/v1/providers/task-policies/reflector?space_id=space-1",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({ chain: [{ provider_id: "provider-1", model: "gpt-4o-mini" }] }),
    });
    expect(put.statusCode).toBe(200);
    expect(put.json()).toMatchObject({ task: "reflector" });

    expect(calls).toEqual([
      "pool:provider-1",
      "pool-add:provider-1:backup key",
      "pool-config:provider-1:round_robin",
      "pool-remove:provider-1:member-2",
      "task-policies",
      "task-put:reflector:1:true",
    ]);
  });

  it("invokes provider chat without putting the API key in the response", async () => {
    const fetches: Array<{ url: string; headers: unknown; body: string }> = [];
    __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProviderCommandStoreForTests(fakeStore());
    __setProviderHttpClientForTests({
      async fetch(url, init) {
        fetches.push({
          url,
          headers: init?.headers,
          body: String(init?.body ?? ""),
        });
        return new Response(
          JSON.stringify({
            choices: [{ message: { content: "hello" } }],
            model: "gpt-4o-mini",
            usage: { total_tokens: 3 },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      },
    });
    app = buildServer(await authorityConfig(), { logger: false });

    const chat = await app.inject({
      method: "POST",
      url: "/api/v1/providers/chat?space_id=space-1",
      headers: { "content-type": "application/json" },
      payload: JSON.stringify({
        provider_id: "provider-1",
        messages: [{ role: "user", content: "hi" }],
      }),
    });

    expect(chat.statusCode).toBe(200);
    expect(chat.json()).toMatchObject({ content: "hello", provider: "openai" });
    expect(chat.payload).not.toContain("sk-test-provider");
    expect(fetches[0].url).toBe("https://api.example.test/v1/chat/completions");
    expect(JSON.stringify(fetches[0].headers)).toContain("sk-test-provider");
  });

  it("owns CLI profile reads, status, and internal credential resolution", async () => {
    __setAuthIdentityForTests({ spaceId: "space-1", userId: "user-1" });
    __setProviderCommandStoreForTests(fakeStore());
    app = buildServer(await authorityConfig(), { logger: false });

    const methods = await app.inject({
      method: "GET",
      url: "/api/v1/credentials/cli/methods?space_id=space-1",
    });
    expect(methods.statusCode).toBe(200);
    expect(
      methods.json().find((row: { runtime: string }) => row.runtime === "claude_code"),
    ).toMatchObject({
      method: "cli",
      supports_cli: true,
    });
    expect(
      methods.json().find((row: { runtime: string }) => row.runtime === "codex_cli"),
    ).toMatchObject({
      method: "cli",
      supports_cli: true,
    });

    const codexProfileDir = join(tempHome!, "secrets/cli-credentials/codex_cli/default");
    await mkdir(codexProfileDir, { recursive: true });
    await writeFile(join(codexProfileDir, "auth.json"), '{"tokens":true}\n');

    const profile = await app.inject({
      method: "GET",
      url: "/api/v1/credentials/cli/profiles/codex_cli/default?space_id=space-1",
    });
    expect(profile.statusCode).toBe(200);
    expect(profile.json()).toMatchObject({
      id: "codex_cli/default",
      runtime: "codex_cli",
      source_exists: true,
    });

    const status = await app.inject({
      method: "GET",
      url: "/api/v1/credentials/cli/status?space_id=space-1",
    });
    expect(status.statusCode).toBe(200);
    expect(
      status.json().find((row: { runtime: string }) => row.runtime === "codex_cli"),
    ).toMatchObject({ logged_in: true, profile_id: "codex_cli/default" });

    const denied = await app.inject({
      method: "POST",
      url: "/internal/providers-credentials/credentials/runtime/resolve",
      payload: JSON.stringify({
        kind: "model_provider_api_key",
        space_id: "space-1",
        provider_id: "provider-1",
      }),
    });
    expect(denied.statusCode).toBe(401);

    const resolved = await app.inject({
      method: "POST",
      url: "/internal/providers-credentials/credentials/runtime/resolve",
      headers: {
        "content-type": "application/json",
        "x-agent-space-internal-token": "internal-token",
      },
      payload: JSON.stringify({
        kind: "model_provider_api_key",
        space_id: "space-1",
        provider_id: "provider-1",
      }),
    });
    expect(resolved.statusCode).toBe(200);
    expect(resolved.json()).toEqual({
      kind: "model_provider_api_key",
      provider_id: "provider-1",
      api_key: "sk-test-provider",
    });

    const resolvedCredential = await app.inject({
      method: "POST",
      url: "/internal/providers-credentials/credentials/runtime/resolve",
      headers: {
        "content-type": "application/json",
        "x-agent-space-internal-token": "internal-token",
      },
      payload: JSON.stringify({
        kind: "credential_api_key",
        space_id: "space-1",
        credential_id: "credential-1",
      }),
    });
    expect(resolvedCredential.statusCode).toBe(200);
    expect(resolvedCredential.json()).toEqual({
      kind: "credential_api_key",
      credential_id: "credential-1",
      api_key: "sk-test-credential",
    });
  });
});
