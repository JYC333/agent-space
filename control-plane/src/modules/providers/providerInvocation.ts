/**
 * Resilient provider invocation for the provider API-key channel.
 *
 * Provider resilience layering (Hermes H1 + H2):
 *
 *   1. Key pool   — each attempt draws the next candidate key from the
 *                   provider's credential pool (rotation strategy ordered,
 *                   cooling keys excluded). The error taxonomy decides what a
 *                   failure does to the key: 429 retries the same key once
 *                   then rotates; quota-exhaustion / 402 rotate with a 24 h
 *                   cooldown; 401/403 rotate with a 24 h cooldown and an
 *                   unhealthy mark (pool keys are plain API keys — the
 *                   refresh-token step of the taxonomy applies only to OAuth
 *                   credentials, which live in the separate CLI channel and
 *                   are never pooled).
 *   2. Provider   — when a provider's keys are exhausted (or it fails with a
 *      fallback      transient 5xx/408 after one retry), invocation falls
 *                   back to the provider's configured fallback chain.
 *                   Fallback is PER REQUEST: nothing sticky is stored, so the
 *                   next user turn always restarts on the primary provider.
 *   3. Task chain — auxiliary tasks (reflector, condenser, …) may carry a
 *                   ProviderTaskPolicy chain that takes precedence over the
 *                   caller's provider, which then acts as the safety net.
 *
 * API keys are passed as request parameters/headers only. They are never
 * written to process env and never returned in responses.
 */

import type {
  InvocationTarget,
  PoolKeyCandidate,
  ProviderCommandStore,
  ProviderInfo,
} from "./providerCommandStore";
import { classifyProviderFailure, type ProviderResilienceDecision } from "./providerResilience";

export interface ChatMessage {
  role: string;
  content: string;
}

export interface ProviderChatRequestBody {
  provider_id?: string | null;
  model?: string | null;
  messages: ChatMessage[];
  system?: string | null;
  temperature?: number;
  max_tokens?: number;
}

export interface ProviderChatResponseBody {
  content: string;
  provider: string;
  model: string;
  usage: Record<string, unknown>;
}

export class ProviderInvocationError extends Error {
  constructor(
    readonly statusCode: number,
    message: string,
    readonly resilience?: ProviderResilienceDecision,
  ) {
    super(message);
    this.name = "ProviderInvocationError";
  }
}

export interface ProviderHttpClient {
  fetch(url: string, init?: RequestInit): Promise<Response>;
}

let httpClientOverride: ProviderHttpClient | null = null;

export function __setProviderHttpClientForTests(client: ProviderHttpClient | null): void {
  httpClientOverride = client;
}

function httpClient(): ProviderHttpClient {
  return httpClientOverride ?? { fetch: globalThis.fetch.bind(globalThis) };
}

export function buildProviderModelName(providerType: string, model: string): string {
  if (model.includes("/")) return model;
  if (providerType === "anthropic") return `anthropic/${model}`;
  if (providerType === "openrouter") return `openrouter/${model}`;
  if (providerType === "ollama") return `ollama/${model}`;
  return `openai/${model}`;
}

function bareModelName(providerType: string, model: string): string {
  if (providerType === "anthropic" && model.startsWith("anthropic/")) {
    return model.slice("anthropic/".length);
  }
  if (providerType === "openrouter" && model.startsWith("openrouter/")) {
    return model.slice("openrouter/".length);
  }
  if (providerType === "ollama" && model.startsWith("ollama/")) {
    return model.slice("ollama/".length);
  }
  if (
    ["openai", "custom_openai_compatible", "other"].includes(providerType) &&
    model.startsWith("openai/")
  ) {
    return model.slice("openai/".length);
  }
  return model;
}

function defaultModelFor(providerType: string): string {
  if (providerType === "anthropic") return "claude-3-5-sonnet-latest";
  if (providerType === "openrouter") return "openai/gpt-4o-mini";
  if (providerType === "ollama") return "llama3";
  return "gpt-4o-mini";
}

function resolveModel(provider: ProviderInfo, requested?: string | null): string {
  return (
    requested ||
    provider.default_model ||
    provider.available_models[0] ||
    defaultModelFor(provider.provider_type)
  );
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!response.ok) {
    throw new ProviderInvocationError(
      502,
      `Provider request failed with status ${response.status}`,
      classifyProviderFailure(response.status, text),
    );
  }
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    throw new ProviderInvocationError(502, "Provider returned invalid JSON");
  }
}

function openAiBase(provider: ProviderInfo): string {
  if (provider.base_url) return provider.base_url.replace(/\/+$/, "");
  if (provider.provider_type === "openrouter") return "https://openrouter.ai/api/v1";
  return "https://api.openai.com/v1";
}

function openAiMessages(body: ProviderChatRequestBody): ChatMessage[] {
  return body.system
    ? [{ role: "system", content: body.system }, ...body.messages]
    : body.messages;
}

// ---------------------------------------------------------------------------
// Single-attempt provider calls (one key, one request)
// ---------------------------------------------------------------------------

