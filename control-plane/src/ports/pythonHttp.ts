/**
 * Explicit HTTP port to the Python authority for TS-owned edge modules.
 *
 * This is not the catch-all Python fallback proxy. Control-plane modules use this port
 * when they own a client-facing route but Python remains the authority for the
 * underlying business/read model. Upstream Python status codes, headers, and
 * bodies pass through unchanged; only transport failures are answered by TS with
 * a sanitized error envelope.
 */

import type { FastifyReply, FastifyRequest } from "fastify";
import type { Readable } from "node:stream";
import { request as undiciRequest } from "undici";
import type { ControlPlaneConfig } from "../config";
import { errorEnvelope, sendErrorEnvelope } from "../gateway/errorEnvelope";
import {
  CONTROL_PLANE_MARKER_HEADER,
  CONTROL_PLANE_MARKER_VALUE,
  REQUEST_ID_HEADER,
  resolveRequestId,
} from "../gateway/requestContext";

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

export interface PythonAuthorityResponse {
  statusCode: number;
  headers: Record<string, string | string[] | undefined>;
  body: Readable & {
    text(): Promise<string>;
  };
}

export function buildPythonAuthorityHeaders(
  request: FastifyRequest,
  requestId: string,
): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(request.headers)) {
    if (value === undefined) continue;
    if (HOP_BY_HOP_REQUEST.has(key.toLowerCase())) continue;
    out[key] = value;
  }
  out[CONTROL_PLANE_MARKER_HEADER] = CONTROL_PLANE_MARKER_VALUE;
  out[REQUEST_ID_HEADER] = requestId;
  return out;
}

export function copyPythonAuthorityResponseHeaders(
  headers: Record<string, string | string[] | undefined>,
  reply: FastifyReply,
): void {
  for (const [key, value] of Object.entries(headers)) {
    if (value === undefined) continue;
    if (HOP_BY_HOP_RESPONSE.has(key.toLowerCase())) continue;
    reply.header(key, value);
  }
}

export async function requestPythonAuthority(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  upstreamPath: string,
): Promise<PythonAuthorityResponse> {
  const requestId = resolveRequestId(request);
  return undiciRequest(`${config.pythonApiBaseUrl}${upstreamPath}`, {
    method: "GET",
    headers: buildPythonAuthorityHeaders(request, requestId),
    maxRedirections: 0,
    signal: AbortSignal.timeout(config.requestTimeoutMs),
  });
}

export async function forwardPythonAuthorityResponse(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
  upstreamPath = request.url,
): Promise<FastifyReply> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  try {
    const upstream = await requestPythonAuthority(config, request, upstreamPath);
    reply.code(upstream.statusCode);
    copyPythonAuthorityResponseHeaders(upstream.headers, reply);
    return reply.send(upstream.body);
  } catch (err) {
    request.log.warn(
      { path: upstreamPath, reason: errKind(err) },
      "python authority port failed",
    );
    return sendErrorEnvelope(
      reply,
      502,
      errorEnvelope(
        "python_authority_unavailable",
        "Python authority is unavailable",
        requestId,
      ),
    );
  }
}

export function errKind(err: unknown): string {
  if (err && typeof err === "object") {
    const code = (err as { code?: string }).code;
    const name = (err as { name?: string }).name;
    if (name === "TimeoutError" || name === "AbortError") return "timeout";
    if (typeof code === "string") return code;
  }
  return "upstream_error";
}
