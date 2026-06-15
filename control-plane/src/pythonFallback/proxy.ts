/**
 * **Temporary** transparent fallback proxy to the Python backend.
 *
 * Any `/api/v1/*` request not owned by a TS control-plane route is forwarded
 * verbatim to the Python backend. The control plane makes no decision about the
 * request beyond routing it. This module is
 * conceptually temporary: it may be removed once its endpoints are owned by
 * control-plane modules or retired. The control-plane service itself stays.
 *
 * This handler:
 * - forwards method, path, query string and raw body unchanged;
 * - forwards client headers (including Authorization, Cookie, Content-Type,
 *   Accept) minus hop-by-hop headers;
 * - preserves or generates `x-request-id`, and stamps
 *   `x-agent-space-control-plane: ts`;
 * - passes the upstream status, headers and body straight back, **streaming** the
 *   body (so JSON and `text/event-stream` both work without buffering);
 * - does NOT follow redirects or decompress, so 3xx/`Location` and
 *   `content-encoding` are passed through untouched (OAuth-safe, transparent).
 *
 * Uses `undici.request` — the native HTTP client that backs global `fetch` — for
 * faithful proxy semantics without a heavyweight proxy dependency. WebSocket and
 * dedicated SSE keep-alive handling for proxied endpoints are intentionally out
 * of scope; TS-owned run-event SSE lives in `modules/streaming`.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { request as undiciRequest } from "undici";
import type { ControlPlaneConfig } from "../config";
import {
  CONTROL_PLANE_MARKER_HEADER,
  CONTROL_PLANE_MARKER_VALUE,
  REQUEST_ID_HEADER,
  resolveRequestId,
} from "../gateway/requestContext";
import type { ErrorEnvelope } from "../gateway/errorEnvelope";

/**
 * Sanitized transport-failure bodies for the temporary proxy. These keep their
 * established shape (no `request_id` field — the id travels in the
 * `x-request-id` response header) and never leak upstream internals, headers,
 * tokens, cookies, or bodies. Bodies proxied *from* Python are never wrapped.
 */

/** Returned when the Python backend cannot be reached (down, refused, timeout). */
export const PYTHON_BACKEND_UNAVAILABLE: ErrorEnvelope = {
  error: "python_backend_unavailable",
  message: "Python backend is unavailable",
};

/** Returned when the Python fallback proxy is disabled but a fallback route is hit. */
export const PYTHON_FALLBACK_PROXY_DISABLED: ErrorEnvelope = {
  error: "python_fallback_proxy_disabled",
  message: "Python fallback proxy is disabled on this control plane",
};

/** Status code carried alongside an unavailable-backend response. */
export const PYTHON_BACKEND_UNAVAILABLE_STATUS = 502;

/** Hop-by-hop headers (RFC 7230 §6.1) plus framing headers we must not forward. */
const HOP_BY_HOP_REQUEST = new Set([
  "host",
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "content-length",
]);

const HOP_BY_HOP_RESPONSE = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function buildUpstreamHeaders(
  request: FastifyRequest,
  requestId: string,
): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(request.headers)) {
    if (value === undefined) continue;
    if (HOP_BY_HOP_REQUEST.has(key.toLowerCase())) continue;
    out[key] = value;
  }
  // Routing/trace metadata. These never carry secrets.
  out[CONTROL_PLANE_MARKER_HEADER] = CONTROL_PLANE_MARKER_VALUE;
  out[REQUEST_ID_HEADER] = requestId;
  return out;
}

function copyResponseHeaders(
  headers: Record<string, string | string[] | undefined>,
  reply: FastifyReply,
): void {
  for (const [key, value] of Object.entries(headers)) {
    if (value === undefined) continue;
    if (HOP_BY_HOP_RESPONSE.has(key.toLowerCase())) continue;
    reply.header(key, value);
  }
}

/**
 * Register the catch-all Python fallback for `/api/v1/*`. Must be
 * registered AFTER all TS-owned control-plane routes so that specific routes win.
 */
export function registerPythonFallbackProxy(
  app: FastifyInstance,
  config: ControlPlaneConfig,
): void {
  app.all("/api/v1/*", async (request, reply) => {
    if (!config.enablePythonFallbackProxy) {
      return reply.code(503).send(PYTHON_FALLBACK_PROXY_DISABLED);
    }

    const requestId = resolveRequestId(request);

    // request.url is the raw path + query string, forwarded unchanged.
    const upstreamUrl = `${config.pythonApiBaseUrl}${request.url}`;
    const method = request.method.toUpperCase();
    const hasBody = method !== "GET" && method !== "HEAD";
    // The catch-all content-type parser buffers the raw body (see server.ts).
    const body =
      hasBody && request.body instanceof Buffer && request.body.length > 0
        ? request.body
        : undefined;

    reply.header(REQUEST_ID_HEADER, requestId);

    try {
      const upstream = await undiciRequest(upstreamUrl, {
        method: method as "GET",
        headers: buildUpstreamHeaders(request, requestId),
        body,
        maxRedirections: 0, // pass 3xx + Location through untouched
        signal: AbortSignal.timeout(config.requestTimeoutMs),
      });

      reply.code(upstream.statusCode);
      copyResponseHeaders(upstream.headers, reply);
      // undici's body is a Node Readable — stream it straight through (handles
      // JSON and text/event-stream alike, without buffering).
      return reply.send(upstream.body);
    } catch (err) {
      // Connection refused / DNS failure / timeout / aborted — never leak detail.
      request.log.warn(
        { method, path: request.url, reason: errKind(err) },
        "python fallback proxy failed",
      );
      return reply
        .code(PYTHON_BACKEND_UNAVAILABLE_STATUS)
        .send(PYTHON_BACKEND_UNAVAILABLE);
    }
  });
}

/** A coarse, secret-free classification of a proxy failure for logging. */
function errKind(err: unknown): string {
  if (err && typeof err === "object") {
    const code = (err as { code?: string }).code;
    const name = (err as { name?: string }).name;
    if (name === "TimeoutError" || name === "AbortError") return "timeout";
    if (typeof code === "string") return code; // e.g. ECONNREFUSED, ENOTFOUND
  }
  return "upstream_error";
}
