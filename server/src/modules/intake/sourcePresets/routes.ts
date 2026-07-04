import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../../gateway/routeRegistry";
import { dbPool, jsonBody, resolveIdentity, sendRouteError } from "../../routeUtils/common";
import { enforceIntake } from "../enforceIntake";
import { listSourcePresets, SourcePresetService } from "./service";

export function registerSourcePresetRoutes(app: FastifyInstance, context: ModuleContext): void {
  const service = () => new SourcePresetService(dbPool(context.config), context.config);

  app.get("/api/v1/intake/source-presets", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(listSourcePresets());
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/source-presets/arxiv/preview", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.connection_manage", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await service().previewArxiv(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/source-presets/arxiv", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.connection_manage", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await service().createArxiv(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
