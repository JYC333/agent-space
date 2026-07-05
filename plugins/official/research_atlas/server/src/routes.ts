import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type {
  PluginHostContext,
  Queryable,
  ResolvedIdentity,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  RESEARCH_ATLAS_PLUGIN_ID,
  RESEARCH_ATLAS_PLUGIN_VERSION,
} from "./manifest";
import { JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY } from "./jobs";
import { parseImportFile, type ResearchAtlasImportFormat } from "./domain/importParsers";
import { AtlasRequestError, researchAtlasService } from "./domain/service";
import type { AtlasEntityType } from "./domain/types";
import {
  addProjectPaper,
  listProjectPapers,
  removeProjectPaper,
  updateProjectPaper,
} from "./projectOverlay";
import {
  addGroupMembership,
  createGroup,
  getScholarGraphContext,
  getGroup,
  graphForLibrary,
  graphForPaper,
  listGroups,
  listPaperCitations,
  listPaperReferences,
  listPaperRelated,
  listTopics,
  sendEntityExport,
} from "./graph";
import { getResearchAtlasSyncStatus, runResearchAtlasIntakeSync } from "./sync";

class RequestError extends Error {
  constructor(readonly statusCode: number, message: string) {
    super(message);
  }
}

export function registerResearchAtlasRoutes(
  app: FastifyInstance,
  db: Queryable,
  ctx: PluginHostContext,
): void {
  function atlasRoute(
    handler: (
      request: FastifyRequest,
      reply: FastifyReply,
      identity: ResolvedIdentity,
    ) => Promise<void>,
  ) {
    return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
      try {
        const identity = await ctx.http.pluginGuard(request, reply);
        if (!identity) return;
        await handler(request, reply, identity);
      } catch (err) {
        if (err instanceof RequestError || err instanceof AtlasRequestError) {
          reply.code(err.statusCode).send({ detail: err.message });
          return;
        }
        ctx.http.sendError(reply, err);
      }
    };
  }

  app.get(
    "/api/v1/atlas/status",
    atlasRoute(async (_request, reply, identity) => {
      reply.send({
        ok: true,
        plugin_id: RESEARCH_ATLAS_PLUGIN_ID,
        version: RESEARCH_ATLAS_PLUGIN_VERSION,
        scope: "space",
        space_id: identity.spaceId,
      });
    }),
  );

  app.get(
    "/api/v1/atlas/papers",
    atlasRoute(async (request, reply, identity) => {
      const result = await researchAtlasService.listPapers(
        db,
        identity.spaceId,
        request.query as Record<string, unknown>,
      );
      reply.send(result);
    }),
  );

  app.post(
    "/api/v1/atlas/papers/import",
    atlasRoute(async (request, reply, identity) => {
      const body = ctx.http.parseJsonBody(request);
      const result = await researchAtlasService.importPaper(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        body,
        enqueue: async (paperId, connector) =>
          ctx.jobs.enqueue(
            JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY,
            {
              space_id: identity.spaceId,
              user_id: identity.userId,
              paper_id: paperId,
              connector,
            },
            { spaceId: identity.spaceId, userId: identity.userId },
          ),
      });
      reply.code(result.status === "created" ? 201 : 200).send(result);
    }),
  );

  app.post(
    "/api/v1/atlas/papers/import-file",
    atlasRoute(async (request, reply, identity) => {
      const body = ctx.http.parseJsonBody(request);
      const format = typeof body.format === "string" ? body.format : "";
      if (!["bibtex", "ris", "csl_json"].includes(format)) {
        throw new RequestError(400, "format must be bibtex, ris, or csl_json");
      }
      const papers = parseImportFile(format as ResearchAtlasImportFormat, body.content);
      const imported = [];
      for (const paper of papers.slice(0, 250)) {
        imported.push(await researchAtlasService.importPaperMetadata(db, {
          spaceId: identity.spaceId,
          userId: identity.userId,
          connector: format === "csl_json" ? "zotero" : "manual",
          paper,
          enqueue: async (paperId, connector) =>
            ctx.jobs.enqueue(
              JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY,
              { space_id: identity.spaceId, user_id: identity.userId, paper_id: paperId, connector },
              { spaceId: identity.spaceId, userId: identity.userId },
            ),
        }));
      }
      reply.send({ imported, count: imported.length });
    }),
  );

  app.get(
    "/api/v1/atlas/papers/:paperId",
    atlasRoute(async (request, reply, identity) => {
      const paperId = param(request, "paperId");
      reply.send(await researchAtlasService.getPaperDetail(db, identity.spaceId, paperId));
    }),
  );

  app.patch(
    "/api/v1/atlas/papers/:paperId",
    atlasRoute(async (request, reply, identity) => {
      const paperId = param(request, "paperId");
      const body = ctx.http.parseJsonBody(request);
      reply.send(await researchAtlasService.patchPaper(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        paperId,
        body,
      }));
    }),
  );

  app.post(
    "/api/v1/atlas/papers/:paperId/refresh",
    atlasRoute(async (request, reply, identity) => {
      const paperId = param(request, "paperId");
      const body = ctx.http.parseJsonBody(request);
      const connector = typeof body.connector === "string" ? body.connector : null;
      const job = await ctx.jobs.enqueue(
        JOB_TYPE_RESEARCH_ATLAS_ENRICH_ENTITY,
        {
          space_id: identity.spaceId,
          user_id: identity.userId,
          paper_id: paperId,
          connector,
        },
        { spaceId: identity.spaceId, userId: identity.userId },
      );
      reply.send({ queued: true, job_id: job.jobId });
    }),
  );

  app.get(
    "/api/v1/atlas/scholars/:scholarId",
    atlasRoute(async (request, reply, identity) => {
      const scholarId = param(request, "scholarId");
      const [detail, graph] = await Promise.all([
        researchAtlasService.getScholar(db, identity.spaceId, scholarId),
        getScholarGraphContext(db, identity.spaceId, scholarId),
      ]);
      reply.send({ ...detail, ...graph });
    }),
  );

  app.get(
    "/api/v1/atlas/papers/:paperId/references",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await listPaperReferences(db, identity.spaceId, param(request, "paperId")));
    }),
  );

  app.get(
    "/api/v1/atlas/papers/:paperId/citations",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await listPaperCitations(db, identity.spaceId, param(request, "paperId")));
    }),
  );

  app.get(
    "/api/v1/atlas/papers/:paperId/related",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await listPaperRelated(db, identity.spaceId, param(request, "paperId")));
    }),
  );

  app.get(
    "/api/v1/atlas/search",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await researchAtlasService.search(
        db,
        identity.spaceId,
        request.query as Record<string, unknown>,
      ));
    }),
  );

  app.get(
    "/api/v1/atlas/settings",
    atlasRoute(async (_request, reply, identity) => {
      reply.send(await getResearchAtlasSyncStatus(db, identity.spaceId));
    }),
  );

  app.get(
    "/api/v1/atlas/topics",
    atlasRoute(async (_request, reply, identity) => {
      reply.send(await listTopics(db, identity.spaceId));
    }),
  );

  app.get(
    "/api/v1/atlas/groups",
    atlasRoute(async (_request, reply, identity) => {
      reply.send(await listGroups(db, identity.spaceId));
    }),
  );

  app.get(
    "/api/v1/atlas/groups/:groupId",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await getGroup(db, identity.spaceId, param(request, "groupId")));
    }),
  );

  app.post(
    "/api/v1/atlas/groups",
    atlasRoute(async (request, reply, identity) => {
      const body = ctx.http.parseJsonBody(request);
      const name = typeof body.name === "string" ? body.name.trim() : "";
      if (!name) throw new RequestError(400, "name is required");
      const aliases = Array.isArray(body.aliases)
        ? body.aliases.filter((item): item is string => typeof item === "string" && item.trim() !== "")
        : [];
      reply.code(201).send({ group: await createGroup(db, {
        spaceId: identity.spaceId,
        name,
        aliases,
        piScholarId: typeof body.pi_scholar_id === "string" ? body.pi_scholar_id : null,
        confidence: typeof body.confidence === "number" ? body.confidence : null,
      }) });
    }),
  );

  app.post(
    "/api/v1/atlas/groups/:groupId/members",
    atlasRoute(async (request, reply, identity) => {
      const body = ctx.http.parseJsonBody(request);
      const scholarId = typeof body.scholar_id === "string" ? body.scholar_id.trim() : "";
      if (!scholarId) throw new RequestError(400, "scholar_id is required");
      reply.code(201).send({ membership: await addGroupMembership(db, {
        spaceId: identity.spaceId,
        groupId: param(request, "groupId"),
        scholarId,
        role: typeof body.role === "string" ? body.role : "unknown",
        source: "manual",
        confidence: typeof body.confidence === "number" ? body.confidence : null,
      }) });
    }),
  );

  app.get(
    "/api/v1/atlas/graph",
    atlasRoute(async (request, reply, identity) => {
      const q = request.query as Record<string, unknown>;
      const mode = typeof q.mode === "string" ? q.mode : "";
      if (mode === "global" || mode === "library") {
        reply.send(await graphForLibrary(db, identity.spaceId));
        return;
      }
      const paperId = typeof q.paper_id === "string" ? q.paper_id : "";
      if (!paperId) throw new RequestError(400, "paper_id is required");
      reply.send(await graphForPaper(db, identity.spaceId, paperId));
    }),
  );

  app.get(
    "/api/v1/atlas/export/entities",
    atlasRoute(async (request, reply, identity) => {
      const q = request.query as Record<string, unknown>;
      const type = typeof q.type === "string" ? q.type : "paper";
      const since = typeof q.since === "string" ? q.since : null;
      const cursor = typeof q.cursor === "string" ? q.cursor : null;
      const limit = typeof q.limit === "string" ? Number(q.limit) : undefined;
      const includeMerged = q.active_only === "true" || q.include_merged === "false" ? false : true;
      await sendEntityExport(db, reply, {
        spaceId: identity.spaceId,
        entityType: type,
        since,
        cursor,
        limit,
        includeMerged,
      });
    }),
  );

  app.post(
    "/api/v1/atlas/sync/intake",
    atlasRoute(async (_request, reply, identity) => {
      reply.send(await runResearchAtlasIntakeSync(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
      }));
    }),
  );

  app.post(
    "/api/v1/atlas/entities/:entityType/:entityId/merge",
    atlasRoute(async (request, reply, identity) => {
      const entityType = param(request, "entityType") as AtlasEntityType;
      const entityId = param(request, "entityId");
      const body = ctx.http.parseJsonBody(request);
      if (!["paper", "scholar", "institution", "venue"].includes(entityType)) {
        throw new RequestError(400, "entity type cannot be merged");
      }
      const loserId = typeof body.loser_id === "string" ? body.loser_id.trim() : "";
      if (!loserId) throw new RequestError(400, "loser_id is required");
      reply.send(await researchAtlasService.mergeEntity(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        entityType,
        winnerId: entityId,
        loserId,
        reason: typeof body.reason === "string" ? body.reason : null,
      }));
    }),
  );

  app.get(
    "/api/v1/atlas/projects/:projectId/papers",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await listProjectPapers(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId: param(request, "projectId"),
      }));
    }),
  );

  app.post(
    "/api/v1/atlas/projects/:projectId/papers",
    atlasRoute(async (request, reply, identity) => {
      const body = ctx.http.parseJsonBody(request);
      const paperId = typeof body.paper_id === "string" ? body.paper_id.trim() : "";
      if (!paperId) throw new RequestError(400, "paper_id is required");
      const projectPaper = await addProjectPaper(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId: param(request, "projectId"),
        paperId,
        status: typeof body.status === "string" ? body.status as "candidate" : undefined,
        source: "manual",
      });
      reply.code(201).send({ project_paper: projectPaper });
    }),
  );

  app.patch(
    "/api/v1/atlas/projects/:projectId/papers/:paperId",
    atlasRoute(async (request, reply, identity) => {
      reply.send({
        project_paper: await updateProjectPaper(db, {
          spaceId: identity.spaceId,
          userId: identity.userId,
          projectId: param(request, "projectId"),
          paperId: param(request, "paperId"),
          body: ctx.http.parseJsonBody(request),
        }),
      });
    }),
  );

  app.delete(
    "/api/v1/atlas/projects/:projectId/papers/:paperId",
    atlasRoute(async (request, reply, identity) => {
      reply.send(await removeProjectPaper(db, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        projectId: param(request, "projectId"),
        paperId: param(request, "paperId"),
      }));
    }),
  );
}

function param(request: FastifyRequest, name: string): string {
  const value = (request.params as Record<string, string>)[name];
  if (!value) throw new RequestError(400, `${name} is required`);
  return value;
}
