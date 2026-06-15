import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { errorEnvelope, sendErrorEnvelope } from "../../gateway/errorEnvelope";
import { REQUEST_ID_HEADER, resolveRequestId } from "../../gateway/requestContext";
import { introspectIdentity } from "../providers/identity";
import { ProposalPythonPortClient, ProposalPythonPortError } from "./pythonProposalPorts";
import { PgProposalRepository, type ProposalListFilters } from "./repository";
import {
  MemoryApplyError,
  MemoryApplyUnsupportedError,
  PgMemoryApplyRepository,
} from "../memory/memoryApplyRepository";
import { applyGatedMemoryProposal } from "../memory/memoryAcceptDispatch";
import type { ProposalOut, ProposalPage } from "@agent-space/protocol" with { "resolution-mode": "import" };

interface ProposalServices {
  repository: Pick<PgProposalRepository, "listVisible" | "getVisible">;
  ports: Pick<
    ProposalPythonPortClient,
    "acceptProposal" | "rejectProposal" | "approveEgressGrantingUser" | "gateMemoryApply"
  >;
}

type ProposalServicesFactory = (context: ModuleContext) => ProposalServices;
type ProposalIdentity = { spaceId: string; userId: string };
type ProposalIdentityOverride =
  | ProposalIdentity
  | ((request: FastifyRequest) => Promise<ProposalIdentity | null> | ProposalIdentity | null);

let servicesFactoryOverride: ProposalServicesFactory | null = null;
let identityOverride: ProposalIdentityOverride | null = null;

export function __setProposalServicesFactoryForTests(
  factory: ProposalServicesFactory | null,
): void {
  servicesFactoryOverride = factory;
}

export function __setProposalIdentityForTests(
  identity: ProposalIdentityOverride | null,
): void {
  identityOverride = identity;
}

function proposalServices(context: ModuleContext): ProposalServices {
  if (servicesFactoryOverride) return servicesFactoryOverride(context);
  return {
    repository: PgProposalRepository.fromConfig(context.config),
    ports: new ProposalPythonPortClient(context.config),
  };
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  if (context.config.proposalsAuthority !== "ts") return;

  app.get("/api/v1/proposals", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const parsed = parseListFilters(request);
    if ("error" in parsed) return reply.code(422).send({ detail: parsed.error });
    const services = proposalServices(context);
    const page = await services.repository.listVisible(
      identity.spaceId,
      identity.userId,
      parsed.filters,
    );
    return reply.send(page);
  });

  app.get("/api/v1/proposals/:proposalId", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const proposalId = params(request).proposalId ?? "";
    const services = proposalServices(context);
    const proposal = await services.repository.getVisible(
      identity.spaceId,
      identity.userId,
      proposalId,
    );
    if (!proposal) return reply.code(404).send({ detail: "Proposal not found" });
    return reply.send(proposal);
  });

  app.post("/api/v1/proposals/:proposalId/accept", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const proposalId = params(request).proposalId ?? "";
    const services = proposalServices(context);

    // Stage 6 slice 7b: TS applies accepted memory proposals itself. Gate the
    // proposal through the Python memory-apply-gate port, then run the active
    // memory writes + accept state transition in one TS transaction.
    if (context.config.memoryApplyAuthority === "ts") {
      const existing = await services.repository.getVisible(
        identity.spaceId,
        identity.userId,
        proposalId,
      );
      if (existing && PgMemoryApplyRepository.supportsType(existing.proposal_type)) {
        try {
          const gate = await services.ports.gateMemoryApply({
            proposal_id: proposalId,
            space_id: identity.spaceId,
            user_id: identity.userId,
          });
          const applied = await applyGatedMemoryProposal(context.config, gate, identity.userId);
          const accepted = await services.repository.getVisible(
            identity.spaceId,
            identity.userId,
            proposalId,
          );
          return reply.send({
            proposal: accepted,
            result_type: "memory_entry",
            result: { memory: applied.memory },
          });
        } catch (error) {
          return sendMemoryAcceptError(request, reply, error);
        }
      }
    }

    try {
      const result = await services.ports.acceptProposal({
        proposal_id: proposalId,
        space_id: identity.spaceId,
        user_id: identity.userId,
        confirm_incomplete_patch: boolQuery(query(request).confirm_incomplete_patch) ?? false,
      });
      return reply.send(result);
    } catch (error) {
      return sendPortError(request, reply, error);
    }
  });

  app.post("/api/v1/proposals/:proposalId/reject", async (request, reply) => {
    const identity = await resolveIdentity(context, request, reply);
    if (!identity) return reply;
    const proposalId = params(request).proposalId ?? "";
    const services = proposalServices(context);
    try {
      const result = await services.ports.rejectProposal({
        proposal_id: proposalId,
        space_id: identity.spaceId,
        user_id: identity.userId,
      });
      return reply.send(result);
    } catch (error) {
      return sendPortError(request, reply, error);
    }
  });

  app.post(
    "/api/v1/proposals/:proposalId/approvals/egress-granting-user",
    async (request, reply) => {
      const identity = await resolveIdentity(context, request, reply);
      if (!identity) return reply;
      const proposalId = params(request).proposalId ?? "";
      const body = jsonBody(request);
      const services = proposalServices(context);
      try {
        const result = await services.ports.approveEgressGrantingUser({
          proposal_id: proposalId,
          space_id: identity.spaceId,
          user_id: identity.userId,
          grant_id: stringValue(body.grant_id),
        });
        return reply.send(result);
      } catch (error) {
        return sendPortError(request, reply, error);
      }
    },
  );
}

