import { afterEach, describe, expect, it } from "vitest";
import {
  __setProviderHttpClientForTests,
  completeProviderChat,
  completeProviderText,
  orderPoolMembers,
  ProviderInvocationError,
  type InvocationTarget,
  type PoolOutcome,
  type ProviderCommandStore,
  type ProviderTaskChainEntry,
} from "../src/modules/providers";

afterEach(() => {
  __setProviderHttpClientForTests(null);
});

function target(
  providerId: string,
  keys: Array<{ member: string; key: string }>,
  overrides: Partial<InvocationTarget["provider"]> & {
    fallback_provider_ids?: string[];
  } = {},
): InvocationTarget {
  const { fallback_provider_ids = [], ...provider } = overrides;
  return {
    provider: {
      id: providerId,
      space_id: "space-1",
      name: providerId,
      provider_type: "openai",
      base_url: `https://api.${providerId}.test/v1`,
      network_profile_id: null,
      default_model: `default-of-${providerId}`,
      available_models: [],
      enabled: true,
      is_default: false,
      ...provider,
    },
    network_profile: null,
    rotation_strategy: "fill_first",
    fallback_provider_ids,
    candidates: keys.map(({ member, key }) => ({
      member_id: member,
      credential_id: `cred-${member}`,
      api_key: key,
    })),
  };
}

function makeStore(
  targets: Record<string, InvocationTarget>,
  outcomes: Array<{ member: string; outcome: PoolOutcome }>,
  taskChains: Record<string, ProviderTaskChainEntry[]> = {},
): ProviderCommandStore {
  const unsupported = () => {
    throw new Error("not used in this test");
  };
  return {
    createProvider: unsupported,
    updateProvider: unsupported,
    deleteProvider: unsupported,
    grantProviderToSpace: unsupported,
    revokeProviderGrant: unsupported,
    async getInvocationTarget(_spaceId, providerId) {
      const t = targets[providerId ?? "default"];
      if (!t) throw new ProviderInvocationError(404, `no provider ${providerId}`);
      // Fresh candidate array per call: per-turn restarts must not see
      // mutations from a previous walk.
      return { ...t, candidates: [...t.candidates] };
    },
    async recordPoolOutcome(memberId, outcome) {
      outcomes.push({ member: memberId, outcome });
    },
    resolveProviderApiKey: unsupported,
    resolveCredentialApiKey: unsupported,
    async listConfiguredModels() {
      return [];
    },
    recordCliCredentialUsage: unsupported,
    listPool: unsupported,
    addPoolCredential: unsupported,
    removePoolCredential: unsupported,
    updatePoolConfig: unsupported,
    async getTaskChain(_spaceId, task) {
      return taskChains[task] ?? null;
    },
    listTaskPolicies: unsupported,
    putTaskPolicy: unsupported,
    deleteTaskPolicy: unsupported,
  };
}

interface Attempt {
  url: string;
  key: string | null;
  model: string | null;
}

/** Scripted provider HTTP client: pops one response per fetch call. */
function scriptedHttp(script: Array<{ status: number; body?: unknown }>): Attempt[] {
  const attempts: Attempt[] = [];
  __setProviderHttpClientForTests({
    async fetch(url, init) {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      attempts.push({
        url,
        key: headers.authorization?.replace("Bearer ", "") ?? headers["x-api-key"] ?? null,
        model: body.model ?? null,
      });
      const step = script.shift() ?? { status: 500, body: { error: "script exhausted" } };
      const payload =
        step.body ??
        {
          choices: [{ message: { content: "ok" } }],
          model: body.model,
          usage: {},
        };
      return new Response(JSON.stringify(payload), {
        status: step.status,
        headers: { "content-type": "application/json" },
      });
    },
  });
  return attempts;
}

const CHAT = {
  messages: [{ role: "user", content: "hi" }],
  max_tokens: 5,
};

