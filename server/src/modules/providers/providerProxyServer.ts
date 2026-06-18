import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { Readable } from "node:stream";
import type { ServerConfig } from "../../config";
import {
  ProviderCommandValidationError,
  resolveProviderCommandStore,
  type ProviderCommandStore,
} from "./providerCommandStore";
import {
  providerProxyLeases,
  setProviderProxyBaseUrlForProcess,
  type ProviderProxyLeaseRegistry,
  type ProviderProxyRoute,
} from "./providerProxyLease";
import {
  fetchWithNetworkProfile,
  resolveNetworkProfileRepository,
} from "../networkProfiles";

const MAX_PROXY_REQUEST_BYTES = 32 * 1024 * 1024;
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export interface ProviderProxyServerHandle {
  baseUrl: string;
  close(): Promise<void>;
}

export interface ProviderProxyServerDeps {
  leaseRegistry?: ProviderProxyLeaseRegistry;
  commandStore?: Pick<ProviderCommandStore, "resolveProviderApiKey">;
  fetch?: typeof fetch;
}

export async function startProviderProxyServer(
  config: ServerConfig,
  deps: ProviderProxyServerDeps = {},
): Promise<ProviderProxyServerHandle> {
  const leaseRegistry = deps.leaseRegistry ?? providerProxyLeases;
  const server = createServer((request, response) => {
    void handleProviderProxyRequest(config, request, response, {
      leaseRegistry,
      commandStore: deps.commandStore,
      fetch: deps.fetch,
    }).catch(() => {
      if (!response.headersSent) {
        sendJson(response, 502, { error: "provider_proxy_failed" });
      } else {
        response.destroy();
      }
    });
  });

  const host = "127.0.0.1";
  await listen(server, host, 0);
  const address = server.address() as AddressInfo;
  const baseUrl = `http://${host}:${address.port}`;
  setProviderProxyBaseUrlForProcess(baseUrl);
  return {
    baseUrl,
    close: () =>
      new Promise<void>((resolve, reject) =>
        server.close((err) => {
          setProviderProxyBaseUrlForProcess(null);
          return err ? reject(err) : resolve();
        }),
      ),
  };
}

async function handleProviderProxyRequest(
  config: ServerConfig,
  request: IncomingMessage,
  response: ServerResponse,
  deps: {
    leaseRegistry: ProviderProxyLeaseRegistry;
    commandStore?: Pick<ProviderCommandStore, "resolveProviderApiKey">;
    fetch?: typeof fetch;
  },
): Promise<void> {
  const parsed = new URL(request.url ?? "/", "http://provider-proxy.local");
  const parts = parsed.pathname.split("/").filter(Boolean);
  const route = providerProxyRoute(parts[0]);
  if (!route || !parts[1]) {
    sendJson(response, 404, { error: "provider_proxy_route_not_found" });
    return;
  }

  const token = requestLeaseToken(request);
  if (!token) {
    sendJson(response, 401, { error: "provider_proxy_token_required" });
    return;
  }

  const lease = deps.leaseRegistry.resolve(decodeURIComponent(parts[1]), token);
  if (!lease || lease.route !== route) {
    sendJson(response, 401, { error: "provider_proxy_token_invalid" });
    return;
  }

  let apiKey: string;
  try {
    const commandStore = deps.commandStore ?? resolveProviderCommandStore(config);
    apiKey = await commandStore.resolveProviderApiKey(lease.space_id, lease.provider_id);
  } catch (error) {
    const status = error instanceof ProviderCommandValidationError ? 400 : 404;
    sendJson(response, status, { error: "provider_proxy_credential_unavailable" });
    return;
  }

  const body = await readBody(request);
  const upstreamUrl = upstreamRequestUrl(
    lease.upstream_base_url,
    `/${parts.slice(2).join("/")}`,
    parsed.search,
  );
  const fetchImpl = await fetchForLease(config, lease, deps.fetch);
  const upstream = await fetchImpl(upstreamUrl, {
    method: request.method ?? "GET",
    headers: upstreamHeaders(route, request, apiKey),
    body: methodMayHaveBody(request.method) ? body : undefined,
  });

  response.statusCode = upstream.status;
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      response.setHeader(key, value);
    }
  });
  if (!upstream.body) {
    response.end();
    return;
  }
  Readable.fromWeb(upstream.body).pipe(response);
}

async function fetchForLease(
  config: ServerConfig,
  lease: { space_id: string; network_profile_id: string | null },
  override?: typeof fetch,
): Promise<typeof fetch> {
  if (override) return override;
  const profile = await resolveNetworkProfileRepository(config).resolve(
    lease.space_id,
    lease.network_profile_id,
  );
  return fetchWithNetworkProfile(profile);
}

function providerProxyRoute(value: string | undefined): ProviderProxyRoute | null {
  return value === "anthropic" || value === "openai" ? value : null;
}

function listen(server: Server, host: string, port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (error: Error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, host);
  });
}

function requestLeaseToken(request: IncomingMessage): string | null {
  const auth = firstHeader(request.headers.authorization);
  if (auth) {
    const match = /^Bearer\s+(.+)$/i.exec(auth.trim());
    if (match?.[1]) return match[1].trim();
  }
  return (
    firstHeader(request.headers["anthropic-auth-token"]) ??
    firstHeader(request.headers["x-api-key"]) ??
    null
  );
}

function firstHeader(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

async function readBody(request: IncomingMessage): Promise<Buffer> {
  if (!methodMayHaveBody(request.method)) return Buffer.alloc(0);
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > MAX_PROXY_REQUEST_BYTES) {
      throw new Error("provider proxy request body too large");
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks);
}

function methodMayHaveBody(method: string | undefined): boolean {
  const normalized = (method ?? "GET").toUpperCase();
  return normalized !== "GET" && normalized !== "HEAD";
}

function upstreamHeaders(
  route: ProviderProxyRoute,
  request: IncomingMessage,
  apiKey: string,
): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const [key, value] of Object.entries(request.headers)) {
    const normalized = key.toLowerCase();
    if (
      HOP_BY_HOP_HEADERS.has(normalized) ||
      normalized === "host" ||
      normalized === "content-length" ||
      normalized === "authorization" ||
      normalized === "x-api-key" ||
      normalized === "anthropic-auth-token"
    ) {
      continue;
    }
    const first = firstHeader(value);
    if (first !== null) headers[key] = first;
  }
  headers.authorization = `Bearer ${apiKey}`;
  if (route === "anthropic") headers["x-api-key"] = apiKey;
  return headers;
}

function upstreamRequestUrl(baseUrl: string, path: string, search: string): string {
  const suffix = path === "/" ? "" : path;
  return `${baseUrl.replace(/\/+$/, "")}${suffix}${search}`;
}

function sendJson(
  response: ServerResponse,
  statusCode: number,
  body: Record<string, unknown>,
): void {
  response.writeHead(statusCode, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}