async function resolveIdentity(
  context: ModuleContext,
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<ProposalIdentity | null> {
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

function parseListFilters(
  request: FastifyRequest,
): { filters: ProposalListFilters } | { error: string } {
  const q = query(request);
  const status = resolveStatus(q.status);
  if (status instanceof Error) return { error: status.message };
  const limit = intQuery(q.limit, 50);
  const offset = intQuery(q.offset, 0);
  if (limit === null || limit < 0 || limit > 200) {
    return { error: "limit must be between 0 and 200" };
  }
  if (offset === null || offset < 0) return { error: "offset must be non-negative" };
  const urgency = q.urgency;
  if (urgency && !["low", "normal", "high", "critical"].includes(urgency)) {
    return { error: `Invalid urgency ${JSON.stringify(urgency)}` };
  }
  const expired = boolQuery(q.expired);
  if (q.expired !== undefined && expired === null) {
    return { error: `Invalid expired ${JSON.stringify(q.expired)}` };
  }
  return {
    filters: {
      status,
      proposalType: q.type ?? null,
      urgency: urgency ?? null,
      expired,
      projectId: q.project_id ?? null,
      limit,
      offset,
    },
  };
}

function resolveStatus(raw: string | undefined): string | null | Error {
  if (raw === undefined) return "pending";
  if (raw === "all") return null;
  if (raw === "pending" || raw === "accepted" || raw === "rejected") return raw;
  return new Error(`Invalid status ${JSON.stringify(raw)}`);
}

function sendMemoryAcceptError(
  request: FastifyRequest,
  reply: FastifyReply,
  error: unknown,
): FastifyReply | Promise<FastifyReply> {
  // Source-monitoring / placement rejections from the TS applier.
  if (error instanceof MemoryApplyError) {
    return reply.code(error.statusCode).send({ detail: error.message });
  }
  // Run/grant egress context or workspace/agent scope: not served by TS yet.
  if (error instanceof MemoryApplyUnsupportedError) {
    return reply.code(error.statusCode).send({ detail: error.message });
  }
  // Gate-port errors (policy block, 404 already-decided) preserve the Python body.
  return sendPortError(request, reply, error);
}

function sendPortError(
  request: FastifyRequest,
  reply: FastifyReply,
  error: unknown,
): FastifyReply | Promise<FastifyReply> {
  if (error instanceof ProposalPythonPortError) {
    if (error.statusCode && error.responseBody !== undefined) {
      return reply.code(error.statusCode).send(error.responseBody);
    }
    return sendErrorEnvelope(
      reply,
      error.statusCode ?? 502,
      errorEnvelope(error.code, error.message, resolveRequestId(request)),
    );
  }
  throw error;
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

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function boolQuery(value: string | undefined): boolean | null {
  if (value === undefined) return null;
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return null;
}

function intQuery(value: string | undefined, fallback: number): number | null {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}

export type { ProposalOut, ProposalPage };
