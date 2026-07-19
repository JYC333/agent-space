import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { dbPool, jsonBody, resolveIdentity, sendRouteError } from "../routeUtils/common";
import { ResearchEngineService } from "./engine/service";
import { enforceSources } from "../sources/enforceSources";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.post("/api/v1/research/engine/search", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply); if (!identity) return reply;
    try { return reply.send(await new ResearchEngineService(dbPool(context.config), context.config).search(identity, jsonBody(request))); }
    catch (error) { return sendRouteError(reply, error); }
  });
  app.post("/api/v1/research/engine/monitors", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply); if (!identity) return reply;
    try {
      const sourceGate = await enforceSources(context, identity, "source.connection.manage", "source_channel");
      if (sourceGate.blocked) return reply.code(403).send(sourceGate.reply403);
      const bindingGate = await enforceSources(context, identity, "project.source.bind", "project_source");
      if (bindingGate.blocked) return reply.code(403).send(bindingGate.reply403);
      return reply.code(201).send(await new ResearchEngineService(dbPool(context.config), context.config).createSuggestedMonitors(identity, jsonBody(request)));
    } catch (error) { return sendRouteError(reply, error); }
  });
}
