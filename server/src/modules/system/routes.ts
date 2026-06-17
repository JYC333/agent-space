/**
 * System module routes (server-owned).
 *
 * - GET /health                          plain liveness (container/LB probe)
 * - GET /api/v1/server/health     namespaced liveness
 * - GET /api/v1/server/features   server-side feature advertisement
 * - GET /api/v1/features                 product-shaped feature list
 *
 * Read-only descriptors of the server itself. As real server-side features ship as server modules, they
 * should be advertised in the features route.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { computeFeatures, featuresBody, healthBody } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/health", async () => healthBody());
  app.get("/api/v1/server/health", async () => healthBody());
  app.get("/api/v1/server/features", async () => featuresBody(context.config));
  app.get("/api/v1/features", async () =>
    computeFeatures(context.config).map((id) => ({
      id,
      name: id,
      always_on: true,
      enabled: true,
    })),
  );
}
