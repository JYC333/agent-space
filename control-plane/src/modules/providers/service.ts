/**
 * Provider read handlers.
 *
 * Providers/credentials are TS-owned. Reads resolve identity through the native
 * auth module, then serve list/detail from the provider DB read port and static
 * catalogs from the protocol package.
 */

import type { FastifyReply, FastifyRequest } from "fastify";
import type { ControlPlaneConfig } from "../../config";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { resolveProvidersDbPort } from "./dbReader";
import { introspectIdentity } from "../auth/identity";
import { loadProtocol } from "./protocolRuntime";

function configIdFromRequest(request: FastifyRequest): string | undefined {
  const params = request.params as Record<string, unknown> | undefined;
  return typeof params?.configId === "string" ? params.configId : undefined;
}

async function resolveIdentityOrReply(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
  requestId: string,
): Promise<{ spaceId: string } | FastifyReply> {
  const identity = await introspectIdentity(config, request);
  if (identity.ok) return { spaceId: identity.spaceId };
  if (identity.reason === "denied") {
    // Pass Python's authentication/authorization answer through unchanged.
    reply.code(identity.statusCode);
    reply.header("content-type", "application/json");
    return reply.send(identity.body);
  }
  return sendErrorEnvelope(
    reply,
    502,
    errorEnvelope(
      identity.reason === "contract_violation"
        ? "introspect_contract_violation"
        : "python_authority_unavailable",
      "Identity introspection failed",
      requestId,
    ),
  );
}

async function serveTsProviderRead(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
  compute: (spaceId: string) => Promise<unknown | null>,
  notFoundDetail?: (configId: string) => string,
): Promise<FastifyReply> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);

  const identityOrReply = await resolveIdentityOrReply(config, request, reply, requestId);
  if (!("spaceId" in identityOrReply)) return identityOrReply;

  let value: unknown | null;
  try {
    value = await compute(identityOrReply.spaceId);
  } catch (err) {
    request.log.error(
      { path: request.url, reason: err instanceof Error ? err.message : "unknown" },
      "providers TS read failed",
    );
    return sendErrorEnvelope(
      reply,
      503,
      errorEnvelope(
        "providers_db_unavailable",
        "Provider database read failed",
        requestId,
      ),
    );
  }

  if (value === null) {
    const configId = configIdFromRequest(request) ?? "";
    reply.code(404);
    return reply.send({ detail: notFoundDetail?.(configId) ?? "Not found" });
  }
  reply.code(200);
  return reply.send(value);
}

function requireDbPort(config: ControlPlaneConfig) {
  const db = resolveProvidersDbPort(config);
  if (!db) {
    // Fixed TS provider authority needs the control-plane DB URL in deployed
    // stacks. Keep tests and minimal local config able to boot, but fail reads
    // loudly if the route is called without a DB port.
    throw new Error("providers TS authority requires CONTROL_PLANE_DATABASE_URL");
  }
  return db;
}

export function listProviderConfigs(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  return serveTsProviderRead(config, request, reply, (spaceId) =>
    requireDbPort(config).listProviders(spaceId),
  );
}

export function getProviderConfig(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  const configId = configIdFromRequest(request) ?? "";
  return serveTsProviderRead(
    config,
    request,
    reply,
    (spaceId) => requireDbPort(config).getProvider(spaceId, configId),
    (id) => `ModelProvider '${id}' not found`,
  );
}

export function getProviderCatalogInfo(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  return serveTsProviderRead(config, request, reply, async () => {
    const { PROVIDER_CATALOG_INFO } = await loadProtocol();
    return PROVIDER_CATALOG_INFO;
  });
}

/**
 * Supported-provider catalog. Once provider/credential authority is TS-owned,
 * this route is served from the control plane instead of Python.
 */
export async function listLitellmProviders(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  return serveTsProviderRead(config, request, reply, async () => [
    "openai",
    "anthropic",
    "openrouter",
    "ollama",
    "custom_openai_compatible",
    "other",
  ]);
}
