/**
 * Resilient provider invocation for the provider API-key channel.
 *
 * Provider resilience layering:
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
  CanonicalToolCall,
  CanonicalToolDefinition,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type {
  InvocationTarget,
  PoolKeyCandidate,
  ProviderCommandStore,
  ProviderInfo,
} from "./providerCommandStore";
import { classifyProviderFailure, type ProviderResilienceDecision } from "./providerResilience";
import { fetchWithNetworkProfile, type ResolvedNetworkProfile } from "../networkProfiles";
import {
  anthropicMessages,
  anthropicToolCalls,
  anthropicTools,
  openAiMessages,
  openAiToolCalls,
  openAiTools,
} from "./providerToolAdapters";
import {
  retrievalEgressAllowed,
  retrievalProviderEgressDestination,
  type RetrievalEgressPolicy,
} from "../retrievalEgress/egressPolicy";

export interface ChatMessage {
  role: string;
  content: string | null;
  tool_calls?: CanonicalToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ProviderChatRequestBody {
  provider_id?: string | null;
  model?: string | null;
  messages: ChatMessage[];
  system?: string | null;
  temperature?: number;
  max_tokens?: number;
  tools?: CanonicalToolDefinition[] | null;
  egressPolicy?: RetrievalEgressPolicy | null;
}

export interface ProviderChatResponseBody {
  content: string;
  provider: string;
  model: string;
  usage: Record<string, unknown>;
  tool_calls?: CanonicalToolCall[];
  finish_reason?: string | null;
}

export class ProviderInvocationError extends Error {
  constructor(
    readonly statusCode: number,
    message: string,
    readonly resilience?: ProviderResilienceDecision,
    /** Stable code so callers can branch (e.g. degrade) without string-matching. */
    readonly code?: string,
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

function httpClient(profile?: ResolvedNetworkProfile | null): ProviderHttpClient {
  if (!httpClientOverride && profile) return { fetch: fetchWithNetworkProfile(profile) };
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
  if (providerType === "zeroentropy" && model.startsWith("zeroentropy/")) {
    return model.slice("zeroentropy/".length);
  }
  if (["openai", "other"].includes(providerType) && model.startsWith("openai/")) {
    return model.slice("openai/".length);
  }
  return model;
}

function defaultModelFor(providerType: string): string {
  if (providerType === "anthropic") return "claude-3-5-sonnet-latest";
  if (providerType === "openrouter") return "openai/gpt-4o-mini";
  if (providerType === "ollama") return "llama3";
  if (providerType === "zeroentropy") return "zembed-1";
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

function anthropicMessagesUrl(provider: ProviderInfo): string {
  const base = (provider.base_url || "https://api.anthropic.com").replace(/\/+$/, "");
  const versioned = base.endsWith("/v1") ? base : `${base}/v1`;
  return `${versioned}/messages`;
}

function providerSupportsRuntimeTools(providerType: string): boolean {
  return (
    providerType === "openai" ||
    providerType === "openrouter" ||
    providerType === "other" ||
    providerType === "anthropic"
  );
}

// ---------------------------------------------------------------------------
// Single-attempt provider calls (one key, one request)
// ---------------------------------------------------------------------------

async function completeOpenAiCompatible(
  provider: ProviderInfo,
  networkProfile: ResolvedNetworkProfile | null,
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
  const tools = openAiTools(body.tools);
  const response = await httpClient(networkProfile).fetch(`${openAiBase(provider)}/chat/completions`, {
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
      ...(tools ? { tools, tool_choice: "auto" } : {}),
    }),
  });
  const data = (await parseJsonResponse(response)) as {
    choices?: Array<{
      finish_reason?: string | null;
      message?: {
        content?: string | null;
        tool_calls?: Array<{
          id?: string;
          type?: string;
          function?: { name?: string; arguments?: string };
        }>;
      };
    }>;
    model?: string;
    usage?: Record<string, unknown>;
  };
  const choice = data.choices?.[0];
  const toolCalls = openAiToolCalls(choice?.message?.tool_calls, body.tools);
  return {
    content: choice?.message?.content ?? "",
    provider: provider.provider_type,
    model: data.model ?? model,
    usage: data.usage ?? {},
    tool_calls: toolCalls,
    finish_reason: choice?.finish_reason ?? null,
  };
}

