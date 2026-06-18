import { describe, expect, it } from "vitest";
import {
  envForNetworkProfile,
  shouldBypassProxy,
  validateNetworkProfileInput,
  type ResolvedNetworkProfile,
} from "../src/modules/networkProfiles";

function profile(overrides: Partial<ResolvedNetworkProfile> = {}): ResolvedNetworkProfile {
  return {
    id: "network-1",
    space_id: "space-1",
    name: "Local proxy",
    mode: "http_proxy",
    proxy_url: "http://127.0.0.1:7890",
    no_proxy: "localhost,127.0.0.1,::1,.internal",
    enabled: true,
    ...overrides,
  };
}

describe("network profile transport", () => {
  it("validates HTTP proxy profiles and rejects credential-bearing or socks URLs", () => {
    expect(validateNetworkProfileInput({
      mode: "http_proxy",
      proxy_url: "http://127.0.0.1:7890",
    })).toMatchObject({
      mode: "http_proxy",
      proxy_url: "http://127.0.0.1:7890",
    });

    expect(() => validateNetworkProfileInput({
      mode: "http_proxy",
      proxy_url: "socks5://127.0.0.1:7891",
    })).toThrow("http:// or https://");

    expect(() => validateNetworkProfileInput({
      mode: "http_proxy",
      proxy_url: "http://user:pass@proxy.example.com:8080",
    })).toThrow("must not contain credentials");
  });

  it("turns enabled HTTP proxy profiles into safe CLI proxy env", () => {
    expect(envForNetworkProfile(profile())).toMatchObject({
      HTTP_PROXY: "http://127.0.0.1:7890",
      HTTPS_PROXY: "http://127.0.0.1:7890",
      ALL_PROXY: "http://127.0.0.1:7890",
      NO_PROXY: "localhost,127.0.0.1,::1,.internal",
      http_proxy: "http://127.0.0.1:7890",
    });

    expect(envForNetworkProfile(profile({ enabled: false }))).toEqual({});
    expect(envForNetworkProfile(profile({ mode: "direct", proxy_url: null }))).toEqual({});
  });

  it("matches no_proxy exact hosts, ports, suffixes, and wildcard", () => {
    expect(shouldBypassProxy("http://localhost:3000/api", "localhost")).toBe(true);
    expect(shouldBypassProxy("http://127.0.0.1:11434/api", "127.0.0.1")).toBe(true);
    expect(shouldBypassProxy("https://api.internal/v1", ".internal")).toBe(true);
    expect(shouldBypassProxy("https://api.example.com/v1", "*.example.com")).toBe(true);
    expect(shouldBypassProxy("https://api.openai.com/v1", "*")).toBe(true);
    expect(shouldBypassProxy("https://api.openai.com/v1", "localhost,.internal")).toBe(false);
  });
});
