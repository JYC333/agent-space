import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../auth/identity";
import { RuntimeToolError, RuntimeToolRegistry } from "./service";

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function bodyText(request: FastifyRequest): string {
  return request.body instanceof Buffer ? request.body.toString("utf8") : "";
}

function jsonBody(request: FastifyRequest): Record<string, unknown> {
  const text = bodyText(request);
  const parsed = text ? JSON.parse(text) : {};
  return parsed && typeof parsed === "object" && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : {};
}

async function resolveIdentity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<boolean> {
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  const identity = await introspectIdentity(context.config, request);
  if (identity.ok) return true;
  if (identity.reason === "denied") {
    reply.code(identity.statusCode);
    reply.header("content-type", "application/json");
    reply.send(identity.body);
    return false;
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
  return false;
}

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  if (error instanceof RuntimeToolError) {
    return reply.code(error.statusCode).send({ detail: error.message, error_code: error.code });
  }
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(400).send({ detail: message });
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const registry = new RuntimeToolRegistry(context.config);

  app.get("/api/v1/runtime-tools/catalog", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    return reply.send(registry.listDefinitions());
  });

  app.get("/api/v1/runtime-tools", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    return reply.send(await registry.listStatus());
  });

  app.get("/api/v1/runtime-tools/:runtime", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    try {
      return reply.send(await registry.status(params(request).runtime ?? ""));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/runtime-tools/:runtime/latest", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    try {
      return reply.send(await registry.latestVersion(params(request).runtime ?? ""));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/runtime-tools/:runtime/install", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    try {
      const body = jsonBody(request);
      const result = await registry.install(params(request).runtime ?? "", {
        version: typeof body.version === "string" ? body.version : null,
        activate: typeof body.activate === "boolean" ? body.activate : true,
        force: body.force === true,
      });
      return reply.code(201).send(result);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/runtime-tools/:runtime/activate", async (request, reply) => {
    if (!(await resolveIdentity(context, request, reply))) return reply;
    try {
      const body = jsonBody(request);
      if (typeof body.version !== "string" || body.version.trim() === "") {
        return reply.code(400).send({ detail: "version is required", error_code: "version_required" });
      }
      return reply.send(await registry.activate(params(request).runtime ?? "", body.version));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });
}
