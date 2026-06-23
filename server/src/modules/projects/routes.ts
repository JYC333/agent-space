import type { FastifyInstance } from "fastify";
import type {
  ProjectPublicSummaryDraftRequest,
  ProjectPublicSummaryUpsertRequest,
  RetrievalBriefRequest,
  RetrievalFeedbackRequest,
  RetrievalSearchRequest,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  HttpError,
  jsonBody,
  optionalString,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import {
  RetrievalFeedbackService,
  RetrievalSearchService,
  persistRetrievalBriefArtifact,
} from "../retrieval";
import { readSpaceRetrievalPrompt } from "../retrieval/prompts";
import { readSpaceRetrievalSettings, resolveRetrievalSearchControls } from "../retrieval/settings";
import { ProviderReranker } from "../retrievalRerank/providerReranker";
import { ProviderQueryRewriter } from "../retrievalQueryRewrite/providerQueryRewriter";
import { ProviderQueryEmbedder } from "../retrievalEmbedding/queryEmbedder";
import { enqueueRetrievalEmbeddingBackfill } from "../retrievalEmbedding/job";
import { ProviderSynthesizer } from "../retrievalSynthesis/providerSynthesizer";
import { resolveProviderCommandStore } from "../providers/providerCommandStore";
import { loadProtocol } from "../providers/protocolRuntime";
import { projectRetrievalRegistry } from "./retrievalAdapter";
import { ProjectPublicSummaryGenerator } from "./publicSummaryGenerator";
import { PgProjectRepository } from "./repository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => PgProjectRepository.fromConfig(context.config);
  const summaryGenerator = () => ProjectPublicSummaryGenerator.fromConfig(context.config);

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

  app.get("/api/v1/projects/public-summaries", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q, 50);
      return reply.send(
        await repository().listPublicSummaries(identity, {
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/public-summaries/search", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = parseRetrievalSearchBody(protocol.RetrievalSearchRequestSchema, jsonBody(request));
      const objectTypes = body.object_types ?? ["project_public_summary"];
      if (objectTypes.some((objectType) => objectType !== "project_public_summary")) {
        throw new HttpError(422, "project public summary search only supports project_public_summary");
      }
      const pool = dbPool(context.config);
      const retrievalSettings = await readSpaceRetrievalSettings(pool, identity.spaceId);
      const controls = resolveRetrievalSearchControls(body, retrievalSettings);
      const store = resolveProviderCommandStore(context.config);
      const queryRewritePrompt = retrievalSettings.queryRewriteEnabled
        ? await readSpaceRetrievalPrompt(pool, identity.spaceId, "query_rewrite")
        : null;
      const egressPolicy = { externalEgressEnabled: retrievalSettings.externalEgressEnabled };
      const search = new RetrievalSearchService(pool, projectRetrievalRegistry, {
        egressPolicy,
        // Vector recall arm (parity with knowledge/memory): provider egress is
        // checked at invocation time, so local providers remain usable when
        // external egress is disabled.
        queryEmbedder: new ProviderQueryEmbedder(
          store,
          null,
          undefined,
          retrievalSettings.embeddingDimensions,
          egressPolicy,
        ),
        feedbackService: new RetrievalFeedbackService(pool, projectRetrievalRegistry),
        // Reranker is off unless this space enables it; degrades to the fused order otherwise.
        reranker: retrievalSettings.rerankEnabled
          ? new ProviderReranker(store, {
              databaseUrl: context.config.databaseUrl,
              surface: "project_public_summary_search",
              egressPolicy,
            })
          : undefined,
        // Query rewriter is off unless this space enables it; degrades to the original query.
        queryRewriter: retrievalSettings.queryRewriteEnabled
          ? new ProviderQueryRewriter(store, {
              databaseUrl: context.config.databaseUrl,
              surface: "project_public_summary_search",
              prompt: queryRewritePrompt,
              egressPolicy,
            })
          : undefined,
      });
      return reply.send(await search.search({
        spaceId: identity.spaceId,
        viewerUserId: identity.userId,
        query: body.query,
        objectTypes: ["project_public_summary"],
        objectKinds: body.object_kinds,
        maxResults: controls.maxResults,
        includeTrace: controls.includeTrace,
        feedbackSurface: "project_public_summary_search",
        mode: controls.mode,
        rewrite: controls.rewrite,
        useCache: controls.useCache,
        adaptiveReturn: controls.adaptiveReturn,
        rankingConfig: controls.rankingConfig,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/retrieval/brief", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = parseRetrievalBriefBody(protocol.RetrievalBriefRequestSchema, jsonBody(request));
      const objectTypes = body.object_types ?? ["project_public_summary"];
      if (objectTypes.some((objectType) => objectType !== "project_public_summary")) {
        throw new HttpError(422, "project retrieval brief only supports project_public_summary");
      }
      const pool = dbPool(context.config);
      const retrievalSettings = await readSpaceRetrievalSettings(pool, identity.spaceId);
      const store = resolveProviderCommandStore(context.config);
      const egressPolicy = { externalEgressEnabled: retrievalSettings.externalEgressEnabled };
      const search = new RetrievalSearchService(pool, projectRetrievalRegistry, {
        egressPolicy,
        queryEmbedder: new ProviderQueryEmbedder(
          store,
          null,
          undefined,
          retrievalSettings.embeddingDimensions,
          egressPolicy,
        ),
        reranker: retrievalSettings.rerankEnabled
          ? new ProviderReranker(store, {
              databaseUrl: context.config.databaseUrl,
              surface: "project_public_summary_brief",
              egressPolicy,
            })
          : undefined,
        synthesizer: new ProviderSynthesizer(store, {
          databaseUrl: context.config.databaseUrl,
          surface: "project_public_summary_brief",
          egressPolicy,
        }),
      });
      const maxResults = body.max_results ?? retrievalSettings.maxResultsDefault;
      const includeTrace = body.include_trace ?? retrievalSettings.includeTrace;
      const mode = body.mode ?? retrievalSettings.defaultSearchMode;
      const adaptiveReturn = body.adaptive_return ?? resolveRetrievalSearchControls(body, retrievalSettings).adaptiveReturn;
      const response = await search.buildBrief({
        spaceId: identity.spaceId,
        viewerUserId: identity.userId,
        query: body.query,
        objectTypes: ["project_public_summary"],
        objectKinds: body.object_kinds,
        maxResults,
        includeTrace,
        mode,
        useCache: retrievalSettings.useQueryCache,
        adaptiveReturn,
        rankingConfig: retrievalSettings.rankingConfig,
      });
      if (!body.persist_artifact) return reply.send(response);
      try {
        const artifactId = await persistRetrievalBriefArtifact(pool, {
          spaceId: identity.spaceId,
          ownerUserId: identity.userId,
          runId: null,
          projectId: null,
          query: body.query,
          objectTypes: ["project_public_summary"],
          objectKinds: body.object_kinds,
          maxResults,
          includeTrace,
          mode,
          surface: "project_public_summary_brief",
          response,
          persistTrace: false,
          egressPolicySnapshot: {
            external_egress_enabled: retrievalSettings.externalEgressEnabled,
          },
          settingsSnapshot: {
            default_search_mode: retrievalSettings.defaultSearchMode,
            rerank_enabled: retrievalSettings.rerankEnabled,
            query_rewrite_enabled: retrievalSettings.queryRewriteEnabled,
            use_query_cache: retrievalSettings.useQueryCache,
            embedding_dimensions: retrievalSettings.embeddingDimensions,
            max_results_default: retrievalSettings.maxResultsDefault,
          },
        });
        return reply.send({ ...response, artifact_id: artifactId });
      } catch (error) {
        request.log.warn(
          { err: error },
          "project retrieval brief artifact persistence failed",
        );
        return reply.send({ ...response, artifact_error: "retrieval_brief_persist_failed" });
      }
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/public-summaries/feedback", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = parseBodyWith<RetrievalFeedbackRequest>(
        protocol.RetrievalFeedbackRequestSchema,
        jsonBody(request),
      );
      if (body.object_type !== "project_public_summary") {
        throw new HttpError(422, "project public summary feedback only supports project_public_summary");
      }
      const recorded = await new RetrievalFeedbackService(
        dbPool(context.config),
        projectRetrievalRegistry,
      ).record({
        spaceId: identity.spaceId,
        viewerUserId: identity.userId,
        surface: "project_public_summary_search",
        query: body.query,
        objectType: "project_public_summary",
        objectId: body.object_id,
        signalType: body.signal_type,
        dwellMs: body.dwell_ms ?? null,
        metadata: body.metadata ?? null,
      });
      if (!recorded) return reply.code(404).send({ detail: "Retrieval result not found" });
      return reply.send({ ok: true });
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

  app.get("/api/v1/projects/:projectId/public-summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const summary = await repository().getPublicSummary(identity, params(request).projectId ?? "");
      if (!summary) return reply.code(404).send({ detail: "Project public summary not found" });
      return reply.send(summary);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.put("/api/v1/projects/:projectId/public-summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = parseBodyWith<ProjectPublicSummaryUpsertRequest>(
        protocol.ProjectPublicSummaryUpsertRequestSchema,
        jsonBody(request),
      );
      const summary = await repository().upsertPublicSummary(
        identity,
        params(request).projectId ?? "",
        body,
      );
      // Best-effort: the upsert recreates the chunk with embedding=NULL, so enqueue
      // a backfill to embed it for the vector arm (matches knowledge/memory).
      await enqueueRetrievalEmbeddingBackfill(context.config, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        trigger: "project_public_summary_upsert",
      }).catch((error) => {
        process.stderr.write(
          `[projects.retrieval] embedding backfill enqueue failed: ${String((error as Error)?.message ?? error)}\n`,
        );
        return null;
      });
      return reply.send(summary);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/:projectId/public-summary/draft", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = parseBodyWith<ProjectPublicSummaryDraftRequest>(
        protocol.ProjectPublicSummaryDraftRequestSchema,
        jsonBody(request),
      );
      return reply.send(
        await summaryGenerator().generateDraft(identity, params(request).projectId ?? "", {
          providerId: optionalString(body.model_provider_id) ?? optionalString(body.provider_id),
          model: optionalString(body.model),
          maxTokens: body.max_tokens ?? null,
          generatedByRunId: optionalString(body.generated_by_run_id),
        }),
      );
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

  // Project membership = the project-level memory access ACL. List is open to
  // any space member; add/remove require the project owner or a space owner/admin.
  app.get("/api/v1/projects/:projectId/members", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listMembers(identity, params(request).projectId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/projects/:projectId/members", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(
        await repository().addMember(identity, params(request).projectId ?? "", jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/projects/:projectId/members/:userId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      await repository().removeMember(
        identity,
        params(request).projectId ?? "",
        params(request).userId ?? "",
      );
      return reply.code(204).send();
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

type ProtocolSchema<T> = {
  safeParse(value: unknown):
    | { success: true; data: T }
    | { success: false; error: { issues: Array<{ path: Array<string | number>; message: string }> } };
};

function parseRetrievalSearchBody(
  schema: ProtocolSchema<RetrievalSearchRequest>,
  value: unknown,
): RetrievalSearchRequest {
  return parseBodyWith(schema, value);
}

function parseRetrievalBriefBody(
  schema: ProtocolSchema<RetrievalBriefRequest>,
  value: unknown,
): RetrievalBriefRequest {
  return parseBodyWith(schema, value);
}

function parseBodyWith<T>(schema: ProtocolSchema<T>, value: unknown): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new HttpError(422, validationMessage(parsed.error.issues));
  return parsed.data;
}

function validationMessage(issues: Array<{ path: Array<string | number>; message: string }>): string {
  const issue = issues[0];
  if (!issue) return "Invalid request body";
  const path = issue.path.length ? `${issue.path.join(".")}: ` : "";
  return `${path}${issue.message}`;
}