async function completeAnthropic(
  provider: ProviderInfo,
  networkProfile: ResolvedNetworkProfile | null,
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
  const tools = anthropicTools(body.tools);
  const response = await httpClient(networkProfile).fetch(anthropicMessagesUrl(provider), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      system: body.system ?? undefined,
      messages: anthropicMessages(body),
      temperature: body.temperature,
      // Tool-use turns need headroom for the tool_use block plus a follow-up
      // answer, so default higher when tools are offered.
      max_tokens: body.max_tokens ?? (tools ? 2048 : 1024),
      ...(tools ? { tools, tool_choice: { type: "auto" } } : {}),
    }),
  });
  const data = (await parseJsonResponse(response)) as {
    content?: Array<{
      type?: string;
      text?: string;
      id?: string;
      name?: string;
      input?: unknown;
    }>;
    model?: string;
    usage?: Record<string, unknown>;
    stop_reason?: string | null;
  };
  return {
    content: data.content?.map((c) => c.text ?? "").join("") ?? "",
    provider: "anthropic",
    model: data.model ?? model,
    usage: data.usage ?? {},
    tool_calls: anthropicToolCalls(data.content, body.tools),
    finish_reason: data.stop_reason ?? null,
  };
}

async function completeOllama(
  provider: ProviderInfo,
  networkProfile: ResolvedNetworkProfile | null,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  const base = provider.base_url?.replace(/\/+$/, "");
  if (!base) {
    throw new ProviderInvocationError(400, "base_url is required for provider_type 'ollama'");
  }
  const model = bareModelName("ollama", resolveModel(provider, body.model));
  const response = await httpClient(networkProfile).fetch(`${base}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model,
      stream: false,
      messages: body.system
        ? [{ role: "system", content: body.system }, ...body.messages.map((m) => ({ role: m.role, content: m.content ?? "" }))]
        : body.messages.map((m) => ({ role: m.role, content: m.content ?? "" })),
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
  target: InvocationTarget,
  apiKey: string | null,
  body: ProviderChatRequestBody,
): Promise<ProviderChatResponseBody> {
  const provider = target.provider;
  if (body.tools?.length && !providerSupportsRuntimeTools(provider.provider_type)) {
    throw new ProviderInvocationError(
      400,
      `provider_type '${provider.provider_type}' does not support runtime-host tools yet; use an OpenAI-compatible or Anthropic provider, or disable retrieval tools for this run`,
      { failure_class: "permanent", actions: ["fail"] },
      "runtime_tool_provider_unsupported",
    );
  }
  if (provider.provider_type === "anthropic") {
    return completeAnthropic(provider, target.network_profile, apiKey, body);
  }
  if (provider.provider_type === "ollama") return completeOllama(provider, target.network_profile, body);
  return completeOpenAiCompatible(provider, target.network_profile, apiKey, body);
}

function providerTargetEgressAllowed(
  target: InvocationTarget,
  policy: RetrievalEgressPolicy | null | undefined,
): boolean {
  if (!policy) return true;
  return retrievalEgressAllowed(
    {
      object_type: "model_provider",
      object_id: target.provider.id,
      source_connection_ids: policy.payloadSourceConnectionIds,
    },
    {
      ...policy,
      destination: retrievalProviderEgressDestination(target.provider),
    },
  );
}

function providerEgressDeniedError(target: InvocationTarget): ProviderInvocationError {
  return new ProviderInvocationError(
    403,
    `retrieval egress policy blocks provider '${target.provider.id}' (${target.provider.provider_type})`,
    undefined,
    "retrieval_egress_denied",
  );
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
        const result = await attemptOnce(target, candidate.api_key, body);
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
    if (!providerTargetEgressAllowed(target, body.egressPolicy)) {
      lastError = providerEgressDeniedError(target);
      continue;
    }
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
  egressPolicy?: RetrievalEgressPolicy | null;
}

export interface ProviderMessagesCompletionInput {
  provider_id: string;
  model?: string | null;
  system?: string | null;
  messages: ChatMessage[];
  max_tokens?: number;
  tools?: CanonicalToolDefinition[] | null;
  /** Auxiliary-task name; resolves a ProviderTaskPolicy chain when present. */
  task?: string | null;
  egressPolicy?: RetrievalEgressPolicy | null;
}

/**
 * Auxiliary-task completion. When the space holds an enabled
 * ProviderTaskPolicy for `task`, its chain is walked first (each entry with
 * full key-pool resilience); the caller's provider acts as the safety net.
 * Without a policy this degrades to a plain provider-chat completion.
 */
export async function completeProviderText(
  store: ProviderCommandStore,
  spaceId: string,
  input: ProviderTextCompletionInput,
): Promise<{ text: string; model: string; usage: Record<string, unknown> }> {
  return completeProviderMessages(store, spaceId, {
    provider_id: input.provider_id,
    model: input.model,
    system: input.system,
    messages: [{ role: "user", content: input.user }],
    max_tokens: input.max_tokens,
    task: input.task,
    egressPolicy: input.egressPolicy,
  });
}

export async function completeProviderMessages(
  store: ProviderCommandStore,
  spaceId: string,
  input: ProviderMessagesCompletionInput,
): Promise<{
  text: string;
  model: string;
  usage: Record<string, unknown>;
  tool_calls?: CanonicalToolCall[];
  finish_reason?: string | null;
}> {
  const chatBody = (providerId: string, model: string | null | undefined): ProviderChatRequestBody => ({
    provider_id: providerId,
    model,
    system: input.system,
    messages: input.messages,
    max_tokens: input.max_tokens,
    tools: input.tools,
    egressPolicy: input.egressPolicy,
  });

  const taskChain = input.task ? await store.getTaskChain(spaceId, input.task) : null;
  let lastError: unknown = null;
  if (taskChain) {
    for (const entry of taskChain) {
      try {
        const result = await completeProviderChat(store, spaceId, chatBody(entry.provider_id, entry.model));
        return {
          text: result.content,
          model: result.model,
          usage: result.usage,
          tool_calls: result.tool_calls,
          finish_reason: result.finish_reason,
        };
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
  return {
    text: result.content,
    model: result.model,
    usage: result.usage,
    tool_calls: result.tool_calls,
    finish_reason: result.finish_reason,
  };
}

export interface ProviderEmbeddingInput {
  /** Caller's own provider; used as the safety net after any task chain. */
  provider_id?: string | null;
  model?: string | null;
  inputs: string[];
  /** Normalized embedding dimension intent; provider adapters map or validate it. */
  dimensions?: number | null;
  /** Retrieval embedding input type for providers that distinguish queries from documents. */
  inputType?: "query" | "document";
  /** Auxiliary task whose ProviderTaskPolicy chain is tried first (e.g. retrieval_embedding). */
  task?: string;
  egressPolicy?: RetrievalEgressPolicy | null;
}

export interface ProviderEmbeddingResult {
  vectors: number[][];
  model: string;
}

export interface ProviderRerankInput {
  /** Caller's own provider; used as the safety net after any task chain. */
  provider_id?: string | null;
  model?: string | null;
  query: string;
  documents: string[];
  /** Provider-side top_n; defaults to all documents. */
  topN?: number | null;
  /** Auxiliary task whose ProviderTaskPolicy chain is tried first. */
  task?: string;
  egressPolicy?: RetrievalEgressPolicy | null;
}

export interface ProviderRerankResult {
  scores: Array<{ index: number; score: number }>;
  model: string;
  usage: Record<string, unknown>;
}

/**
 * Auxiliary embeddings completion. Mirrors `completeProviderText`'s task-chain
 * resilience: the `task` policy chain is tried first, then the caller's
 * provider as a safety net. Supports OpenAI-compatible `/embeddings`, Ollama
 * `/api/embed`, and ZeroEntropy `/models/embed`; provider types without an
 * embeddings endpoint fail closed.
 */
export async function completeProviderEmbedding(
  store: ProviderCommandStore,
  spaceId: string,
  input: ProviderEmbeddingInput,
): Promise<ProviderEmbeddingResult> {
  if (input.inputs.length === 0) return { vectors: [], model: "" };
  const taskChain = input.task ? await store.getTaskChain(spaceId, input.task) : null;
  if (taskChain) {
    let lastError: unknown = null;
    for (const entry of taskChain) {
      try {
        return await completeProviderEmbeddingWithFallback(
          store,
          spaceId,
          entry.provider_id,
          entry.model,
          input.inputs,
          input.dimensions,
          input.inputType,
          input.egressPolicy,
        );
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
    if (taskChain.some((entry) => entry.provider_id === input.provider_id)) {
      throw lastError instanceof Error
        ? lastError
        : new ProviderInvocationError(502, "Embedding invocation failed");
    }
  }

  return completeProviderEmbeddingWithFallback(
    store,
    spaceId,
    input.provider_id ?? null,
    input.model,
    input.inputs,
    input.dimensions,
    input.inputType,
    input.egressPolicy,
  );
}

async function completeProviderEmbeddingWithFallback(
  store: ProviderCommandStore,
  spaceId: string,
  providerId: string | null | undefined,
  model: string | null | undefined,
  inputs: string[],
  dimensions?: number | null,
  inputType?: "query" | "document",
  egressPolicy?: RetrievalEgressPolicy | null,
): Promise<ProviderEmbeddingResult> {
  const target = await store.getInvocationTarget(spaceId, providerId);
  const chain: InvocationTarget[] = [target];
  for (const fallbackId of target.fallback_provider_ids) {
    try {
      chain.push(await store.getInvocationTarget(spaceId, fallbackId));
    } catch {
      // A missing/disabled fallback provider is skipped, matching chat behavior.
    }
  }

  let lastError: unknown = null;
  for (const [index, candidate] of chain.entries()) {
    if (!providerTargetEgressAllowed(candidate, egressPolicy)) {
      lastError = providerEgressDeniedError(candidate);
      continue;
    }
    try {
      return await invokeEmbeddingProviderWithPool(
        store,
        candidate,
        index === 0 ? model : null,
        inputs,
        dimensions,
        inputType,
      );
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
    : new ProviderInvocationError(502, "Embedding invocation failed");
}

async function invokeEmbeddingProviderWithPool(
  store: ProviderCommandStore,
  target: InvocationTarget,
  model: string | null | undefined,
  inputs: string[],
  dimensions?: number | null,
  inputType?: "query" | "document",
): Promise<ProviderEmbeddingResult> {
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
        const result = await embedOnce(target, candidate.api_key, model, inputs, dimensions, inputType);
        if (candidate.member_id) {
          await store.recordPoolOutcome(candidate.member_id, { kind: "success" });
        }
        return result;
      } catch (error) {
        lastError = error;
        if (!(error instanceof ProviderInvocationError) || !error.resilience) {
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
          throw error;
        }
        break;
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new ProviderInvocationError(502, "Embedding invocation failed");
}

async function embedOnce(
  target: InvocationTarget,
  apiKey: string | null,
  model: string | null | undefined,
  inputs: string[],
  dimensions?: number | null,
  inputType?: "query" | "document",
): Promise<ProviderEmbeddingResult> {
  const provider = target.provider;
  const resolvedModel = bareModelName(provider.provider_type, resolveModel(provider, model));

  if (provider.provider_type === "ollama") {
    const base = provider.base_url?.replace(/\/+$/, "");
    if (!base) throw new ProviderInvocationError(400, "base_url is required for provider_type 'ollama'");
    const response = await httpClient(target.network_profile).fetch(`${base}/api/embed`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: resolvedModel, input: inputs }),
    });
    const data = (await parseJsonResponse(response)) as { embeddings?: number[][]; model?: string };
    return { vectors: data.embeddings ?? [], model: data.model ?? resolvedModel };
  }

  if (provider.provider_type === "zeroentropy") {
    if (!apiKey) {
      throw new ProviderInvocationError(400, `ModelProvider '${provider.id}' has no API key credential`);
    }
    const base = provider.base_url?.replace(/\/+$/, "");
    if (!base) throw new ProviderInvocationError(400, "base_url is required for provider_type 'zeroentropy'");
    const body: Record<string, unknown> = {
      model: resolvedModel,
      input: inputs,
      input_type: inputType ?? "document",
      encoding_format: "float",
    };
    if (typeof dimensions === "number" && Number.isInteger(dimensions) && dimensions > 0) {
      body.dimensions = dimensions;
    }
    const response = await httpClient(target.network_profile).fetch(`${base}/models/embed`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify(body),
    });
    const data = (await parseJsonResponse(response)) as {
      results?: Array<{ embedding?: number[] }>;
    };
    return {
      vectors: (data.results ?? []).map((row) => row.embedding ?? []),
      model: resolvedModel,
    };
  }

  if (["openai", "openrouter", "other"].includes(provider.provider_type)) {
    if (!apiKey) {
      throw new ProviderInvocationError(400, `ModelProvider '${provider.id}' has no API key credential`);
    }
    const body: Record<string, unknown> = { model: resolvedModel, input: inputs };
    if (typeof dimensions === "number" && Number.isInteger(dimensions) && dimensions > 0) {
      body.dimensions = dimensions;
    }
    const response = await httpClient(target.network_profile).fetch(`${openAiBase(provider)}/embeddings`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify(body),
    });
    const data = (await parseJsonResponse(response)) as {
      data?: Array<{ embedding: number[]; index?: number }>;
      model?: string;
    };
    const sorted = [...(data.data ?? [])].sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
    return { vectors: sorted.map((row) => row.embedding), model: data.model ?? resolvedModel };
  }

  throw new ProviderInvocationError(
    400,
    `provider_type '${provider.provider_type}' does not support embeddings`,
  );
}

/**
 * Auxiliary native rerank completion. This is intentionally separate from chat
 * completions because rerank providers expose a different request/response
 * contract and may not support generation.
 */
export async function completeProviderRerank(
  store: ProviderCommandStore,
  spaceId: string,
  input: ProviderRerankInput,
): Promise<ProviderRerankResult> {
  if (input.documents.length === 0) return { scores: [], model: "", usage: {} };
  const taskChain = input.task ? await store.getTaskChain(spaceId, input.task) : null;
  if (taskChain) {
    let lastError: unknown = null;
    for (const entry of taskChain) {
      try {
        return await completeProviderRerankWithFallback(
          store,
          spaceId,
          entry.provider_id,
          entry.model,
          input.query,
          input.documents,
          input.topN,
          input.egressPolicy,
        );
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
    if (taskChain.some((entry) => entry.provider_id === input.provider_id)) {
      throw lastError instanceof Error
        ? lastError
        : new ProviderInvocationError(502, "Rerank invocation failed");
    }
  }

  return completeProviderRerankWithFallback(
    store,
    spaceId,
    input.provider_id ?? null,
    input.model,
    input.query,
    input.documents,
    input.topN,
    input.egressPolicy,
  );
}

async function completeProviderRerankWithFallback(
  store: ProviderCommandStore,
  spaceId: string,
  providerId: string | null | undefined,
  model: string | null | undefined,
  query: string,
  documents: string[],
  topN?: number | null,
  egressPolicy?: RetrievalEgressPolicy | null,
): Promise<ProviderRerankResult> {
  const target = await store.getInvocationTarget(spaceId, providerId);
  const chain: InvocationTarget[] = [target];
  for (const fallbackId of target.fallback_provider_ids) {
    try {
      chain.push(await store.getInvocationTarget(spaceId, fallbackId));
    } catch {
      // A missing/disabled fallback provider is skipped, matching chat behavior.
    }
  }

  let lastError: unknown = null;
  for (const [index, candidate] of chain.entries()) {
    if (!providerTargetEgressAllowed(candidate, egressPolicy)) {
      lastError = providerEgressDeniedError(candidate);
      continue;
    }
    try {
      return await invokeRerankProviderWithPool(
        store,
        candidate,
        index === 0 ? model : null,
        query,
        documents,
        topN,
      );
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
    : new ProviderInvocationError(502, "Rerank invocation failed");
}

async function invokeRerankProviderWithPool(
  store: ProviderCommandStore,
  target: InvocationTarget,
  model: string | null | undefined,
  query: string,
  documents: string[],
  topN?: number | null,
): Promise<ProviderRerankResult> {
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
        const result = await rerankOnce(target, candidate.api_key, model, query, documents, topN);
        if (candidate.member_id) {
          await store.recordPoolOutcome(candidate.member_id, { kind: "success" });
        }
        return result;
      } catch (error) {
        lastError = error;
        if (!(error instanceof ProviderInvocationError) || !error.resilience) {
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
          throw error;
        }
        break;
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new ProviderInvocationError(502, "Rerank invocation failed");
}

async function rerankOnce(
  target: InvocationTarget,
  apiKey: string | null,
  model: string | null | undefined,
  query: string,
  documents: string[],
  topN?: number | null,
): Promise<ProviderRerankResult> {
  const provider = target.provider;

  if (provider.provider_type === "zeroentropy") {
    if (!apiKey) {
      throw new ProviderInvocationError(400, `ModelProvider '${provider.id}' has no API key credential`);
    }
    const base = provider.base_url?.replace(/\/+$/, "");
    if (!base) throw new ProviderInvocationError(400, "base_url is required for provider_type 'zeroentropy'");
    const resolvedModel = bareModelName("zeroentropy", model?.trim() || "zerank-2");
    const response = await httpClient(target.network_profile).fetch(`${base}/models/rerank`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model: resolvedModel,
        query,
        documents,
        top_n:
          typeof topN === "number" && Number.isInteger(topN) && topN > 0
            ? Math.min(topN, documents.length)
            : documents.length,
      }),
    });
    const data = (await parseJsonResponse(response)) as {
      results?: Array<{ index?: number; relevance_score?: number }>;
      total_bytes?: number;
      total_tokens?: number;
      e2e_latency?: number;
      inference_latency?: number;
    };
    return {
      scores: (data.results ?? [])
        .map((entry) => ({ index: Number(entry.index), score: Number(entry.relevance_score) }))
        .filter((entry) => Number.isInteger(entry.index) && Number.isFinite(entry.score)),
      model: resolvedModel,
      usage: {
        total_bytes: data.total_bytes,
        total_tokens: data.total_tokens,
        e2e_latency: data.e2e_latency,
        inference_latency: data.inference_latency,
      },
    };
  }

  throw new ProviderInvocationError(
    400,
    `provider_type '${provider.provider_type}' does not support native rerank`,
  );
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
      await httpClient(target.network_profile).fetch(`${provider.base_url.replace(/\/+$/, "")}/api/tags`),
    )) as { models?: Array<{ name?: string }> };
    return {
      models: (data.models ?? []).map((m) => m.name).filter((m): m is string => Boolean(m)),
      source: "live",
    };
  }
  if (["openai", "openrouter", "other"].includes(provider.provider_type)) {
    const headers: Record<string, string> = {};
    if (apiKey) headers.authorization = `Bearer ${apiKey}`;
    const data = (await parseJsonResponse(
      await httpClient(target.network_profile).fetch(`${openAiBase(provider)}/models`, { headers }),
    )) as { data?: Array<{ id?: string }> };
    return {
      models: (data.data ?? []).map((m) => m.id).filter((m): m is string => Boolean(m)),
      source: "live",
    };
  }
  return { models: [], source: "configured" };
}
