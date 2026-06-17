import type { FastifyInstance, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import {
  authRepositoryFromConfig,
  sessionTokenFromRequest,
  type AuthFailure,
} from "../auth/identity";
import {
  spaceRepositoryFromConfig,
  type SpaceCreateInput,
  type InvitationCreateInput,
  type SpaceFailure,
} from "./repository";

function isFailure(value: unknown): value is AuthFailure {
  return Boolean(value && typeof value === "object" && "statusCode" in value);
}

function isSpaceFailure(value: unknown): value is SpaceFailure {
  return Boolean(value && typeof value === "object" && "statusCode" in value);
}

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function body<T extends object>(request: FastifyRequest): Partial<T> {
  if (!(request.body instanceof Buffer) || request.body.length === 0) return {};
  try {
    const parsed = JSON.parse(request.body.toString("utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Partial<T>)
      : {};
  } catch {
    return {};
  }
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.post("/api/v1/spaces", async (request, reply) => {
    const requestId = resolveRequestId(request);
    reply.header(REQUEST_ID_HEADER, requestId);
    const auth = authRepositoryFromConfig(context.config);
    const spaces = spaceRepositoryFromConfig(context.config);
    if (!auth || !spaces) {
      return sendErrorEnvelope(
        reply,
        502,
        errorEnvelope("identity_db_unavailable", "Identity database is unavailable", requestId),
      );
    }
    const user = await auth.getCurrentUser(sessionTokenFromRequest(request));
    if (isFailure(user)) return reply.code(user.statusCode).send({ detail: user.detail });
    const payload = body<SpaceCreateInput>(request);
    const result = await spaces.createSpace(user.id, {
      name: typeof payload.name === "string" ? payload.name : "",
      type: payload.type,
    });
    if (isSpaceFailure(result)) return reply.code(result.statusCode).send({ detail: result.detail });
    return reply.code(201).send(result);
  });

  app.get("/api/v1/spaces/:spaceId/members", async (request, reply) => {
    const requestId = resolveRequestId(request);
    reply.header(REQUEST_ID_HEADER, requestId);
    const auth = authRepositoryFromConfig(context.config);
    const spaces = spaceRepositoryFromConfig(context.config);
    if (!auth || !spaces) {
      return sendErrorEnvelope(
        reply,
        502,
        errorEnvelope("identity_db_unavailable", "Identity database is unavailable", requestId),
      );
    }
    const user = await auth.getCurrentUser(sessionTokenFromRequest(request));
    if (isFailure(user)) return reply.code(user.statusCode).send({ detail: user.detail });
    const result = await spaces.listMembers(user.id, params(request).spaceId ?? "");
    if (isSpaceFailure(result)) return reply.code(result.statusCode).send({ detail: result.detail });
    return reply.send(result);
  });

  app.post("/api/v1/spaces/:spaceId/invitations", async (request, reply) => {
    const requestId = resolveRequestId(request);
    reply.header(REQUEST_ID_HEADER, requestId);
    const auth = authRepositoryFromConfig(context.config);
    const spaces = spaceRepositoryFromConfig(context.config);
    if (!auth || !spaces) {
      return sendErrorEnvelope(
        reply,
        502,
        errorEnvelope("identity_db_unavailable", "Identity database is unavailable", requestId),
      );
    }
    const user = await auth.getCurrentUser(sessionTokenFromRequest(request));
    if (isFailure(user)) return reply.code(user.statusCode).send({ detail: user.detail });
    const payload = body<InvitationCreateInput>(request);
    const result = await spaces.createInvitation(user.id, params(request).spaceId ?? "", {
      email: typeof payload.email === "string" ? payload.email : "",
      role: payload.role,
    });
    if (isSpaceFailure(result)) return reply.code(result.statusCode).send({ detail: result.detail });
    return reply.code(201).send(result);
  });

  app.post("/api/v1/invitations/:token/accept", async (request, reply) => {
    const requestId = resolveRequestId(request);
    reply.header(REQUEST_ID_HEADER, requestId);
    const auth = authRepositoryFromConfig(context.config);
    const spaces = spaceRepositoryFromConfig(context.config);
    if (!auth || !spaces) {
      return sendErrorEnvelope(
        reply,
        502,
        errorEnvelope("identity_db_unavailable", "Identity database is unavailable", requestId),
      );
    }
    const user = await auth.getCurrentUser(sessionTokenFromRequest(request));
    if (isFailure(user)) return reply.code(user.statusCode).send({ detail: user.detail });
    const result = await spaces.acceptInvitation({
      token: params(request).token ?? "",
      userId: user.id,
      userEmail: user.email,
    });
    if (isSpaceFailure(result)) return reply.code(result.statusCode).send({ detail: result.detail });
    return reply.send(result);
  });

  app.get("/api/v1/spaces/:spaceId", async (request, reply) => {
    const requestId = resolveRequestId(request);
    reply.header(REQUEST_ID_HEADER, requestId);
    const repository = authRepositoryFromConfig(context.config);
    if (!repository) {
      return sendErrorEnvelope(
        reply,
        502,
        errorEnvelope(
          "identity_db_unavailable",
          "Identity database is unavailable",
          requestId,
        ),
      );
    }
    const user = await repository.getCurrentUser(sessionTokenFromRequest(request));
    if (isFailure(user)) return reply.code(user.statusCode).send({ detail: user.detail });
    const space = await repository.getSpaceForUser(user.id, params(request).spaceId ?? "");
    if (space === null) return reply.code(404).send({ detail: "Space not found" });
    if (isFailure(space)) return reply.code(space.statusCode).send({ detail: space.detail });
    return reply.send(space);
  });
}
