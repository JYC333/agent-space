import { join } from "node:path";
import type { ServerConfig } from "../../config";
import type { CredentialGrant } from "../providers/cli/credentialBroker";
import { resolveProvidersDbPort } from "../providers/dbReader";
import {
  providerProxyLeaseBaseUrl,
  providerProxyLeases,
  type ProviderProxyLeaseRegistry,
  type ProviderProxyRoute,
} from "../providers/proxy/lease";
import type { LocalCliRuntimeAdapterSpec } from "../runtimeAdapters";
import type { RunRecord } from "./repository";
import {
  CodexProviderConfigError,
  writeCodexProviderConfig,
} from "./codexProviderConfig";

export interface RuntimeProviderResolverPort {
  getProvider(
    spaceId: string,
    userId: string | null,
    providerId: string,
  ): Promise<unknown | null>;
}

export interface RuntimeProviderBinding {
  env: Record<string, string>;
  lease_id: string | null;
  lease_registry: ProviderProxyLeaseRegistry | null;
  model: string | null;
  provider_id: string | null;
  protocol: "anthropic" | "openai_responses" | null;
}

export class RuntimeProviderBindingError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RuntimeProviderBindingError";
  }
}

export async function buildRuntimeProviderBinding(
  config: ServerConfig,
  input: {
    run: RunRecord;
    model: string | null;
  },
  spec: LocalCliRuntimeAdapterSpec,
  deps: {
    credential: CredentialGrant;
    providerResolver?: RuntimeProviderResolverPort;
    leaseRegistry?: ProviderProxyLeaseRegistry;
    proxyBaseUrl?: string;
    ttlSeconds: number;
  },
): Promise<RuntimeProviderBinding> {
  if (spec.adapter_type !== "claude_code" && spec.adapter_type !== "codex_cli") {
    return emptyRuntimeProviderBinding();
  }
  const providerId = input.run.model_provider_id;
  if (!providerId) {
    return spec.adapter_type === "codex_cli"
      ? codexHomeOnlyBinding(deps.credential)
      : emptyRuntimeProviderBinding();
  }

  const provider = await resolveRuntimeProvider(config, input.run, providerId, deps.providerResolver);
  if (spec.adapter_type === "claude_code") {
    return buildClaudeProviderBinding(input, providerId, provider, deps);
  }
  return buildCodexProviderBinding(input, providerId, provider, deps);
}

export function cleanupRuntimeProviderBinding(binding: RuntimeProviderBinding): void {
  if (binding.lease_id) binding.lease_registry?.revoke(binding.lease_id);
}

async function resolveRuntimeProvider(
  config: ServerConfig,
  run: RunRecord,
  providerId: string,
  providerResolver?: RuntimeProviderResolverPort,
): Promise<Record<string, unknown>> {
  const resolver = providerResolver ?? resolveProvidersDbPort(config);
  if (!resolver) {
    throw new RuntimeProviderBindingError(
      "providers_db_unavailable",
      "Provider database read port is unavailable.",
    );
  }
  const provider = recordValue(await resolver.getProvider(run.space_id, null, providerId));
  if (Object.keys(provider).length === 0) {
    throw new RuntimeProviderBindingError(
      "model_provider_not_found",
      `ModelProvider '${providerId}' not found.`,
    );
  }
  return provider;
}

function buildClaudeProviderBinding(
  input: {
    run: RunRecord;
    model: string | null;
  },
  providerId: string,
  provider: Record<string, unknown>,
  deps: {
    leaseRegistry?: ProviderProxyLeaseRegistry;
    proxyBaseUrl?: string;
    ttlSeconds: number;
  },
): RuntimeProviderBinding {
  const baseUrl = stringValue(provider.claude_compatible_base_url);
  if (!baseUrl) {
    throw new RuntimeProviderBindingError(
      "claude_compatible_base_url_required",
      `ModelProvider '${providerId}' is not configured with a Claude-compatible URL.`,
    );
  }

  const model =
    input.model ??
    modelFromRun(input.run) ??
    stringValue(provider.default_model) ??
    firstString(provider.available_models) ??
    null;
  const leaseRegistry = deps.leaseRegistry ?? providerProxyLeases;
  const lease = leaseRegistry.create({
    run_id: input.run.id,
    space_id: input.run.space_id,
    provider_id: providerId,
    network_profile_id: stringValue(provider.network_profile_id),
    route: "anthropic",
    upstream_base_url: baseUrl,
    model,
    ttl_ms: Math.max(deps.ttlSeconds, 1) * 1000,
  });
  const env: Record<string, string> = {
    ANTHROPIC_BASE_URL: runtimeProviderProxyUrl("anthropic", lease.id, deps.proxyBaseUrl),
    ANTHROPIC_AUTH_TOKEN: lease.token,
  };
  if (model) {
    env.ANTHROPIC_MODEL = model;
    env.ANTHROPIC_DEFAULT_SONNET_MODEL = model;
    env.ANTHROPIC_DEFAULT_OPUS_MODEL = model;
    env.ANTHROPIC_DEFAULT_HAIKU_MODEL = model;
  }
  return {
    env,
    lease_id: lease.id,
    lease_registry: leaseRegistry,
    model,
    provider_id: providerId,
    protocol: "anthropic",
  };
}

