/**
 * Catalog module routes (server-owned).
 *
 * - GET /api/v1/server/catalog                  summary (availability + counts)
 * - GET /api/v1/server/catalog/capabilities     capability manifest summaries
 * - GET /api/v1/server/catalog/agent-templates  agent template spec summaries
 * - GET /api/v1/capabilities                          public capability manifest view
 *
 * Read-only descriptors of the on-disk `catalog/` definitions. The public
 * capability routes expose the same catalog data in the legacy product shape.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { resolveIdentity, sendRouteError } from "../routeUtils/common";
import { catalogSummary, listAgentTemplates, listCapabilities } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const catalogRoot = context.config.catalogRoot;
  app.get("/api/v1/server/catalog", async () => catalogSummary(catalogRoot));
  app.get("/api/v1/server/catalog/capabilities", async () =>
    listCapabilities(catalogRoot),
  );
  app.get("/api/v1/server/catalog/agent-templates", async () =>
    listAgentTemplates(catalogRoot),
  );

  app.get("/api/v1/capabilities", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const listed = await listCapabilities(catalogRoot);
      return reply.send(listed.items.map(capabilityToPublicOut));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/capabilities/reload", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const listed = await listCapabilities(catalogRoot);
      const failed = listed.items.filter((item) => item.parse_error).length;
      return reply.send({
        loaded: listed.items.length - failed,
        failed,
        details: listed.items.map((item) => ({
          id: item.id,
          status: item.parse_error ? "failed" : "loaded",
        })),
      });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/capabilities/:capabilityId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const capabilityId = (request.params as { capabilityId?: string }).capabilityId ?? "";
      const listed = await listCapabilities(catalogRoot);
      const found = listed.items.find((item) => item.id === capabilityId);
      if (!found) return reply.code(404).send({ detail: "Capability not found" });
      return reply.send(capabilityToPublicOut(found));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

function capabilityToPublicOut(item: Awaited<ReturnType<typeof listCapabilities>>["items"][number]): Record<string, unknown> {
  const now = new Date(0).toISOString();
  return {
    id: item.id,
    name: item.name ?? item.id,
    version: item.version ?? "0.0.0",
    description: item.description,
    enabled: item.enabled ?? false,
    manifest_json: {
      id: item.id,
      name: item.name,
      version: item.version,
      description: item.description,
      enabled: item.enabled,
      parse_error: item.parse_error ?? false,
    },
    created_at: now,
    updated_at: now,
  };
}
