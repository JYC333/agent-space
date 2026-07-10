import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  HttpError,
  jsonBody,
  optionalString,
  params,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import {
  isContentAccessLevel,
  isContentVisibility,
  type ContentAccessLevel,
} from "../access/contentAccessTypes";
import { ContentAccessService, type ContentAccessUpdate } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const service = () => ContentAccessService.fromConfig(context.config);

  app.get("/api/v1/content-access/:resourceType/:resourceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const route = params(request);
      return reply.send(await service().getPolicy(
        identity,
        requiredParam(route.resourceType, "resourceType"),
        requiredParam(route.resourceId, "resourceId"),
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.put("/api/v1/content-access/:resourceType/:resourceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const route = params(request);
      return reply.send(await service().updatePolicy(
        identity,
        requiredParam(route.resourceType, "resourceType"),
        requiredParam(route.resourceId, "resourceId"),
        updateInput(jsonBody(request)),
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

function updateInput(body: Record<string, unknown>): ContentAccessUpdate {
  const visibility = optionalString(body.visibility);
  const accessLevel = optionalString(body.access_level);
  if (!isContentVisibility(visibility)) throw new HttpError(422, "Invalid visibility");
  if (!isContentAccessLevel(accessLevel)) throw new HttpError(422, "Invalid access_level");
  if (!Array.isArray(body.grants)) throw new HttpError(422, "grants must be an array");
  const grants = body.grants.map((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new HttpError(422, "Invalid content grant");
    }
    const item = value as Record<string, unknown>;
    const userId = optionalString(item.user_id);
    const grantLevel = optionalString(item.access_level) ?? "full";
    if (!userId || !isContentAccessLevel(grantLevel)) throw new HttpError(422, "Invalid content grant");
    return { user_id: userId, access_level: grantLevel as ContentAccessLevel };
  });
  return { visibility, access_level: accessLevel, grants };
}

function requiredParam(value: string | undefined, name: string): string {
  if (!value) throw new HttpError(422, `${name} is required`);
  return value;
}
