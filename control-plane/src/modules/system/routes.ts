/**
 * System module routes (TS-owned).
 *
 * - GET /health                          plain liveness (container/LB probe)
 * - GET /api/v1/control-plane/health     namespaced liveness
 * - GET /api/v1/control-plane/features   TS-side feature advertisement
 *
 * Read-only descriptors of the control plane itself — no business command, no
 * proxy to Python. As real TS-side features ship as control-plane modules, they
 * should be advertised in the features route.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { featuresBody, healthBody } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/health", async () => healthBody());
  app.get("/api/v1/control-plane/health", async () => healthBody());
  app.get("/api/v1/control-plane/features", async () => featuresBody(context.config));
}