async function buildCodexProviderBinding(
  input: {
    run: RunRecord;
    model: string | null;
  },
  providerId: string,
  provider: Record<string, unknown>,
  deps: {
    credential: CredentialGrant;
    leaseRegistry?: ProviderProxyLeaseRegistry;
    proxyBaseUrl?: string;
    ttlSeconds: number;
  },
): Promise<RuntimeProviderBinding> {
  const baseUrl = stringValue(provider.openai_compatible_base_url);
  if (!baseUrl) {
    throw new RuntimeProviderBindingError(
      "openai_compatible_base_url_required",
      `ModelProvider '${providerId}' is not configured with an OpenAI-compatible URL.`,
    );
  }
  const model =
    input.model ??
    modelFromRun(input.run) ??
    stringValue(provider.default_model) ??
    firstString(provider.available_models) ??
    null;
  if (!model) {
    throw new RuntimeProviderBindingError(
      "codex_model_required",
      `ModelProvider '${providerId}' must provide a model for Codex CLI.`,
    );
  }

  const leaseRegistry = deps.leaseRegistry ?? providerProxyLeases;
  const lease = leaseRegistry.create({
    run_id: input.run.id,
    space_id: input.run.space_id,
    provider_id: providerId,
    network_profile_id: stringValue(provider.network_profile_id),
    route: "openai",
    upstream_base_url: baseUrl,
    model,
    ttl_ms: Math.max(deps.ttlSeconds, 1) * 1000,
  });
  let codexHome: string;
  try {
    codexHome = await writeCodexProviderConfig({
      tempHome: deps.credential.temp_home,
      providerName: stringValue(provider.name) ?? "Agent Space Provider",
      proxyBaseUrl: runtimeProviderProxyUrl("openai", lease.id, deps.proxyBaseUrl),
      leaseToken: lease.token,
      model,
      availableModels: stringArray(provider.available_models),
    });
  } catch (error) {
    leaseRegistry.revoke(lease.id);
    if (error instanceof CodexProviderConfigError) {
      throw new RuntimeProviderBindingError(error.code, error.message);
    }
    throw error;
  }

  return {
    env: { CODEX_HOME: codexHome },
    lease_id: lease.id,
    lease_registry: leaseRegistry,
    model,
    provider_id: providerId,
    protocol: "openai_responses",
  };
}

function codexHomeOnlyBinding(credential: CredentialGrant): RuntimeProviderBinding {
  const codexHome = credential.temp_home ? join(credential.temp_home, ".codex") : null;
  return {
    env: codexHome ? { CODEX_HOME: codexHome } : {},
    lease_id: null,
    lease_registry: null,
    model: null,
    provider_id: null,
    protocol: null,
  };
}

function emptyRuntimeProviderBinding(): RuntimeProviderBinding {
  return {
    env: {},
    lease_id: null,
    lease_registry: null,
    model: null,
    provider_id: null,
    protocol: null,
  };
}

function runtimeProviderProxyUrl(
  route: ProviderProxyRoute,
  leaseId: string,
  proxyBaseUrl?: string,
): string {
  if (proxyBaseUrl) {
    return `${proxyBaseUrl.replace(/\/+$/, "")}/${route}/${encodeURIComponent(leaseId)}`;
  }
  return providerProxyLeaseBaseUrl(route, leaseId);
}

function modelFromRun(run: RunRecord): string | null {
  return stringValue(recordValue(run.model_override_json).model);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function firstString(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  for (const item of value) {
    if (typeof item === "string" && item.trim()) return item.trim();
  }
  return null;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => (typeof item === "string" && item.trim() ? [item.trim()] : []));
}
