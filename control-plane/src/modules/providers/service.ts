/**
 * Provider read handlers for both authority modes.
 *
 * - `python` (default): forward to the Python authority and validate 2xx
 *   responses against the shared protocol schemas; optionally run the
 *   read-only shadow compare after serving.
 * - `ts`: resolve identity through the Python introspection port, then serve
 *   list/detail from the DB read port and the catalog from the protocol
 *   constant.
 *
 * All validation uses `@agent-space/protocol` Zod schemas loaded at runtime;
 * there are no hand-rolled schema mirrors.
 */

import type { FastifyReply, FastifyRequest } from "fastify";
import type { ControlPlaneConfig } from "../../config";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import {
  copyPythonAuthorityResponseHeaders,
  errKind,
  requestPythonAuthority,
} from "../../ports/pythonHttp";
import { resolveProvidersDbPort } from "./dbReader";
import { introspectIdentity } from "./identity";
import { loadProtocol, type ProtocolModule } from "./protocolRuntime";
import { runProvidersShadowCompare, type ShadowRoute } from "./shadow";

interface ZodLikeSchema {
  safeParse(value: unknown): { success: boolean };
}

type SchemaPick = (protocol: ProtocolModule) => ZodLikeSchema;

const pickProviderList: SchemaPick = (p) => p.ModelProviderDTOSchema.array();
const pickProviderDetail: SchemaPick = (p) => p.ModelProviderDTOSchema;
const pickCatalogInfo: SchemaPick = (p) => p.ProviderCatalogInfoSchema;
const pickLitellmProviders: SchemaPick = (p) => p.LitellmProvidersResponseSchema;

// ---------------------------------------------------------------------------
// Python-authority path (forward + validate + optional shadow)
// ---------------------------------------------------------------------------

async function forwardValidatedProviderRead(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
  pickSchema: SchemaPick,
  shadowRoute?: ShadowRoute,
): Promise<FastifyReply> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  let upstream;
  try {
    upstream = await requestPythonAuthority(config, request, request.url);
  } catch (err) {
    request.log.warn(
      { path: request.url, reason: errKind(err) },
      "provider read Python authority port failed",
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

  const body = await upstream.body.text();

  if (upstream.statusCode < 200 || upstream.statusCode >= 300) {
    copyPythonAuthorityResponseHeaders(upstream.headers, reply);
    reply.code(upstream.statusCode);
    return reply.send(body);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = undefined;
  }
  const schema = pickSchema(await loadProtocol());
  if (parsed === undefined || !schema.safeParse(parsed).success) {
    request.log.warn(
      { path: request.url },
      "provider read Python authority returned an invalid provider contract",
    );
    return sendErrorEnvelope(
      reply,
      502,
      errorEnvelope(
        "provider_contract_violation",
        "Python provider response violated the provider read contract",
        requestId,
      ),
    );
  }

  copyPythonAuthorityResponseHeaders(upstream.headers, reply);
  reply.code(upstream.statusCode);
  const sent = reply.send(parsed);

  if (shadowRoute && config.providersShadowCompare) {
    const configId = configIdFromRequest(request);
    // Fire-and-forget by design: the compare must never affect the response.
    void runProvidersShadowCompare(config, request, shadowRoute, parsed, configId);
  }
  return sent;
}

function configIdFromRequest(request: FastifyRequest): string | undefined {
  const params = request.params as Record<string, unknown> | undefined;
  return typeof params?.configId === "string" ? params.configId : undefined;
}

// ---------------------------------------------------------------------------
// TS-authority path (introspect identity, read DB / constant)
// ---------------------------------------------------------------------------

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
    // Config semantics make this unreachable (authority=ts requires the URL);
    // guard anyway so a future refactor fails loudly instead of silently.
    throw new Error("providers TS authority requires CONTROL_PLANE_DATABASE_URL");
  }
  return db;
}

// ---------------------------------------------------------------------------
// Route handlers (authority-aware)
// ---------------------------------------------------------------------------

export function listProviderConfigs(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  if (config.providersAuthority === "ts") {
    return serveTsProviderRead(config, request, reply, (spaceId) =>
      requireDbPort(config).listProviders(spaceId),
    );
  }
  return forwardValidatedProviderRead(config, request, reply, pickProviderList, "list");
}

export function getProviderConfig(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  if (config.providersAuthority === "ts") {
    const configId = configIdFromRequest(request) ?? "";
    return serveTsProviderRead(
      config,
      request,
      reply,
      (spaceId) => requireDbPort(config).getProvider(spaceId, configId),
      (id) => `ModelProvider '${id}' not found`,
    );
  }
  return forwardValidatedProviderRead(config, request, reply, pickProviderDetail, "detail");
}

export function getProviderCatalogInfo(
  config: ControlPlaneConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<FastifyReply> {
  if (config.providersAuthority === "ts") {
    return serveTsProviderRead(config, request, reply, async () => {
      const { PROVIDER_CATALOG_INFO } = await loadProtocol();
      return PROVIDER_CATALOG_INFO;
    });
  }
  return forwardValidatedProviderRead(config, request, reply, pickCatalogInfo, "catalog");
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
  if (config.providersCredentialsAuthority === "ts") {
    return serveTsProviderRead(config, request, reply, async () => [
      "openai",
      "anthropic",
      "openrouter",
      "ollama",
      "custom_openai_compatible",
      "other",
    ]);
  }
  return forwardValidatedProviderRead(config, request, reply, pickLitellmProviders);
}
