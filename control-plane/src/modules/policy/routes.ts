/**
 * Policy module routes — internal, service-authenticated enforcement port.
 *
 * Python-owned callers reach the TS policy authority through this port so there
 * is never a second decider (§8.1). Run orchestration already calls
 * `policy.enforce` via its context port. Proposal-apply uses the same internal
 * boundary, with Python supplying membership-role and supported proposal-type
 * inputs while TS owns the decision and audit write.
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { checkInternalToken } from "../../gateway/internalAuth";
import { loadProtocol } from "../providers/protocolRuntime";
import { loadActionRegistry } from "./actionRegistry";
import { enforce, enforceProposalApply } from "./service";

function jsonBody(request: FastifyRequest): unknown {
  const text = request.body instanceof Buffer ? request.body.toString("utf8") : "";
  return text ? JSON.parse(text) : {};
}

function sendDomainError(reply: FastifyReply, error: unknown): FastifyReply {
  const message = error instanceof Error ? error.message : "Request failed";
  return reply.code(400).send({ detail: message });
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.post("/internal/policy/enforce", async (request, reply) => {
    if (!checkInternalToken(context.config, request)) {
      return reply.code(401).send({ detail: "Unauthorized" });
    }
    try {
      const protocol = await loadProtocol();
      const req = protocol.PolicyCheckRequestSchema.parse(jsonBody(request));
      const registry = await loadActionRegistry();
      const result = await enforce(context.config, registry, req);
      return reply.send(protocol.PolicyEnforceResultSchema.parse(result));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });

  app.post("/internal/policy/enforce-proposal-apply", async (request, reply) => {
    if (!checkInternalToken(context.config, request)) {
      return reply.code(401).send({ detail: "Unauthorized" });
    }
    try {
      const protocol = await loadProtocol();
      const req = protocol.PolicyProposalApplyRequestSchema.parse(jsonBody(request));
      const result = await enforceProposalApply(
        context.config,
        {
          user_id: req.user_id,
          space_id: req.space_id,
          proposal_id: req.proposal_id,
          proposal_type: req.proposal_type,
          declared_risk: req.risk_level ?? null,
          proposal_payload: req.payload ?? null,
          metadata_json: req.metadata_json ?? null,
        },
        req.membership_role ?? null,
        new Set(req.supported_proposal_types),
      );
      return reply.send(protocol.PolicyEnforceResultSchema.parse(result));
    } catch (error) {
      return sendDomainError(reply, error);
    }
  });
}
