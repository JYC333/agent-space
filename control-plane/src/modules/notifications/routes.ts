/**
 * Notification/webhook egress routes.
 *
 * - GET  /api/v1/control-plane/notifications/webhooks/policy
 * - POST /api/v1/control-plane/notifications/webhooks/dispatch
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { dispatchWebhookRoute, notificationWebhookPolicy } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/api/v1/control-plane/notifications/webhooks/policy", async () =>
    notificationWebhookPolicy(context.config),
  );
  app.post(
    "/api/v1/control-plane/notifications/webhooks/dispatch",
    async (request, reply) => dispatchWebhookRoute(context.config, request, reply),
  );
}