async function completeOpenAiCompatible(
  provider: ProviderInfo,
  apiKey: string | null,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  if (!apiKey) {
    throw new ProviderInvocationError(
      400,
      `ModelProvider '${provider.id}' has no API key credential`,
    );
  }
  const model = bareModelName(provider.provider_type, resolveModel(provider, body.model));
  const response = await httpClient().fetch(`${openAiBase(provider)}/chat/completions`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: openAiMessages(body),
      temperature: body.temperature,
      max_tokens: body.max_tokens,
    }),
  });
  const data = (await parseJsonResponse(response)) as {
    choices?: Array<{ message?: { content?: string } }>;
    model?: string;
    usage?: Record<string, unknown>;
  };
  return {
    content: data.choices?.[0]?.message?.content ?? "",
    provider: provider.provider_type,
    model: data.model ?? model,
    usage: data.usage ?? {},
  };
}

async function completeAnthropic(
  provider: ProviderInfo,
  apiKey: string | null,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  if (!apiKey) {
    throw new ProviderInvocationError(
      400,
      `ModelProvider '${provider.id}' has no API key credential`,
    );
  }
  const model = bareModelName("anthropic", resolveModel(provider, body.model));
  const response = await httpClient().fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      system: body.system ?? undefined,
      messages: body.messages.filter((m) => m.role !== "system"),
      temperature: body.temperature,
      max_tokens: body.max_tokens ?? 1024,
    }),
  });
  const data = (await parseJsonResponse(response)) as {
    content?: Array<{ type?: string; text?: string }>;
    model?: string;
    usage?: Record<string, unknown>;
  };
  return {
    content: data.content?.map((c) => c.text ?? "").join("") ?? "",
    provider: "anthropic",
    model: data.model ?? model,
    usage: data.usage ?? {},
  };
}

