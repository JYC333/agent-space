import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  boolQuery,
  dbPool,
  jsonBody,
  optionalString,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
  toDbDate,
} from "../routeUtils/common";
import { enforceIntake } from "./enforceIntake";
import { PgIntakeRepository } from "./repository";
import { registerCustomSourceRoutes } from "./customSourceRoutes";
import { registerSourceRecipeRoutes } from "./sourceRecipeRoutes";
import { listSourceRuns } from "./sourceRunReadModel";
import { PgAnnotationRepository, PgCommentRepository, PgReaderActionRepository, PgReaderRepository } from "./readerRepository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new PgIntakeRepository(dbPool(context.config), context.config);
  registerCustomSourceRoutes(app, context);
  registerSourceRecipeRoutes(app, context);

  app.get("/api/v1/intake", intakeHealth(context));
  app.get("/api/v1/intake/", intakeHealth(context));

  app.get("/api/v1/intake/connectors", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listConnectors());
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/connections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listConnections(identity, { status: optionalString(q.status), limit, offset }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/connections", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.connection_manage", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createConnection(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/connections/:connectionId", async (request, reply) => {
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

  app.get("/api/v1/intake/connections/:connectionId/source-runs", async (request, reply) => {
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

  app.patch("/api/v1/intake/connections/:connectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateConnection(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.delete("/api/v1/intake/connections/:connectionId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.connection_manage", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateConnection(identity, connectionId, { status: "archived" }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/connections/:connectionId/scan", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.item_create", "extraction_job");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(202).send(await repository().scanConnection(identity, params(request).connectionId ?? ""));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/items", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listItems(identity, {
        status: optionalString(q.status),
        readStatus: optionalString(q.read_status),
        contentState: optionalString(q.content_state),
        connectionId: optionalString(q.connection_id),
        itemType: optionalString(q.item_type),
        sourceDomain: optionalString(q.source_domain),
        createdAfter: toDbDate(q.created_after),
        occurredAfter: toDbDate(q.occurred_after),
        includeIgnored: boolQuery(q.include_ignored, false),
        includeArchived: boolQuery(q.include_archived, false),
        q: optionalString(q.q),
        projectId: optionalString(q.project_id),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/items/manual-url", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.item_create", "intake_item");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createManualUrl(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/items/:itemId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const item = await repository().getItem(identity, params(request).itemId ?? "");
      if (!item) return reply.code(404).send({ detail: "Intake item not found" });
      return reply.send(item);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/items/:itemId/actions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const itemId = params(request).itemId ?? "";
      const body = jsonBody(request);
      const action = typeof body.action === "string" ? body.action : "";
      const policyAction =
        action === "queue_content" || action === "archive_snapshot"
          ? "intake.item_create"
          : "intake.item_update";
      const gate = await enforceIntake(context, identity, policyAction, "intake_item", itemId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().itemAction(identity, itemId, body));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/jobs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listJobs(identity, {
        status: optionalString(q.status),
        intakeItemId: optionalString(q.intake_item_id),
        connectionId: optionalString(q.connection_id),
        jobType: optionalString(q.job_type),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/jobs/:jobId/run", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const jobId = params(request).jobId ?? "";
      const gate = await enforceIntake(context, identity, "intake.item_create", "extraction_job", jobId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().runJob(identity, jobId));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/evidence", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      const { limit, offset } = parsePage(q);
      return reply.send(await repository().listEvidence(identity, {
        status: optionalString(q.status),
        evidenceType: optionalString(q.evidence_type),
        intakeItemId: optionalString(q.intake_item_id),
        projectId: optionalString(q.project_id),
        connectionId: optionalString(q.connection_id),
        limit,
        offset,
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/evidence", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "evidence.create", "evidence");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createEvidence(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/evidence/:evidenceId", async (request, reply) => {
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

  app.patch("/api/v1/intake/evidence/:evidenceId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const evidenceId = params(request).evidenceId ?? "";
      const gate = await enforceIntake(context, identity, "evidence.update", "evidence", evidenceId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await repository().updateEvidence(identity, evidenceId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/evidence-links", async (request, reply) => {
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

  app.post("/api/v1/intake/evidence-links", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "evidence.link", "evidence");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createEvidenceLink(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/workspace-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository().listWorkspaceProfiles(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/workspace-profiles", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "workspace_intake.configure", "workspace_intake");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createWorkspaceProfile(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/workspace-source-bindings", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(await repository().listWorkspaceBindings(identity, {
        workspaceId: optionalString(q.workspace_id),
        sourceConnectionId: optionalString(q.source_connection_id),
        projectId: optionalString(q.project_id),
      }));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/workspace-source-bindings", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "workspace_intake.configure", "workspace_intake");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await repository().createWorkspaceBinding(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/summary-runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.code(201).send(await repository().createSummaryRun(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/summary-runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.code(405).send({ detail: "Use POST /api/v1/intake/summary-runs to create a summary run" });
  });

  // ── Reader routes ────────────────────────────────────────────────────────────

  const readerRepo = () => new PgReaderRepository(dbPool(context.config), context.config);
  const annotationRepo = () => new PgAnnotationRepository(dbPool(context.config));
  const commentRepo = () => new PgCommentRepository(dbPool(context.config));
  const actionRepo = () => new PgReaderActionRepository(dbPool(context.config));

  app.get("/api/v1/intake/reader/documents/:documentType/:documentId", async (request, reply) => {
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

  app.get("/api/v1/intake/reader/documents/:documentType/:documentId/annotations", async (request, reply) => {
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

  app.post("/api/v1/intake/reader/annotations", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const result = await annotationRepo().createAnnotation(identity, jsonBody(request));
      return reply.code(201).send(result);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch("/api/v1/intake/reader/annotations/:annotationId", async (request, reply) => {
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

  app.delete("/api/v1/intake/reader/annotations/:annotationId", async (request, reply) => {
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

  app.post("/api/v1/intake/reader/annotations/:annotationId/comments", async (request, reply) => {
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

  app.get("/api/v1/intake/reader/annotations/:annotationId/threads", async (request, reply) => {
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

  app.patch("/api/v1/intake/reader/comments/:commentId", async (request, reply) => {
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

  app.patch("/api/v1/intake/reader/comment-threads/:threadId", async (request, reply) => {
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

  app.post("/api/v1/intake/reader/annotations/:annotationId/evidence", async (request, reply) => {
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

  app.post("/api/v1/intake/reader/annotations/:annotationId/proposals", async (request, reply) => {
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

  app.get("/api/v1/intake/reader/annotations", async (request, reply) => {
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

function intakeHealth(context: ModuleContext) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send({ ok: true });
  };
}
