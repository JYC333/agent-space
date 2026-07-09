import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { HttpError, params, resolveIdentity, sendRouteError } from "../routeUtils/common";
import { ProjectPresetsService } from "./service";

let serviceFactoryOverride: ((context: ModuleContext) => ProjectPresetsService) | null = null;

export function __setProjectPresetsServiceFactoryForTests(
  factory: ((context: ModuleContext) => ProjectPresetsService) | null,
): void {
  serviceFactoryOverride = factory;
}

function service(context: ModuleContext): ProjectPresetsService {
  if (serviceFactoryOverride) return serviceFactoryOverride(context);
  return ProjectPresetsService.fromConfig(context.config);
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/api/v1/project-presets", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(service(context).listAvailablePresets());
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/projects/:projectId/preset", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const projectId = params(request).projectId;
      if (!projectId) throw new HttpError(422, "projectId is required");
      return reply.send({ preset_key: await service(context).getProjectPreset(identity, projectId) });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
