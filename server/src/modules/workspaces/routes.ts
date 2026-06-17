import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { RuntimeToolRegistry } from "../runtimeTools";
import {
  HttpError,
  jsonBody,
  params,
  parsePage,
  query,
  resolveIdentity,
  sendRouteError,
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { PgWorkspaceRepository } from "./repository";

interface WorkspaceServices {
  repository: Pick<
    PgWorkspaceRepository,
    | "list"
    | "create"
    | "scan"
    | "get"
    | "update"
    | "archive"
    | "listConsoleWorkspaces"
    | "getTree"
    | "getFile"
    | "getGitStatus"
    | "getGitDiff"
  >;
  runtimes: Pick<RuntimeToolRegistry, "listStatus">;
}

type WorkspaceServicesFactory = (context: ModuleContext) => WorkspaceServices;
type WorkspaceIdentityOverride =
  | SpaceUserIdentity
  | ((request: FastifyRequest) => Promise<SpaceUserIdentity | null> | SpaceUserIdentity | null);

let servicesFactoryOverride: WorkspaceServicesFactory | null = null;
let identityOverride: WorkspaceIdentityOverride | null = null;

export function __setWorkspaceServicesFactoryForTests(
  factory: WorkspaceServicesFactory | null,
): void {
  servicesFactoryOverride = factory;
}

export function __setWorkspaceIdentityForTests(identity: WorkspaceIdentityOverride | null): void {
  identityOverride = identity;
}

function services(context: ModuleContext): WorkspaceServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  return {
    repository: PgWorkspaceRepository.fromConfig(context.config),
    runtimes: new RuntimeToolRegistry(context.config),
  };
}

async function identity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<SpaceUserIdentity | null> {
  if (identityOverride) {
    return typeof identityOverride === "function" ? identityOverride(request) : identityOverride;
  }
  return resolveIdentity(context.config, request, reply);
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.get("/api/v1/workspaces", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const q = query(request);
      const page = parsePage(q);
      return reply.send(await services(context).repository.list(id, {
        status: q.status ?? null,
        limit: page.limit,
        offset: page.offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/workspaces", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const workspace = await services(context).repository.create(id, jsonBody(request));
      return reply.code(201).send(workspace);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/workspaces/scan", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send(await services(context).repository.scan(id));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspaces/:workspaceId", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const workspace = await services(context).repository.get(id, params(request).workspaceId ?? "");
      if (!workspace) return reply.code(404).send({ detail: "Workspace not found" });
      return reply.send(workspace);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/workspaces/:workspaceId", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const workspace = await services(context).repository.update(
        id,
        params(request).workspaceId ?? "",
        jsonBody(request),
      );
      if (!workspace) return reply.code(404).send({ detail: "Workspace not found" });
      return reply.send(workspace);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/workspaces/:workspaceId", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const archived = await services(context).repository.archive(id, params(request).workspaceId ?? "");
      if (!archived) return reply.code(404).send({ detail: "Workspace not found" });
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/workspaces", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send(await services(context).repository.listConsoleWorkspaces(id));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/workspaces/:workspaceId/tree", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send(await services(context).repository.getTree(id, params(request).workspaceId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/workspaces/:workspaceId/file", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      const requestedPath = query(request).path;
      if (!requestedPath) throw new HttpError(422, "path is required");
      return reply.send(await services(context).repository.getFile(
        id,
        params(request).workspaceId ?? "",
        requestedPath,
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/workspaces/:workspaceId/git/status", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send(await services(context).repository.getGitStatus(id, params(request).workspaceId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/workspaces/:workspaceId/git/diff", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send(await services(context).repository.getGitDiff(
        id,
        params(request).workspaceId ?? "",
        query(request).path ?? null,
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/runtimes", async (request, reply) => {
    try {
      const id = await identity(context, request, reply);
      if (!id) return reply;
      return reply.send({ runtimes: await services(context).runtimes.listStatus() });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/workspace-console/sessions", async (request, reply) => {
    const id = await identity(context, request, reply);
    if (!id) return reply;
    return reply.send({ items: [] });
  });
  app.post("/api/v1/workspace-console/sessions", notImplemented(context));
  app.get("/api/v1/workspace-console/sessions/:sessionId", notImplemented(context));
  app.post("/api/v1/workspace-console/sessions/:sessionId/run", notImplemented(context));
  app.post("/api/v1/workspace-console/sessions/:sessionId/stop", notImplemented(context));
}

function notImplemented(context: ModuleContext) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<FastifyReply> => {
    const id = await identity(context, request, reply);
    if (!id) return reply;
    return reply.code(501).send({ detail: "workspace_console_sessions is not implemented" });
  };
}
