import { ProxyAgent, fetch as undiciFetch } from "undici";

// See invocation.ts's PROVIDER_KEEPALIVE_INITIAL_DELAY_MS: undici's default
// 60s keepalive initial delay can lose the race against a NAT/idle-connection
// timeout in front of a provider while a proxied request is still in flight.
const PROXY_KEEPALIVE_INITIAL_DELAY_MS = 15_000;

export type NetworkProfileMode = "direct" | "http_proxy";

export interface ResolvedNetworkProfile {
  id: string;
  space_id: string;
  name: string;
  mode: NetworkProfileMode;
  proxy_url: string | null;
  no_proxy: string | null;
  enabled: boolean;
}

export function validateNetworkProfileInput(input: {
  mode: string;
  proxy_url?: string | null;
  no_proxy?: string | null;
}): { mode: NetworkProfileMode; proxy_url: string | null; no_proxy: string | null } {
  const mode = input.mode;
  if (mode !== "direct" && mode !== "http_proxy") {
    throw new Error("mode must be one of: direct, http_proxy");
  }
  const proxyUrl = trimmed(input.proxy_url);
  if (mode === "direct") {
    return { mode, proxy_url: null, no_proxy: trimmed(input.no_proxy) };
  }
  if (!proxyUrl) {
    throw new Error("proxy_url is required when mode is http_proxy");
  }
  const parsed = parseUrl(proxyUrl, "proxy_url must be a valid URL");
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("proxy_url must use http:// or https://");
  }
  if (parsed.username || parsed.password) {
    throw new Error("proxy_url must not contain credentials");
  }
  return { mode, proxy_url: proxyUrl, no_proxy: trimmed(input.no_proxy) };
}

export function envForNetworkProfile(
  profile: ResolvedNetworkProfile | null | undefined,
): Record<string, string> {
  if (!profile?.enabled || profile.mode !== "http_proxy" || !profile.proxy_url) return {};
  const env: Record<string, string> = {
    HTTP_PROXY: profile.proxy_url,
    HTTPS_PROXY: profile.proxy_url,
    ALL_PROXY: profile.proxy_url,
    http_proxy: profile.proxy_url,
    https_proxy: profile.proxy_url,
    all_proxy: profile.proxy_url,
  };
  if (profile.no_proxy?.trim()) {
    env.NO_PROXY = profile.no_proxy.trim();
    env.no_proxy = profile.no_proxy.trim();
  }
  return env;
}

export function shouldBypassProxy(url: string, noProxy: string | null | undefined): boolean {
  const value = trimmed(noProxy);
  if (!value) return false;
  const host = hostForUrl(url);
  if (!host) return false;
  const normalizedHost = stripPort(host).toLowerCase();
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .some((entry) => noProxyEntryMatches(normalizedHost, entry));
}

export function fetchWithNetworkProfile(
  profile: ResolvedNetworkProfile | null | undefined,
): typeof fetch {
  if (!profile?.enabled || profile.mode !== "http_proxy" || !profile.proxy_url) {
    return globalThis.fetch.bind(globalThis);
  }
  const proxyUrl = profile.proxy_url;
  return ((url: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
    const target = typeof url === "string" ? url : url instanceof URL ? url.toString() : url.url;
    if (shouldBypassProxy(target, profile.no_proxy)) {
      return globalThis.fetch(url, init);
    }
    const dispatcher = new ProxyAgent({
      uri: proxyUrl,
      requestTls: { keepAlive: true, keepAliveInitialDelay: PROXY_KEEPALIVE_INITIAL_DELAY_MS },
      proxyTls: { keepAlive: true, keepAliveInitialDelay: PROXY_KEEPALIVE_INITIAL_DELAY_MS },
    });
    return undiciFetch(url, { ...(init ?? {}), dispatcher } as Parameters<typeof undiciFetch>[1]);
  }) as typeof fetch;
}

function noProxyEntryMatches(host: string, rawEntry: string): boolean {
  if (rawEntry === "*") return true;
  const entryHost = stripPort(hostForEntry(rawEntry)).toLowerCase();
  if (!entryHost) return false;
  if (entryHost.startsWith("*.")) {
    const suffix = entryHost.slice(1);
    return host.endsWith(suffix);
  }
  if (entryHost.startsWith(".")) {
    const suffix = entryHost.slice(1);
    return host === suffix || host.endsWith(`.${suffix}`);
  }
  return host === entryHost;
}

function hostForEntry(value: string): string {
  if (value.includes("://")) {
    try {
      return new URL(value).host;
    } catch {
      return value;
    }
  }
  return value;
}

function hostForUrl(value: string): string | null {
  try {
    return new URL(value).host;
  } catch {
    return null;
  }
}

function stripPort(value: string): string {
  if (value.startsWith("[") && value.includes("]")) {
    return value.slice(1, value.indexOf("]"));
  }
  const colon = value.lastIndexOf(":");
  if (colon > -1 && value.indexOf(":") === colon) return value.slice(0, colon);
  return value;
}

function parseUrl(value: string, message: string): URL {
  try {
    return new URL(value);
  } catch {
    throw new Error(message);
  }
}

function trimmed(value: string | null | undefined): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
