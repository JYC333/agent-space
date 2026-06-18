import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type * as Protocol from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ServerConfig } from "../../config";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { authRepositoryFromConfig, introspectIdentity } from "../auth/identity";
import {
  NetworkProfileError,
  resolveNetworkProfileRepository,
  type NetworkProfileCreateInput,
  type NetworkProfileUpdateInput,
} from "./repository";

type ProtocolModule = typeof Protocol;

let protocolModule: Promise<ProtocolModule> | null = null;

function loadProtocol(): Promise<ProtocolModule> {
  protocolModule ??= import("@agent-space/protocol");
  return protocolModule;
}

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function bodyText(request: FastifyRequest): string {
  return request.body instanceof Buffer ? request.body.toString("utf8") : "";
}

function jsonBody(request: FastifyRequest): unknown {
  const text = bodyText(request);
  return text ? JSON.parse(text) : {};
}

async function parseWith<T>(schemaName: string, value: unknown): Promise<T> {
  const protocol = await loadProtocol();
  const schema = (protocol as unknown as Record<string, { parse(v: unknown): T }>)[schemaName];
  return schema.parse(value);
}

async function resolveIdentity(
  config: ServerConfig,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<{ spaceId: string; userId: string } | null> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  const identity = await introspectIdentity(config, request);
  if (identity.ok) return { spaceId: identity.spaceId, userId: identity.userId };
  if (identity.reason === "denied") {
    reply.code(identity.statusCode);
    reply.header("content-type", "application/json");
    reply.send(identity.body);
    return null;
  }
  await sendErrorEnvelope(
    reply,
    502,
    errorEnvelope(
      identity.reason === "contract_violation"
        ? "introspect_contract_violation"
        : "identity_unavailable",
      "Identity introspection failed",
      requestId,
    ),
  );
  return null;
}

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  const statusCode = error instanceof NetworkProfileError ? error.statusCode : 400;
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(statusCode).send({ detail: message });
}

async function requireSpaceAdmin(
  config: ServerConfig,
  identity: { spaceId: string; userId: string },
  reply: FastifyReply,
): Promise<boolean> {
  const repository = authRepositoryFromConfig(config);
  if (!repository) {
    sendErrorEnvelope(
      reply,
      502,
      errorEnvelope("identity_unavailable", "Identity introspection failed"),
    );
    return false;
  }
  const space = await repository.getSpaceForUser(identity.userId, identity.spaceId);
  if (!space) {
    reply.code(404).send({ detail: "Space not found" });
    return false;
  }
  if ("statusCode" in space) {
    reply.code(space.statusCode).send({ detail: space.detail });
    return false;
  }
  if (space.role !== "owner" && space.role !== "admin") {
    reply.code(403).send({ detail: "Requires space owner or admin role" });
    return false;
  }
  return true;
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/api/v1/network-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceAdmin(context.config, identity, reply))) return reply;
    try {
      return reply.send(await resolveNetworkProfileRepository(context.config).list(identity.spaceId));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/network-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceAdmin(context.config, identity, reply))) return reply;
    try {
      const body = await parseWith<NetworkProfileCreateInput>(
        "NetworkProfileCreateRequestSchema",
        jsonBody(request),
      );
      const value = await resolveNetworkProfileRepository(context.config).create(
        identity.spaceId,
        body,
      );
      return reply.code(201).send(value);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/network-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceAdmin(context.config, identity, reply))) return reply;
    try {
      const value = await resolveNetworkProfileRepository(context.config).get(
        identity.spaceId,
        params(request).profileId ?? "",
      );
      if (!value) return reply.code(404).send({ detail: "Network profile not found" });
      return reply.send(value);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.patch("/api/v1/network-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceAdmin(context.config, identity, reply))) return reply;
    try {
      const body = await parseWith<NetworkProfileUpdateInput>(
        "NetworkProfileUpdateRequestSchema",
        jsonBody(request),
      );
      return reply.send(
        await resolveNetworkProfileRepository(context.config).update(
          identity.spaceId,
          params(request).profileId ?? "",
          body,
        ),
      );
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.delete("/api/v1/network-profiles/:profileId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceAdmin(context.config, identity, reply))) return reply;
    try {
      await resolveNetworkProfileRepository(context.config).delete(
        identity.spaceId,
        params(request).profileId ?? "",
      );
      return reply.code(204).send();
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });
}
