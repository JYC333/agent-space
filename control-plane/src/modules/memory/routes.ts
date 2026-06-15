import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../providers/identity";
import { loadProtocol } from "../providers/protocolRuntime";
import { PgMemoryReadRepository, MemoryReadValidationError } from "./repository";
import {
  MemoryProposalForbiddenError,
  MemoryProposalNotFoundError,
  MemoryProposalPolicyError,
  MemoryProposalValidationError,
  PgMemoryProposalRepository,
} from "./proposalRepository";

/**
 * TS memory model (Stage 6 slices 5-6).
 *
 * Behind `CONTROL_PLANE_MEMORY_AUTHORITY=ts` the control plane serves the read
 * routes (`GET /memory`, `GET /memory/{id}`, `POST /memory/search`) from the DB
 * with the `can_read_memory` visibility rules + summary-only redaction (see
 * `memoryReadAuth.ts`). It also owns public memory proposal creation
 * (`POST`/`PATCH`/`DELETE /memory`): those routes INSERT pending `proposals`
 * rows only and never mutate active `memory_entries`. Read-access audit still
 * returns with the memory apply slice that owns `memory_access_logs`.
 */
interface MemoryServices {
  repository: Pick<PgMemoryReadRepository, "list" | "get" | "search"> &
    Pick<
      PgMemoryProposalRepository,
      "createMemoryProposal" | "updateMemoryProposal" | "archiveMemoryProposal"
    >;
}

type MemoryServicesFactory = (context: ModuleContext) => MemoryServices;
type MemoryIdentity = { spaceId: string; userId: string };
type MemoryIdentityOverride =
  | MemoryIdentity
  | ((request: FastifyRequest) => Promise<MemoryIdentity | null> | MemoryIdentity | null);

let servicesFactoryOverride: MemoryServicesFactory | null = null;
let identityOverride: MemoryIdentityOverride | null = null;

export function __setMemoryServicesFactoryForTests(
  factory: MemoryServicesFactory | null,
): void {
  servicesFactoryOverride = factory;
}

export function __setMemoryIdentityForTests(identity: MemoryIdentityOverride | null): void {
  identityOverride = identity;
}

