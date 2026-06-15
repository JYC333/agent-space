import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { checkInternalToken } from "../../gateway/internalAuth";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { forwardPythonAuthorityResponse } from "../../ports/pythonHttp";
import { introspectIdentity } from "../providers/identity";
import { PgRunRepository, type RunRecord } from "./repository";
import { RunOrchestrationService } from "./orchestrationService";
import { RunPythonContextPortClient } from "./pythonContextPorts";
import { RunMaterializationService } from "./materializationService";
import { sharedCliProcessRegistry } from "./processRegistry";

interface RunsCommandServices {
  orchestration: Pick<RunOrchestrationService, "executeRun" | "cancelRun">;
  repository: Pick<PgRunRepository, "getRun">;
}

type RunsCommandServicesFactory = (context: ModuleContext) => RunsCommandServices;
type RunsIdentity = { spaceId: string; userId: string };
type RunsIdentityOverride =
  | RunsIdentity
  | ((request: FastifyRequest) => Promise<RunsIdentity | null> | RunsIdentity | null);
type RunsReadResponseOverride = (
  runId: string,
  request: FastifyRequest,
  reply: FastifyReply,
) => Promise<FastifyReply> | FastifyReply;

let servicesFactoryOverride: RunsCommandServicesFactory | null = null;
let identityOverride: RunsIdentityOverride | null = null;
let readResponseOverride: RunsReadResponseOverride | null = null;

export function __setRunsCommandServicesFactoryForTests(
  factory: RunsCommandServicesFactory | null,
): void {
  servicesFactoryOverride = factory;
}

export function __setRunsIdentityForTests(identity: RunsIdentityOverride | null): void {
  identityOverride = identity;
}

export function __setRunsReadResponseForTests(
  responder: RunsReadResponseOverride | null,
): void {
  readResponseOverride = responder;
}

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function query(request: FastifyRequest): Record<string, string | undefined> {
  return request.query as Record<string, string | undefined>;
}

function bodyText(request: FastifyRequest): string {
  return request.body instanceof Buffer ? request.body.toString("utf8") : "";
}

function jsonBody(request: FastifyRequest): Record<string, unknown> {
  const text = bodyText(request);
  if (!text) return {};
  const parsed = JSON.parse(text) as unknown;
  return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : {};
}

async function resolveIdentity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<{ spaceId: string; userId: string } | null> {
  if (identityOverride) {
    return typeof identityOverride === "function"
      ? identityOverride(request)
      : identityOverride;
  }
  const requestId = resolveRequestId(request);
  reply.header(REQUEST_ID_HEADER, requestId);
  const identity = await introspectIdentity(context.config, request);
  if (identity.ok) return { spaceId: identity.spaceId, userId: identity.userId };
  if (identity.reason === "denied") {
    reply.code(identity.statusCode);
    reply.header("content-type", "application/json");
    reply.send(identity.body);
    return null;
  }
  await sendErrorEnvelope(
    reply,
    502,
    errorEnvelope(
      identity.reason === "contract_violation"
        ? "introspect_contract_violation"
        : "python_authority_unavailable",
      "Identity introspection failed",
      requestId,
    ),
  );
  return null;
}

function commandServices(context: ModuleContext): RunsCommandServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  const repository = PgRunRepository.fromConfig(context.config);
  const contextPorts = new RunPythonContextPortClient(context.config);
  const materializer = new RunMaterializationService(contextPorts);
  return {
    repository,
    orchestration: new RunOrchestrationService(context.config, repository, {
      materializer,
      contextPorts,
      processRegistry: sharedCliProcessRegistry,
    }),
  };
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  if (context.config.runsAuthority !== "ts") return;

  app.post("/api/v1/runs/:runId/execute", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const runId = params(request).runId ?? "";
    const runtime = query(request).runtime;
    if (runtime) {
      return reply.code(400).send({
        detail:
          "Runtime query overrides are not supported by the TS runs authority; use the configured runtime adapter.",
      });
    }
    // The Run row and the policy-owned adapter resolution are authoritative.
    // Execution parameters (prompt, model, adapter config, sandbox, timeouts)
    // are never accepted from the request body.
    const services = commandServices(context);
    await services.orchestration.executeRun({
      run_id: runId,
      space_id: identity.spaceId,
      worker_id: `http:${resolveRequestId(request)}`,
      command_source: "http",
    });
    if (readResponseOverride) return readResponseOverride(runId, request, reply);
    return forwardPythonAuthorityResponse(
      context.config,
      request,
      reply,
      `/api/v1/runs/${encodeURIComponent(runId)}`,
    );
  });

  // Service-authenticated internal execute for Python-owned synchronous
  // callers (currently the agents chat turn). Same orchestration authority as
  // the public route; identity is the internal service token, and the caller
  // supplies the run/space ids it already validated.
  app.post("/internal/runs/execute", async (request, reply) => {
    if (!checkInternalToken(context.config, request)) {
      return reply.code(401).send({ detail: "Unauthorized" });
    }
    const body = jsonBody(request);
    const runId = stringValue(body.run_id);
    const spaceId = stringValue(body.space_id);
    if (!runId || !spaceId) {
      return reply.code(422).send({ detail: "run_id and space_id are required" });
    }
    const services = commandServices(context);
    const result = await services.orchestration.executeRun({
      run_id: runId,
      space_id: spaceId,
      worker_id: stringValue(body.worker_id) ?? "internal",
      command_source: "internal",
    });
    return reply.send(result);
  });

  app.patch("/api/v1/runs/:runId/stop", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const runId = params(request).runId ?? "";
    const body = jsonBody(request);
    const services = commandServices(context);
    const before = await services.repository.getRun(identity.spaceId, runId);
    const result = await services.orchestration.cancelRun({
      run_id: runId,
      space_id: identity.spaceId,
      requested_by_user_id: identity.userId,
      reason: stringValue(body.reason),
    });
    const after = await services.repository.getRun(identity.spaceId, runId);
    const run = after ?? before;
    if (!run && result.status === "unknown") {
      return reply.code(404).send({ detail: "Run not found in this space." });
    }
    return reply.send(stopResponse(run, result.status, !result.skipped));
  });
}

function stopResponse(
  run: RunRecord | null,
  fallbackStatus: string,
  changed: boolean,
): Record<string, unknown> {
  return {
    id: run?.id ?? null,
    status: run?.status ?? fallbackStatus,
    mode: run?.mode ?? null,
    run_type: run?.run_type ?? "agent",
    trigger_origin: run?.trigger_origin ?? null,
    started_at: run?.started_at ?? null,
    ended_at: run?.ended_at ?? null,
    error_message: run?.error_message ?? null,
    changed,
  };
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
