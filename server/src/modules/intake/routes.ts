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
  type SpaceUserIdentity,
} from "../routeUtils/common";
import { enforce } from "../policy";
import { loadActionRegistry } from "../policy/actionRegistry";
import { PgIntakeRepository } from "./repository";

async function enforceIntake(
  context: ModuleContext,
  identity: SpaceUserIdentity,
  action: string,
  resourceType: string,
  resourceId?: string,
): Promise<{ blocked: boolean; reply403: Record<string, string> | null }> {
  const registry = await loadActionRegistry();
  const result = await enforce(context.config, registry, {
    action,
    actor_type: "user",
    actor_id: identity.userId,
    space_id: identity.spaceId,
    resource_type: resourceType,
    resource_id: resourceId ?? null,
    force_record: false,
  });
  if (result.status === "blocked") {
    return { blocked: true, reply403: { detail: result.message ?? "Policy denied" } };
  }
  return { blocked: false, reply403: null };
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const repository = () => new PgIntakeRepository(dbPool(context.config), context.config);

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
        action === "queue_content" || action === "snapshot"
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
      return reply.send(await repository().listWorkspaceBindings(identity));
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
}

function intakeHealth(context: ModuleContext) {
  return async (request: FastifyRequest, reply: FastifyReply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send({ ok: true });
  };
}
