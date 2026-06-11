/**
 * Catalog module routes (TS-owned).
 *
 * - GET /api/v1/control-plane/catalog                  summary (availability + counts)
 * - GET /api/v1/control-plane/catalog/capabilities     capability manifest summaries
 * - GET /api/v1/control-plane/catalog/agent-templates  agent template spec summaries
 *
 * Read-only descriptors of the on-disk `catalog/` definitions. No business
 * command, no proxy to Python; the DB-backed capability registry and Template
 * Library APIs remain Python-owned.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { catalogSummary, listAgentTemplates, listCapabilities } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const catalogRoot = context.config.catalogRoot;
  app.get("/api/v1/control-plane/catalog", async () => catalogSummary(catalogRoot));
  app.get("/api/v1/control-plane/catalog/capabilities", async () =>
    listCapabilities(catalogRoot),
  );
  app.get("/api/v1/control-plane/catalog/agent-templates", async () =>
    listAgentTemplates(catalogRoot),
  );
}
