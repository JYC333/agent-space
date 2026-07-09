import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  HttpError,
  jsonBody,
  optionalString,
  parsePage,
  params,
  query,
  requiredString,
  resolveIdentity,
  sendRouteError,
  toDbDate,
} from "../routeUtils/common";
import { requireSpaceOwnerOrAdmin } from "../routeUtils/access";
import { enforceSources } from "./enforceSources";
import { PgSourcesRepository } from "./repository";
import { SourcePostProcessingService } from "./postProcessing/service";
import { registerCustomSourceRoutes } from "./customSources/customSourceRoutes";
import { registerSourceRecipeRoutes } from "./sourceRecipeRoutes";
import { registerSourcePresetRoutes } from "./sourcePresets/routes";
import { listSourceRuns } from "./sourceRunReadModel";
import { PgAnnotationRepository, PgCommentRepository, PgReaderActionRepository, PgReaderRepository } from "./readerRepository";
import {
  RetrievalProjectionService,
  RetrievalSearchService,
  persistRetrievalBriefArtifact,
  type RetrievalObjectType,
} from "../retrieval";
import { readSpaceRetrievalSettings, resolveRetrievalSearchControls } from "../retrieval/settings";
import { ProviderQueryEmbedder } from "../retrieval/embedding/queryEmbedder";
import { ProviderQueryRewriter } from "../retrieval/queryRewriteProvider/providerQueryRewriter";
import { ProviderReranker } from "../retrieval/rerankProvider/providerReranker";
import { ProviderSynthesizer } from "../retrieval/synthesisProvider/providerSynthesizer";
import { resolveProviderCommandStore } from "../providers/commands/store";
import { enqueueRetrievalEmbeddingBackfill } from "../retrieval/embedding/job";
import { loadProtocol } from "../providers/protocolRuntime";
import { sourceRetrievalRegistry } from "./retrievalAdapter";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new PgSourcesRepository(dbPool(context.config), context.config);
  const postProcessing = () => new SourcePostProcessingService(dbPool(context.config), context.config);
  registerCustomSourceRoutes(app, context);
  registerSourceRecipeRoutes(app, context);
  registerSourcePresetRoutes(app, context);

  app.get("/api/v1/sources", sourcesHealth(context));
  app.get("/api/v1/sources/", sourcesHealth(context));

  app.post("/api/v1/sources/retrieval/search", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const parsed = protocol.RetrievalSearchRequestSchema.safeParse(jsonBody(request));
      if (!parsed.success) throw new HttpError(422, validationMessage(parsed.error.issues));
      const body = parsed.data;
      const objectTypes = sourceObjectTypes(body.object_types);
      const pool = dbPool(context.config);
      const retrievalSettings = await readSpaceRetrievalSettings(pool, identity.spaceId);
      const controls = resolveRetrievalSearchControls(body, retrievalSettings);
      const store = resolveProviderCommandStore(context.config);
      const egressPolicy = { externalEgressEnabled: retrievalSettings.externalEgressEnabled };
      const search = new RetrievalSearchService(pool, sourceRetrievalRegistry, {
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
              surface: "source_search",
              egressPolicy,
            })
          : undefined,
        queryRewriter: retrievalSettings.queryRewriteEnabled
          ? new ProviderQueryRewriter(store, {
              databaseUrl: context.config.databaseUrl,
              surface: "source_search",
              egressPolicy,
            })
          : undefined,
      });
      return reply.send(await search.search({
        spaceId: identity.spaceId,
        viewerUserId: identity.userId,
        query: body.query,
        objectTypes,
        objectKinds: body.object_kinds,
        maxResults: controls.maxResults,
        includeTrace: controls.includeTrace,
        feedbackSurface: "source_search",
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

  app.post("/api/v1/sources/retrieval/brief", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const parsed = protocol.RetrievalBriefRequestSchema.safeParse(jsonBody(request));
      if (!parsed.success) throw new HttpError(422, validationMessage(parsed.error.issues));
      const body = parsed.data;
      const objectTypes = sourceObjectTypes(body.object_types);
      const pool = dbPool(context.config);
      const retrievalSettings = await readSpaceRetrievalSettings(pool, identity.spaceId);
      const store = resolveProviderCommandStore(context.config);
      const egressPolicy = { externalEgressEnabled: retrievalSettings.externalEgressEnabled };
      const search = new RetrievalSearchService(pool, sourceRetrievalRegistry, {
        egressPolicy,
        queryEmbedder: new ProviderQueryEmbedder(
          store,
          null,
          undefined,
          retrievalSettings.embeddingDimensions,
          egressPolicy,
        ),
        reranker: retrievalSettings.rerankEnabled
          ? new ProviderReranker(store, { databaseUrl: context.config.databaseUrl, surface: "source_brief", egressPolicy })
          : undefined,
        synthesizer: new ProviderSynthesizer(store, {
          databaseUrl: context.config.databaseUrl,
          surface: "source_brief",
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
        objectTypes,
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
          objectTypes,
          objectKinds: body.object_kinds,
          maxResults,
          includeTrace,
          mode,
          surface: "source_brief",
          response,
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
            ranking_config: retrievalSettings.rankingConfig,
          },
        });
        return reply.send({ ...response, artifact_id: artifactId });
      } catch {
        return reply.send({ ...response, artifact_error: "retrieval_brief_persist_failed" });
      }
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/retrieval/reindex", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireSpaceMaintenanceRole(context, identity, reply))) return reply;
    try {
      const projection = new RetrievalProjectionService(dbPool(context.config), sourceRetrievalRegistry);
      const summary = await projection.reindexAll(identity.spaceId);
      const embeddingBackfill = await enqueueRetrievalEmbeddingBackfill(context.config, {
        spaceId: identity.spaceId,
        userId: identity.userId,
        trigger: "source_retrieval_reindex",
      }).catch((error) => {
        process.stderr.write(
          `[source.retrieval] embedding backfill enqueue failed: ${String((error as Error)?.message ?? error)}\n`,
        );
        return null;
      });
      return reply.send({
        ok: true,
        reindexed: summary,
        embedding_backfill_job_id: embeddingBackfill?.jobId ?? null,
      });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connectors", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listConnectors());
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listConnections(identity, {
        view: optionalString(q.view),
        status: optionalString(q.status),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createConnection(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connection = await repository().getConnection(identity, params(request).connectionId ?? "");
      if (!connection) return reply.code(404).send({ detail: "Source connection not found" });
      return reply.send(connection);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/recommendations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().recommendConnection(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/subscription", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().updateConnectionSubscription(
        identity,
        params(request).connectionId ?? "",
        jsonBody(request),
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/source-runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request));
      return reply.send(await listSourceRuns(dbPool(context.config), identity, params(request).connectionId ?? "", {
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/post-processing/rules", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await postProcessing().listRules(identity, params(request).connectionId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/post-processing/rules", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await postProcessing().createRule(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/connections/:connectionId/post-processing/rules/:ruleId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await postProcessing().updateRule(
        identity,
        connectionId,
        params(request).ruleId ?? "",
        jsonBody(request),
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/post-processing/rules/:ruleId/run", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(202).send(await postProcessing().runRuleNow(
        identity,
        connectionId,
        params(request).ruleId ?? "",
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/post-processing/runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request));
      return reply.send(await postProcessing().listRuns(identity, params(request).connectionId ?? "", limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/post-processing/backlog", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await postProcessing().backlog(identity, params(request).connectionId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/post-processing/decisions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await postProcessing().listDecisions(identity, {
        connectionId: params(request).connectionId ?? "",
        ruleId: optionalString(q.rule_id),
        relevance: optionalString(q.relevance),
        reviewStatus: optionalString(q.review_status),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/post-processing/rules/:ruleId/drain", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(202).send(await postProcessing().drainRuleNow(
        identity,
        connectionId,
        params(request).ruleId ?? "",
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/post-processing/decisions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await postProcessing().listDecisions(identity, {
        connectionId: optionalString(q.connection_id),
        projectId: optionalString(q.project_id),
        ruleId: optionalString(q.rule_id),
        relevance: optionalString(q.relevance),
        reviewStatus: optionalString(q.review_status),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/briefings", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await postProcessing().listBriefings(identity, {
        connectionId: optionalString(q.connection_id),
        projectId: optionalString(q.project_id),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/briefings/:connectionId/:date", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await postProcessing().getBriefing(
        identity,
        params(request).connectionId ?? "",
        params(request).date ?? "",
      ));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/post-processing/decisions/:decisionId/actions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const action = optionalString(body.action);
      const policyAction = action === "queue_content" || action === "extract_evidence"
        ? "source.item_create"
        : "source.item_update";
      const gate = await enforceSources(context, identity, policyAction, "source_item");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await postProcessing().decisionAction(identity, params(request).decisionId ?? "", body));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/connections/:connectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateConnection(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/sources/connections/:connectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateConnection(identity, connectionId, { status: "archived" }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/connections/:connectionId/scan", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "source.item_create", "extraction_job");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(202).send(await repository().scanConnection(identity, params(request).connectionId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/items", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listItems(identity, {
        libraryStatus: optionalString(q.library_status),
        readStatus: optionalString(q.read_status),
        contentState: optionalString(q.content_state),
        connectionId: optionalString(q.connection_id),
        itemType: optionalString(q.item_type),
        libraryType: optionalString(q.library_type),
        sourceDomain: optionalString(q.source_domain),
        createdAfter: toDbDate(q.created_after),
        occurredAfter: toDbDate(q.occurred_after),
        q: optionalString(q.q),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/items/manual-url", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "source.item_create", "source_item");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createManualUrl(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/items/:itemId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const item = await repository().getItem(identity, params(request).itemId ?? "");
      if (!item) return reply.code(404).send({ detail: "Source item not found" });
      return reply.send(item);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/items/:itemId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const itemId = params(request).itemId ?? "";
      const gate = await enforceSources(context, identity, "source.item_update", "source_item", itemId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateItem(identity, itemId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/items/:itemId/actions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const itemId = params(request).itemId ?? "";
      const body = jsonBody(request);
      const action = typeof body.action === "string" ? body.action : "";
      const policyAction =
        action === "queue_content" || action === "archive_snapshot"
          ? "source.item_create"
          : "source.item_update";
      const gate = await enforceSources(context, identity, policyAction, "source_item", itemId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().itemAction(identity, itemId, body));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/jobs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listJobs(identity, {
        status: optionalString(q.status),
        sourceItemId: optionalString(q.source_item_id),
        connectionId: optionalString(q.connection_id),
        jobType: optionalString(q.job_type),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/jobs/:jobId/run", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const jobId = params(request).jobId ?? "";
      const gate = await enforceSources(context, identity, "source.item_create", "extraction_job", jobId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().runJob(identity, jobId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/evidence", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listEvidence(identity, {
        status: optionalString(q.status),
        evidenceType: optionalString(q.evidence_type),
        sourceItemId: optionalString(q.source_item_id),
        projectId: optionalString(q.project_id),
        connectionId: optionalString(q.connection_id),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/evidence", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "evidence.create", "evidence");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createEvidence(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/evidence/:evidenceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const evidence = await repository().getEvidence(identity, params(request).evidenceId ?? "");
      if (!evidence) return reply.code(404).send({ detail: "Evidence not found" });
      return reply.send(evidence);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/evidence/:evidenceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const evidenceId = params(request).evidenceId ?? "";
      const gate = await enforceSources(context, identity, "evidence.update", "evidence", evidenceId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateEvidence(identity, evidenceId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/evidence-links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q, 100);
      return reply.send(await repository().listEvidenceLinks(identity, {
        evidenceId: optionalString(q.evidence_id),
        targetType: optionalString(q.target_type),
        targetId: optionalString(q.target_id),
        status: optionalString(q.status),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/evidence-links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "evidence.link", "evidence");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createEvidenceLink(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/project-source-bindings", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(await repository().listProjectSourceBindings(identity, {
        projectId: requiredString(q.project_id, "project_id"),
        sourceConnectionId: optionalString(q.source_connection_id),
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/project-source-bindings", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "project_source.configure", "project_source");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createProjectSourceBinding(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/project-source-bindings/:bindingId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "project_source.configure", "project_source");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      const bindingId = requiredString(params(request).bindingId, "binding_id");
      return reply.send(await repository().updateProjectSourceBinding(identity, bindingId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/sources/project-source-bindings/:bindingId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "project_source.configure", "project_source");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      const bindingId = requiredString(params(request).bindingId, "binding_id");
      return reply.send(await repository().deleteProjectSourceBinding(identity, bindingId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/project-source-bindings/:bindingId/backfill", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "project_source.configure", "project_source");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      const bindingId = requiredString(params(request).bindingId, "binding_id");
      return reply.send(await repository().backfillProjectSourceBinding(identity, bindingId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/project-items", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listProjectItems(identity, {
        projectId: requiredString(q.project_id, "project_id"),
        sourceConnectionId: optionalString(q.source_connection_id),
        itemType: optionalString(q.item_type),
        sourceDomain: optionalString(q.source_domain),
        matchedDate: optionalString(q.matched_date),
        createdAfter: toDbDate(q.created_after),
        occurredAfter: toDbDate(q.occurred_after),
        q: optionalString(q.q),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/project-source-summary", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(await repository().projectSourceSummary(identity, requiredString(q.project_id, "project_id")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/project-source-health", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(await repository().projectSourceHealth(identity, requiredString(q.project_id, "project_id")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/source-health", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(await repository().sourceHealth(identity, { connectionId: optionalString(q.connection_id) }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/post-processing/run-once", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await postProcessing().runOneOff(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  // ── Reader routes ────────────────────────────────────────────────────────────

  const readerRepo = () => new PgReaderRepository(dbPool(context.config), context.config);
  const annotationRepo = () => new PgAnnotationRepository(dbPool(context.config));
  const commentRepo = () => new PgCommentRepository(dbPool(context.config));
  const actionRepo = () => new PgReaderActionRepository(dbPool(context.config));

  app.get("/api/v1/sources/reader/documents/:documentType/:documentId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const doc = await readerRepo().getDocument(identity, p.documentType ?? "", p.documentId ?? "");
      if (!doc) return reply.code(404).send({ detail: "Document not found or not accessible" });
      return reply.send(doc);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/reader/documents/:documentType/:documentId/annotations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const items = await annotationRepo().listAnnotations(identity, p.documentType ?? "", p.documentId ?? "");
      return reply.send({ items });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/reader/annotations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const result = await annotationRepo().createAnnotation(identity, jsonBody(request));
      return reply.code(201).send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/reader/annotations/:annotationId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await annotationRepo().updateAnnotation(identity, p.annotationId ?? "", jsonBody(request));
      return reply.send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/sources/reader/annotations/:annotationId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      await annotationRepo().archiveAnnotation(identity, p.annotationId ?? "");
      return reply.code(204).send();
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/reader/annotations/:annotationId/comments", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await commentRepo().createComment(identity, p.annotationId ?? "", jsonBody(request));
      return reply.code(201).send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/reader/annotations/:annotationId/threads", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const threads = await commentRepo().listThreads(identity, p.annotationId ?? "");
      return reply.send({ items: threads });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/reader/comments/:commentId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await commentRepo().updateComment(identity, p.commentId ?? "", jsonBody(request));
      return reply.send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/sources/reader/comment-threads/:threadId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await commentRepo().updateThread(identity, p.threadId ?? "", jsonBody(request));
      return reply.send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  // Evidence and proposal creation from reader annotations

  app.post("/api/v1/sources/reader/annotations/:annotationId/evidence", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await actionRepo().createEvidence(identity, p.annotationId ?? "", jsonBody(request));
      return reply.code(201).send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/reader/annotations/:annotationId/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const result = await actionRepo().createProposal(identity, p.annotationId ?? "", jsonBody(request));
      return reply.code(201).send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  // Project-scoped annotation summaries

  app.get("/api/v1/sources/reader/annotations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const projectId = optionalString(q.project_id);
      if (!projectId) return reply.code(400).send({ detail: "project_id is required" });
      const limitRaw = Number(q.limit ?? "20");
      const limit = Number.isFinite(limitRaw) && limitRaw > 0 ? Math.min(limitRaw, 100) : 20;
      const items = await actionRepo().listProjectAnnotations(identity, projectId, limit);
      return reply.send({ items });
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}

function sourcesHealth(context: ModuleContext) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send({ ok: true });
  };
}

const SOURCE_RETRIEVAL_OBJECT_TYPES = ["source_item", "extracted_evidence"] as const;

function sourceObjectTypes(values: RetrievalObjectType[] | undefined): RetrievalObjectType[] {
  if (!values || values.length === 0) return [...SOURCE_RETRIEVAL_OBJECT_TYPES];
  const invalid = values.filter((value) => !(SOURCE_RETRIEVAL_OBJECT_TYPES as readonly string[]).includes(value));
  if (invalid.length > 0) {
    throw new HttpError(422, "source retrieval only supports source_item and extracted_evidence");
  }
  return [...new Set(values)];
}

async function requireSpaceMaintenanceRole(
  context: ModuleContext,
  identity: { spaceId: string; userId: string },
  reply: FastifyReply,
): Promise<boolean> {
  return requireSpaceOwnerOrAdmin(context.config, identity, reply);
}

function validationMessage(issues: Array<{ path: Array<string | number>; message: string }>): string {
  const issue = issues[0];
  if (!issue) return "Invalid request body";
  const path = issue.path.length ? `${issue.path.join(".")}: ` : "";
  return `${path}${issue.message}`;
}
