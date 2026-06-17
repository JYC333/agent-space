import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  jsonBody,
  optionalString,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { PgProjectRepository } from "./repository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => PgProjectRepository.fromConfig(context.config);

  app.get("/api/v1/projects", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q, 50);
      const status = optionalString(q.status);
      if (status && !["active", "archived"].includes(status)) {
        return reply.code(422).send({ detail: "status must be active or archived" });
      }
      return reply.send(await repository().list(identity, { status, limit, offset }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().create(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/projects/:projectId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const project = await repository().get(identity, params(request).projectId ?? "");
      if (!project) return reply.code(404).send({ detail: "Project not found" });
      return reply.send(project);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/projects/:projectId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository().update(identity, params(request).projectId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/:projectId/archive", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().archive(identity, params(request).projectId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/projects/:projectId/summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().summary(identity, params(request).projectId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/projects/:projectId/workspaces", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listWorkspaces(identity, params(request).projectId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/:projectId/workspaces", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(
        await repository().linkWorkspace(identity, params(request).projectId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/projects/:projectId/workspaces/:workspaceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().unlinkWorkspace(
        identity,
        params(request).projectId ?? "",
        params(request).workspaceId ?? "",
        optionalString(query(request).role),
      );
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
