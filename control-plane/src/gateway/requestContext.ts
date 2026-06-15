/**
 * Per-request context helpers for the control-plane gateway entry layer.
 *
 * The "gateway" is the permanent entry/routing layer of the control plane (as
 * opposed to the temporary Python fallback proxy). These helpers carry the
 * cross-cutting request metadata — request id continuity, safe header access,
 * and the control-plane marker header — that every control-plane path
 * (TS-owned or proxied) shares.
 *
 * This is metadata only. No auth tokens are parsed or validated here; Python
 * remains the authority for authentication and authorization.
 */

import type { FastifyRequest } from "fastify";
import { randomUUID } from "node:crypto";

/** Standard correlation id header, preserved end-to-end. */
export const REQUEST_ID_HEADER = "x-request-id";

/**
 * Marker stamped on requests/responses that passed through the control plane. It
 * is trace metadata only — never a grant of trust. Python still authenticates and
 * authorizes every request.
 */
export const CONTROL_PLANE_MARKER_HEADER = "x-agent-space-control-plane";
export const CONTROL_PLANE_MARKER_VALUE = "ts";

/**
 * Headers that carry secrets. `readHeader` refuses to return them so that
 * context/log helpers can never accidentally surface a credential. The fallback
 * proxy forwards them verbatim via its own header-copy path, which is the only
 * sanctioned reader.
 */
const SENSITIVE_HEADERS = new Set(["authorization", "cookie", "proxy-authorization"]);

/** Preserve an incoming `x-request-id`, or generate one if absent. */
export function resolveRequestId(request: FastifyRequest): string {
  const incoming = request.headers[REQUEST_ID_HEADER];
  const value = Array.isArray(incoming) ? incoming[0] : incoming;
  return value || randomUUID();
}

/**
 * Read a single non-sensitive header value. Returns `undefined` for absent
 * headers and for the sensitive set (Authorization, Cookie, …) — those must
 * never flow through context helpers, error bodies, or logs.
 */
export function readHeader(request: FastifyRequest, name: string): string | undefined {
  const key = name.toLowerCase();
  if (SENSITIVE_HEADERS.has(key)) return undefined;
  const value = request.headers[key];
  return Array.isArray(value) ? value[0] : value;
}

/**
 * Client-facing request metadata shared by TS-owned routes. Future identity
 * fields (user/space/actor) belong here as *placeholders* once auth context is
 * introduced — the control plane will still not validate tokens itself.
 */
export interface RequestContext {
  /** Preserved or generated correlation id for this request. */
  requestId: string;
  method: string;
  /** Raw path + query string as received. */
  path: string;
}

/** Build the standard request context for a TS-owned route handler. */
export function buildRequestContext(request: FastifyRequest): RequestContext {
  return {
    requestId: resolveRequestId(request),
    method: request.method,
    path: request.url,
  };
}