function memoryServices(context: ModuleContext): MemoryServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  const readRepository = PgMemoryReadRepository.fromConfig(context.config);
  const proposalRepository = PgMemoryProposalRepository.fromConfig(context.config);
  return {
    repository: {
      list: readRepository.list.bind(readRepository),
      get: readRepository.get.bind(readRepository),
      search: readRepository.search.bind(readRepository),
      createMemoryProposal: proposalRepository.createMemoryProposal.bind(proposalRepository),
      updateMemoryProposal: proposalRepository.updateMemoryProposal.bind(proposalRepository),
      archiveMemoryProposal: proposalRepository.archiveMemoryProposal.bind(proposalRepository),
    },
  };
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  if (context.config.memoryAuthority !== "ts") return;

  app.get("/api/v1/memory", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const q = query(request);
    const limit = intQuery(q.limit, 50);
    const offset = intQuery(q.offset, 0);
    if (limit === null || limit < 0 || limit > 200) {
      return reply.code(422).send({ detail: "limit must be between 0 and 200" });
    }
    if (offset === null || offset < 0) {
      return reply.code(422).send({ detail: "offset must be non-negative" });
    }
    try {
      const page = await memoryServices(context).repository.list(
        identity.spaceId,
        identity.userId,
        {
          scope: optionalString(q.scope),
          namespace: optionalString(q.namespace),
          memoryType: optionalString(q.type),
          status: q.status === undefined ? "active" : q.status,
          workspaceId: optionalString(q.workspace_id),
          projectId: optionalString(q.project_id),
          includeSystem: boolQuery(q.include_system),
          limit,
          offset,
        },
      );
      return reply.send(page);
    } catch (error) {
      if (error instanceof MemoryReadValidationError) {
        return reply.code(422).send({ detail: error.message });
      }
      return sendDomainError(reply, error);
    }
  });

  app.get("/api/v1/memory/:memoryId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const memoryId = params(request).memoryId ?? "";
    const workspaceId = optionalString(query(request).workspace_id);
    const memory = await memoryServices(context).repository.get(
      identity.spaceId,
      identity.userId,
      memoryId,
      workspaceId,
    );
    if (!memory) return reply.code(404).send({ detail: "Memory not found" });
    return reply.send(memory);
  });

  app.post("/api/v1/memory/search", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const body = protocol.MemorySearchRequestSchema.parse(jsonBody(request));
      // Python honors body space_id/user_id overrides over the caller identity.
      const spaceId = body.space_id ?? identity.spaceId;
      const userId = body.user_id ?? identity.userId;
      const rows = await memoryServices(context).repository.search(spaceId, userId, {
        query: body.query,
        scope: body.scope ?? null,
        namespace: body.namespace ?? null,
        memoryType: body.type ?? null,
        workspaceId: body.workspace_id ?? null,
        includeSystem: body.include_system,
        limit: body.limit,
      });
      return reply.send(rows);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/api/v1/memory", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    try {
      const protocol = await loadProtocol();
      const command = protocol.MemoryProposalCreateCommandSchema.parse({
        ...jsonBody(request),
        operation: "create",
      });
      const proposal = await memoryServices(context).repository.createMemoryProposal(
        identity.spaceId,
        identity.userId,
        command,
      );
      return reply.code(202).send(proposal);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.patch("/api/v1/memory/:memoryId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const memoryId = params(request).memoryId ?? "";
    const workspaceId = optionalString(query(request).workspace_id);
    try {
      const protocol = await loadProtocol();
      const command = protocol.MemoryProposalUpdateCommandSchema.parse({
        ...jsonBody(request),
        operation: "update",
        target_memory_id: memoryId,
      });
      const proposal = await memoryServices(context).repository.updateMemoryProposal(
        identity.spaceId,
        identity.userId,
        memoryId,
        workspaceId,
        command,
      );
      return reply.code(202).send(proposal);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.delete("/api/v1/memory/:memoryId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const memoryId = params(request).memoryId ?? "";
    const workspaceId = optionalString(query(request).workspace_id);
    try {
      const protocol = await loadProtocol();
      const command = protocol.MemoryProposalArchiveCommandSchema.parse({
        operation: "archive",
        target_memory_id: memoryId,
        workspace_id: workspaceId,
      });
      const proposal = await memoryServices(context).repository.archiveMemoryProposal(
        identity.spaceId,
        identity.userId,
        memoryId,
        workspaceId,
        command,
      );
      return reply.code(202).send(proposal);
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });
}

async function resolveIdentity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<MemoryIdentity | null> {
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

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  if (error instanceof MemoryProposalPolicyError) {
    return reply.code(error.statusCode).send(error.body);
  }
  if (
    error instanceof MemoryProposalValidationError ||
    error instanceof MemoryProposalForbiddenError ||
    error instanceof MemoryProposalNotFoundError
  ) {
    return reply.code(error.statusCode).send({ detail: error.message });
  }
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(400).send({ detail: message });
}

function params(request: FastifyRequest): Record<string, string | undefined> {
  return request.params as Record<string, string | undefined>;
}

function query(request: FastifyRequest): Record<string, string | undefined> {
  return request.query as Record<string, string | undefined>;
}

function jsonBody(request: FastifyRequest): Record<string, unknown> {
  const text = request.body instanceof Buffer ? request.body.toString("utf8") : "";
  if (!text) return {};
  const parsed = JSON.parse(text) as unknown;
  return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
    ? (parsed as Record<string, unknown>)
    : {};
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function boolQuery(value: string | undefined): boolean {
  return value === "true" || value === "1";
}

function intQuery(value: string | undefined, fallback: number): number | null {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}
