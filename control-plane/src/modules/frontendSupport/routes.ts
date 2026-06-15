/**
 * Frontend-support read model routes (TS edge, Python authority).
 *
 * These are aggregation/read surfaces used by the frontend. The control plane
 * owns the route edge so the Python fallback surface shrinks, but it does not inspect
 * or reinterpret the read-model payloads.
 */

import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { forwardReadModel } from "./service";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const forward = forwardReadModel(context.config);

  app.get("/api/v1/home/summary", forward);

  app.get("/api/v1/me/summary", forward);
  app.get("/api/v1/me/timeline", forward);
  app.get("/api/v1/me/tasks", forward);
  app.get("/api/v1/me/pending", forward);

  app.get("/api/v1/workspace-console/workspaces", forward);
  app.get("/api/v1/workspace-console/workspaces/:workspaceId/tree", forward);
  app.get("/api/v1/workspace-console/workspaces/:workspaceId/file", forward);
  app.get("/api/v1/workspace-console/workspaces/:workspaceId/git/status", forward);
  app.get("/api/v1/workspace-console/workspaces/:workspaceId/git/diff", forward);
  app.get("/api/v1/workspace-console/runtimes", forward);
  app.get("/api/v1/workspace-console/sessions", forward);
  app.get("/api/v1/workspace-console/sessions/:sessionId", forward);
}