describe("provider invocation resilience", () => {
  it("retries the same key once on a transient 429, then succeeds", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      { p1: target("p1", [{ member: "m1", key: "k1" }]) },
      outcomes,
    );
    const attempts = scriptedHttp([
      { status: 429, body: { error: { message: "slow down" } } },
      { status: 200 },
    ]);

    const result = await completeProviderChat(store, "space-1", { ...CHAT, provider_id: "p1" });

    expect(result.content).toBe("ok");
    expect(attempts.map((a) => a.key)).toEqual(["k1", "k1"]);
    expect(outcomes).toEqual([{ member: "m1", outcome: { kind: "success" } }]);
  });

  it("rotates to the next key with a 24h cooldown on quota exhaustion", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      {
        p1: target("p1", [
          { member: "m1", key: "k1" },
          { member: "m2", key: "k2" },
        ]),
      },
      outcomes,
    );
    const attempts = scriptedHttp([
      { status: 429, body: { error: { message: "You exceeded your current quota" } } },
      { status: 200 },
    ]);

    const result = await completeProviderChat(store, "space-1", { ...CHAT, provider_id: "p1" });

    expect(result.content).toBe("ok");
    expect(attempts.map((a) => a.key)).toEqual(["k1", "k2"]);
    expect(outcomes[0]).toEqual({
      member: "m1",
      outcome: {
        kind: "failure",
        failure_class: "quota_exhausted",
        cooldown_seconds: 24 * 60 * 60,
        unhealthy: false,
      },
    });
    expect(outcomes[1]).toEqual({ member: "m2", outcome: { kind: "success" } });
  });

  it("marks a key unhealthy on 401 and rotates without retry", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      {
        p1: target("p1", [
          { member: "m1", key: "bad" },
          { member: "m2", key: "good" },
        ]),
      },
      outcomes,
    );
    const attempts = scriptedHttp([{ status: 401 }, { status: 200 }]);

    await completeProviderChat(store, "space-1", { ...CHAT, provider_id: "p1" });

    expect(attempts.map((a) => a.key)).toEqual(["bad", "good"]);
    expect(outcomes[0].outcome).toMatchObject({
      kind: "failure",
      failure_class: "unauthorized",
      unhealthy: true,
    });
  });

  it("falls back to the next provider with ITS default model after 402 exhausts the pool", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      {
        p1: target("p1", [{ member: "m1", key: "k1" }], { fallback_provider_ids: ["p2"] }),
        p2: target("p2", [{ member: "m2", key: "k2" }]),
      },
      outcomes,
    );
    const attempts = scriptedHttp([{ status: 402 }, { status: 200 }]);

    const result = await completeProviderChat(store, "space-1", {
      ...CHAT,
      provider_id: "p1",
      model: "explicit-model-for-p1",
    });

    expect(result.content).toBe("ok");
    expect(attempts[0]).toMatchObject({ key: "k1", model: "explicit-model-for-p1" });
    // The explicit model bound to p1 must not leak onto the fallback provider.
    expect(attempts[1]).toMatchObject({ key: "k2", model: "default-of-p2" });
  });

  it("does not rotate keys on permanent request errors", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      {
        p1: target("p1", [
          { member: "m1", key: "k1" },
          { member: "m2", key: "k2" },
        ]),
      },
      outcomes,
    );
    const attempts = scriptedHttp([{ status: 400, body: { error: "bad request" } }]);

    await expect(
      completeProviderChat(store, "space-1", { ...CHAT, provider_id: "p1" }),
    ).rejects.toThrow(ProviderInvocationError);
    expect(attempts).toHaveLength(1);
  });

  it("fails with 503 when every key is cooling down", async () => {
    const store = makeStore({ p1: target("p1", []) }, []);
    // No HTTP script: nothing should be called.
    const attempts = scriptedHttp([]);

    await expect(
      completeProviderChat(store, "space-1", { ...CHAT, provider_id: "p1" }),
    ).rejects.toMatchObject({ statusCode: 503 });
    expect(attempts).toHaveLength(0);
  });

  it("walks the task chain first and uses the caller provider as the safety net", async () => {
    const outcomes: Array<{ member: string; outcome: PoolOutcome }> = [];
    const store = makeStore(
      {
        chain1: target("chain1", [{ member: "mc", key: "kc" }]),
        net: target("net", [{ member: "mn", key: "kn" }]),
      },
      outcomes,
      { reflector: [{ provider_id: "chain1", model: "chain-model" }] },
    );
    const attempts = scriptedHttp([
      { status: 503, body: { error: "down" } }, // chain1 attempt 1
      { status: 503, body: { error: "down" } }, // chain1 transient retry
      { status: 200 }, // safety net
    ]);

    const result = await completeProviderText(store, "space-1", {
      provider_id: "net",
      system: "sys",
      user: "hello",
      task: "reflector",
    });

    expect(result.text).toBe("ok");
    expect(attempts.map((a) => a.key)).toEqual(["kc", "kc", "kn"]);
    expect(attempts[0].model).toBe("chain-model");
  });
});

describe("rotation strategy ordering", () => {
  const member = (
    position: number,
    requestCount: number,
    lastUsed: string | null,
  ) => ({
    position,
    request_count: requestCount,
    last_used_at: lastUsed ? new Date(lastUsed) : null,
  });

  it("fill_first orders by position", () => {
    const ordered = orderPoolMembers(
      [member(2, 0, null), member(0, 9, null), member(1, 1, null)],
      "fill_first",
    );
    expect(ordered.map((m) => m.position)).toEqual([0, 1, 2]);
  });

  it("round_robin orders least-recently-used first", () => {
    const ordered = orderPoolMembers(
      [
        member(0, 5, "2026-06-11T10:00:00Z"),
        member(1, 5, "2026-06-11T08:00:00Z"),
        member(2, 5, null),
      ],
      "round_robin",
    );
    expect(ordered.map((m) => m.position)).toEqual([2, 1, 0]);
  });

  it("least_used orders by request count", () => {
    const ordered = orderPoolMembers(
      [member(0, 7, null), member(1, 2, null), member(2, 4, null)],
      "least_used",
    );
    expect(ordered.map((m) => m.position)).toEqual([1, 2, 0]);
  });
});
