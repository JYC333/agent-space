import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  jsonBody,
  optionalString,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { PgRunContextRepository, buildContextPackage } from "./repository";

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  app.post("/api/v1/context/build", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const body = jsonBody(request);
      const q = query(request);
      const workspaceId = optionalString(body.workspace_id) ?? optionalString(q.workspace_id);
      const projectId = optionalString(body.project_id) ?? optionalString(q.project_id);
      const agentId = optionalString(body.agent_id) ?? optionalString(q.agent_id);
      const capabilityId = optionalString(body.capability_id) ?? optionalString(q.capability_id);
      const sessionId = optionalString(body.session_id) ?? optionalString(q.session_id);
      const runId = optionalString(body.run_id) ?? optionalString(q.run_id);
      const repo = PgRunContextRepository.fromConfig(context.config);
      const retrieval = await repo.retrieve({
        spaceId: identity.spaceId,
        userId: identity.userId,
        workspaceId,
        agentId,
        capabilityId,
        query: optionalString(body.query) ?? optionalString(q.query),
        agentMemoryPolicy: null,
        includeSystemScope: true,
      });
      const sessionSummary = await repo.loadLatestSessionSummary(identity.spaceId, sessionId);
      const evidenceSelections = await repo.selectEvidenceForContext({
        spaceId: identity.spaceId,
        workspaceId,
        projectId,
        runId,
      });
      const pkg = buildContextPackage({
        memories: retrieval.memories,
        activePolicies: retrieval.activePolicies,
        sourceRefs: retrieval.sourceRefs,
        retrievalTrace: {
          ...retrieval.retrievalTrace,
          preview_request: {
            workspace_id: workspaceId,
            project_id: projectId,
            agent_id: agentId,
            capability_id: capabilityId,
            session_id: sessionId,
            run_id: runId,
          },
        },
        tokenBudget: retrieval.tokenBudget,
        userId: identity.userId,
        spaceId: identity.spaceId,
        workspaceId,
        sessionSummary,
        evidenceSelections,
      });
      return reply.send(pkg);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
