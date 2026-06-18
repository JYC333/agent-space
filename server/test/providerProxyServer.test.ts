import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { ProviderProxyLeaseRegistry } from "../src/modules/providers/providerProxyLease";
import { startProviderProxyServer, type ProviderProxyServerHandle } from "../src/modules/providers/providerProxyServer";
import { startMockUpstream, type MockUpstream } from "./support/mockUpstream";

const handles: ProviderProxyServerHandle[] = [];
const upstreams: MockUpstream[] = [];

afterEach(async () => {
  for (const handle of handles.splice(0).reverse()) {
    await handle.close();
  }
  for (const upstream of upstreams.splice(0).reverse()) {
    await upstream.close();
  }
});

function config() {
  return loadConfig({
    SERVER_DATABASE_URL: "postgresql://server@db:5432/agent_space",
  });
}

describe("provider proxy server", () => {
  it("forwards a Claude-compatible request with provider credentials instead of the lease token", async () => {
    const upstream = await startMockUpstream();
    upstreams.push(upstream);
    const leases = new ProviderProxyLeaseRegistry();
    const proxy = await startProviderProxyServer(config(), {
      leaseRegistry: leases,
      commandStore: {
        async resolveProviderApiKey(spaceId, providerId) {
          expect(spaceId).toBe("space-1");
          expect(providerId).toBe("provider-1");
          return "provider-secret";
        },
      },
    });
    handles.push(proxy);
    const lease = leases.create({
      run_id: "run-1",
      space_id: "space-1",
      provider_id: "provider-1",
      upstream_base_url: `${upstream.baseUrl}/anthropic`,
      model: "MiniMax-M2.7",
      ttl_ms: 60_000,
    });

    const response = await fetch(`${proxy.baseUrl}/anthropic/${lease.id}/v1/messages?trace=1`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${lease.token}`,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": "lease-token-must-not-pass",
      },
      body: JSON.stringify({ model: "MiniMax-M2.7", messages: [] }),
    });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      ok: true,
      seen_path: "/anthropic/v1/messages?trace=1",
    });
    expect(upstream.requests).toHaveLength(1);
    expect(upstream.requests[0]).toMatchObject({
      method: "POST",
      url: "/anthropic/v1/messages?trace=1",
      body: JSON.stringify({ model: "MiniMax-M2.7", messages: [] }),
    });
    expect(upstream.requests[0].headers.authorization).toBe("Bearer provider-secret");
    expect(upstream.requests[0].headers["x-api-key"]).toBe("provider-secret");
    expect(upstream.requests[0].headers["anthropic-version"]).toBe("2023-06-01");
  });

  it("rejects invalid lease tokens before reaching the upstream provider", async () => {
    const upstream = await startMockUpstream();
    upstreams.push(upstream);
    const leases = new ProviderProxyLeaseRegistry();
    const proxy = await startProviderProxyServer(config(), {
      leaseRegistry: leases,
      commandStore: {
        async resolveProviderApiKey() {
          return "provider-secret";
        },
      },
    });
    handles.push(proxy);
    const lease = leases.create({
      run_id: "run-1",
      space_id: "space-1",
      provider_id: "provider-1",
      upstream_base_url: upstream.baseUrl,
      ttl_ms: 60_000,
    });

    const response = await fetch(`${proxy.baseUrl}/anthropic/${lease.id}/v1/messages`, {
      method: "POST",
      headers: {
        authorization: "Bearer wrong-token",
        "content-type": "application/json",
      },
      body: "{}",
    });

    expect(response.status).toBe(401);
    expect(upstream.requests).toHaveLength(0);
  });

  it("forwards an OpenAI-compatible request with bearer provider credentials", async () => {
    const upstream = await startMockUpstream();
    upstreams.push(upstream);
    const leases = new ProviderProxyLeaseRegistry();
    const proxy = await startProviderProxyServer(config(), {
      leaseRegistry: leases,
      commandStore: {
        async resolveProviderApiKey(spaceId, providerId) {
          expect(spaceId).toBe("space-1");
          expect(providerId).toBe("provider-openai");
          return "provider-secret";
        },
      },
    });
    handles.push(proxy);
    const lease = leases.create({
      run_id: "run-1",
      space_id: "space-1",
      provider_id: "provider-openai",
      route: "openai",
      upstream_base_url: `${upstream.baseUrl}/v1`,
      model: "MiniMax-M3",
      ttl_ms: 60_000,
    });

    const response = await fetch(`${proxy.baseUrl}/openai/${lease.id}/responses`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${lease.token}`,
        "content-type": "application/json",
        "x-api-key": "lease-token-must-not-pass",
      },
      body: JSON.stringify({ model: "MiniMax-M3", input: "hello" }),
    });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      ok: true,
      seen_path: "/v1/responses",
    });
    expect(upstream.requests).toHaveLength(1);
    expect(upstream.requests[0]).toMatchObject({
      method: "POST",
      url: "/v1/responses",
      body: JSON.stringify({ model: "MiniMax-M3", input: "hello" }),
    });
    expect(upstream.requests[0].headers.authorization).toBe("Bearer provider-secret");
    expect(upstream.requests[0].headers["x-api-key"]).toBeUndefined();
  });
});
