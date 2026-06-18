import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";

export interface ProviderProxyLeaseInput {
  run_id: string;
  space_id: string;
  provider_id: string;
  network_profile_id?: string | null;
  route?: ProviderProxyRoute;
  upstream_base_url: string;
  model?: string | null;
  ttl_ms: number;
}

export type ProviderProxyRoute = "anthropic" | "openai";

export interface ProviderProxyLease {
  id: string;
  token: string;
  run_id: string;
  space_id: string;
  provider_id: string;
  network_profile_id: string | null;
  route: ProviderProxyRoute;
  upstream_base_url: string;
  model: string | null;
  expires_at: string;
}

export interface ResolvedProviderProxyLease {
  id: string;
  token_hash: Buffer;
  run_id: string;
  space_id: string;
  provider_id: string;
  network_profile_id: string | null;
  route: ProviderProxyRoute;
  upstream_base_url: string;
  model: string | null;
  expires_at_ms: number;
}

function hashToken(token: string): Buffer {
  return createHash("sha256").update(token).digest();
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

let processProviderProxyBaseUrl: string | null = null;

export function setProviderProxyBaseUrlForProcess(baseUrl: string | null): void {
  processProviderProxyBaseUrl = baseUrl ? baseUrl.replace(/\/+$/, "") : null;
}

export function providerProxyLeaseBaseUrl(route: ProviderProxyRoute, leaseId: string): string {
  if (!processProviderProxyBaseUrl) {
    throw new Error("Provider proxy listener is not started.");
  }
  return `${processProviderProxyBaseUrl}/${route}/${encodeURIComponent(leaseId)}`;
}

export class ProviderProxyLeaseRegistry {
  private readonly leases = new Map<string, ResolvedProviderProxyLease>();

  create(input: ProviderProxyLeaseInput): ProviderProxyLease {
    this.pruneExpired();
    const token = randomBytes(32).toString("base64url");
    const record: ResolvedProviderProxyLease = {
      id: randomUUID(),
      token_hash: hashToken(token),
      run_id: input.run_id,
      space_id: input.space_id,
      provider_id: input.provider_id,
      network_profile_id: input.network_profile_id ?? null,
      route: input.route ?? "anthropic",
      upstream_base_url: normalizeBaseUrl(input.upstream_base_url),
      model: input.model ?? null,
      expires_at_ms: Date.now() + Math.max(input.ttl_ms, 1_000),
    };
    this.leases.set(record.id, record);
    return {
      id: record.id,
      token,
      run_id: record.run_id,
      space_id: record.space_id,
      provider_id: record.provider_id,
      network_profile_id: record.network_profile_id,
      route: record.route,
      upstream_base_url: record.upstream_base_url,
      model: record.model,
      expires_at: new Date(record.expires_at_ms).toISOString(),
    };
  }

  resolve(id: string, token: string): ResolvedProviderProxyLease | null {
    const lease = this.leases.get(id);
    if (!lease) return null;
    if (lease.expires_at_ms <= Date.now()) {
      this.leases.delete(id);
      return null;
    }
    const presented = hashToken(token);
    if (
      presented.length !== lease.token_hash.length ||
      !timingSafeEqual(presented, lease.token_hash)
    ) {
      return null;
    }
    return lease;
  }

  revoke(id: string): void {
    this.leases.delete(id);
  }

  revokeRun(runId: string): void {
    for (const [id, lease] of this.leases) {
      if (lease.run_id === runId) this.leases.delete(id);
    }
  }

  size(): number {
    this.pruneExpired();
    return this.leases.size;
  }

  private pruneExpired(): void {
    const now = Date.now();
    for (const [id, lease] of this.leases) {
      if (lease.expires_at_ms <= now) this.leases.delete(id);
    }
  }
}

export const providerProxyLeases = new ProviderProxyLeaseRegistry();
