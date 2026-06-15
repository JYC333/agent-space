/**
 * Identity introspection caller.
 *
 * Python remains the sole authentication/membership authority: this port
 * forwards the original caller's Authorization header / session cookie plus
 * the `space_id` query to `GET /api/v1/auth/introspect` and never validates
 * credentials itself. Responses are validated against the shared
 * `IdentityIntrospectionResponseSchema`.
 */

import type { FastifyRequest } from "fastify";
import type { ControlPlaneConfig } from "../../config";
import { errKind, requestPythonAuthority } from "../../ports/pythonHttp";
import { loadProtocol } from "./protocolRuntime";

export type IntrospectionResult =
  | { ok: true; spaceId: string; userId: string }
  | {
      ok: false;
      /** `denied`: Python answered non-2xx (pass its answer through). */
      reason: "denied" | "unavailable" | "contract_violation";
      statusCode: number;
      body: string;
    };

export async function introspectIdentity(
  config: ControlPlaneConfig,
  request: FastifyRequest,
): Promise<IntrospectionResult> {
  const query = request.query as Record<string, unknown> | undefined;
  const spaceId = typeof query?.space_id === "string" ? query.space_id : undefined;
  const path = spaceId
    ? `/api/v1/auth/introspect?space_id=${encodeURIComponent(spaceId)}`
    : "/api/v1/auth/introspect";

  let upstream;
  try {
    upstream = await requestPythonAuthority(config, request, path);
  } catch (err) {
    request.log.warn(
      { reason: errKind(err) },
      "identity introspection port unavailable",
    );
    return { ok: false, reason: "unavailable", statusCode: 502, body: "" };
  }

  const body = await upstream.body.text();
  if (upstream.statusCode < 200 || upstream.statusCode >= 300) {
    return { ok: false, reason: "denied", statusCode: upstream.statusCode, body };
  }

  const { IdentityIntrospectionResponseSchema } = await loadProtocol();
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = undefined;
  }
  const result = IdentityIntrospectionResponseSchema.safeParse(parsed);
  if (!result.success) {
    request.log.warn("identity introspection response violated the contract");
    return { ok: false, reason: "contract_violation", statusCode: 502, body: "" };
  }
  return { ok: true, spaceId: result.data.space_id, userId: result.data.user_id };
}