async function completeOllama(
  provider: ProviderInfo,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  const base = provider.base_url?.replace(/\/+$/, "");
  if (!base) {
    throw new ProviderInvocationError(400, "base_url is required for provider_type 'ollama'");
  }
  const model = bareModelName("ollama", resolveModel(provider, body.model));
  const response = await httpClient().fetch(`${base}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model,
      stream: false,
      messages: openAiMessages(body),
      options: {
        temperature: body.temperature,
        num_predict: body.max_tokens,
      },
    }),
  });
  const data = (await parseJsonResponse(response)) as {
    message?: { content?: string };
    model?: string;
  };
  return {
    content: data.message?.content ?? "",
    provider: "ollama",
    model: data.model ?? model,
    usage: {},
  };
}

function attemptOnce(
  provider: ProviderInfo,
  apiKey: string | null,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  if (provider.provider_type === "anthropic") return completeAnthropic(provider, apiKey, body);
  if (provider.provider_type === "ollama") return completeOllama(provider, body);
  return completeOpenAiCompatible(provider, apiKey, body);
}

// ---------------------------------------------------------------------------
// Resilience engine
// ---------------------------------------------------------------------------

const DAY_SECONDS = 24 * 60 * 60;

async function recordFailure(
  store: ProviderCommandStore,
  candidate: PoolKeyCandidate,
  decision: ProviderResilienceDecision,
): Promise<void> {
  if (!candidate.member_id) return;
  await store.recordPoolOutcome(candidate.member_id, {
    kind: "failure",
    failure_class: decision.failure_class,
    cooldown_seconds:
      decision.failure_class === "quota_exhausted" ||
      decision.failure_class === "payment_required" ||
      decision.failure_class === "unauthorized"
        ? decision.cooldown_seconds ?? DAY_SECONDS
        : undefined,
    unhealthy: decision.failure_class === "unauthorized",
  });
}

/**
 * Run one provider through its key pool, applying the per-key error taxonomy.
 * Throws the last error when every candidate is exhausted; the caller decides
 * whether a fallback provider exists.
 */
async function invokeProviderWithPool(
  store: ProviderCommandStore,
  target: InvocationTarget,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  if (target.candidates.length === 0) {
    throw new ProviderInvocationError(
      503,
      `ModelProvider '${target.provider.id}' has no available credential (all keys cooling down)`,
    );
  }

  let lastError: unknown = null;
  for (const candidate of target.candidates) {
    let retriedSameKey = false;
    for (;;) {
      try {
        const result = await attemptOnce(target.provider, candidate.api_key, body);
        if (candidate.member_id) {
          await store.recordPoolOutcome(candidate.member_id, { kind: "success" });
        }
        return result;
      } catch (error) {
        lastError = error;
        if (!(error instanceof ProviderInvocationError) || !error.resilience) {
          // Permanent request-shaped errors (and non-taxonomy errors) do not
          // rotate: another key would fail the same way.
          throw error;
        }
        const decision = error.resilience;
        if (decision.failure_class === "permanent") {
          await recordFailure(store, candidate, decision);
          throw error;
        }
        if (
          (decision.failure_class === "rate_limit" || decision.failure_class === "transient") &&
          !retriedSameKey
        ) {
          retriedSameKey = true;
          continue;
        }
        await recordFailure(store, candidate, decision);
        if (decision.failure_class === "transient") {
          // Provider-side failure: other keys of the same provider won't
          // help. Hand over to the provider fallback layer.
          throw error;
        }
        break; // rotate to the next key
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new ProviderInvocationError(502, "Provider invocation failed");
}

/**
 * Provider-level fallback (Hermes layer 2): the requested provider first,
 * then its configured `fallback_provider_ids` in order. Stateless per
 * request — a later request always restarts on the primary.
 */
export async function completeProviderChat(
  store: ProviderCommandStore,
  spaceId: string,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  const primary = await store.getInvocationTarget(spaceId, body.provider_id);
  const chain: InvocationTarget[] = [primary];
  for (const fallbackId of primary.fallback_provider_ids) {
    try {
      chain.push(await store.getInvocationTarget(spaceId, fallbackId));
    } catch {
      // A missing/disabled fallback provider is skipped, not fatal.
    }
  }

  let lastError: unknown = null;
  for (const [index, target] of chain.entries()) {
    try {
      // Fallback providers serve THEIR OWN default model: an explicit model
      // name from the request only binds to the provider it was meant for.
      const effectiveBody = index === 0 ? body : { ...body, model: null };
      return await invokeProviderWithPool(store, target, effectiveBody);
    } catch (error) {
      lastError = error;
      if (
        error instanceof ProviderInvocationError &&
        error.resilience?.failure_class === "permanent"
      ) {
        throw error;
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new ProviderInvocationError(502, "Provider invocation failed");
}

export interface ProviderTextCompletionInput {
  provider_id: string;
  model?: string | null;
  system: string;
  user: string;
  max_tokens?: number;
  /** Auxiliary-task name; resolves a ProviderTaskPolicy chain when present. */
  task?: string | null;
}

/**
 * Auxiliary-task completion (Hermes H2). When the space holds an enabled
 * ProviderTaskPolicy for `task`, its chain is walked first (each entry with
 * full key-pool resilience); the caller's provider acts as the safety net.
 * Without a policy this degrades to a plain provider-chat completion.
 */
export async function completeProviderText(
  store: ProviderCommandStore,
  spaceId: string,
  input: ProviderTextCompletionInput,
): Promise<{ text: string; model: string; usage: Record<string, unknown> }> {
  const chatBody = (providerId: string, model: string | null | undefined): ProviderChatRequestBody => ({
    provider_id: providerId,
    model,
    system: input.system,
    messages: [{ role: "user", content: input.user }],
    max_tokens: input.max_tokens,
  });

  const taskChain = input.task ? await store.getTaskChain(spaceId, input.task) : null;
  let lastError: unknown = null;
  if (taskChain) {
    for (const entry of taskChain) {
      try {
        const result = await completeProviderChat(store, spaceId, chatBody(entry.provider_id, entry.model));
        return { text: result.content, model: result.model, usage: result.usage };
      } catch (error) {
        lastError = error;
        if (
          error instanceof ProviderInvocationError &&
          error.resilience?.failure_class === "permanent"
        ) {
          throw error;
        }
      }
    }
    // Safety net: the caller's provider, unless the chain already tried it.
    if (taskChain.some((entry) => entry.provider_id === input.provider_id)) {
      throw lastError instanceof Error
        ? lastError
        : new ProviderInvocationError(502, "Provider invocation failed");
    }
  }

  const result = await completeProviderChat(store, spaceId, chatBody(input.provider_id, input.model));
  return { text: result.content, model: result.model, usage: result.usage };
}

export async function listProviderModels(
  store: ProviderCommandStore,
  spaceId: string,
  providerId: string,
): Promise<{ models: string[]; source: "configured" | "live" }> {
  const configured = await store.listConfiguredModels(spaceId, providerId);
  if (configured.length > 0) return { models: configured, source: "configured" };
  const target = await store.getInvocationTarget(spaceId, providerId);
  const provider = target.provider;
  const apiKey = target.candidates.find((c) => c.api_key)?.api_key ?? null;
  if (provider.provider_type === "ollama" && provider.base_url) {
    const data = (await parseJsonResponse(
      await httpClient().fetch(`${provider.base_url.replace(/\/+$/, "")}/api/tags`),
    )) as { models?: Array<{ name?: string }> };
    return {
      models: (data.models ?? []).map((m) => m.name).filter((m): m is string => Boolean(m)),
      source: "live",
    };
  }
  if (["openai", "openrouter", "custom_openai_compatible", "other"].includes(provider.provider_type)) {
    const headers: Record<string, string> = {};
    if (apiKey) headers.authorization = `Bearer ${apiKey}`;
    const data = (await parseJsonResponse(
      await httpClient().fetch(`${openAiBase(provider)}/models`, { headers }),
    )) as { data?: Array<{ id?: string }> };
    return {
      models: (data.data ?? []).map((m) => m.id).filter((m): m is string => Boolean(m)),
      source: "live",
    };
  }
  return { models: [], source: "configured" };
}
