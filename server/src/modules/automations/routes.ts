import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  jsonBody,
  optionalString,
  params,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { AutomationService, automationToOut } from "./service";
import { PgAutomationRepository } from "./repository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const service = () =>
    new AutomationService(context.config, new PgAutomationRepository(dbPool(context.config)));

  app.get("/api/v1/spaces/:spaceId/automations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    const spaceId = params(request).spaceId ?? identity.spaceId;
    if (spaceId !== identity.spaceId) return reply.code(403).send({ detail: "Access denied" });
    try {
      const rows = await new PgAutomationRepository(dbPool(context.config)).list(spaceId);
      return reply.send(rows.map(automationToOut));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/spaces/:spaceId/automations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    const spaceId = params(request).spaceId ?? identity.spaceId;
    if (spaceId !== identity.spaceId) return reply.code(403).send({ detail: "Access denied" });
    try {
      const row = await service().create({
        spaceId,
        ownerUserId: identity.userId,
        body: jsonBody(request),
      });
      return reply.code(201).send(automationToOut(row));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/spaces/:spaceId/automations/:automationId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    const spaceId = params(request).spaceId ?? identity.spaceId;
    if (spaceId !== identity.spaceId) return reply.code(403).send({ detail: "Access denied" });
    try {
      const row = await new PgAutomationRepository(dbPool(context.config)).get(
        spaceId,
        params(request).automationId ?? "",
      );
      if (!row) return reply.code(404).send({ detail: "Automation not found" });
      return reply.send(automationToOut(row));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/spaces/:spaceId/automations/:automationId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    const spaceId = params(request).spaceId ?? identity.spaceId;
    if (spaceId !== identity.spaceId) return reply.code(403).send({ detail: "Access denied" });
    try {
      const row = await service().update({
        spaceId,
        automationId: params(request).automationId ?? "",
        actorUserId: identity.userId,
        body: jsonBody(request),
      });
      return reply.send(automationToOut(row));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/spaces/:spaceId/automations/:automationId/fire", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    const spaceId = params(request).spaceId ?? identity.spaceId;
    if (spaceId !== identity.spaceId) return reply.code(403).send({ detail: "Access denied" });
    try {
      const body = jsonBody(request);
      const result = await service().fire({
        spaceId,
        automationId: params(request).automationId ?? "",
        actorUserId: identity.userId,
        prompt: optionalString(body.prompt),
        instruction: optionalString(body.instruction),
        triggerType: optionalString(body.trigger_type) ?? "manual",
      });
      return reply.send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
