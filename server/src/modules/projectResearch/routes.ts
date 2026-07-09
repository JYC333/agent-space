import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import { HttpError, dbPool, jsonBody, optionalString, params, query, resolveIdentity, sendRouteError } from "../routeUtils/common";
import { ProjectResearchRepository } from "./repository";
import { ProjectExperimentRepository } from "./experimentRepository";

let repositoryFactoryOverride: ((context: ModuleContext) => ProjectResearchRepository) | null = null;
let experimentRepositoryFactoryOverride: ((context: ModuleContext) => ProjectExperimentRepository) | null = null;

export function __setProjectResearchRepositoryFactoryForTests(
  factory: ((context: ModuleContext) => ProjectResearchRepository) | null,
): void {
  repositoryFactoryOverride = factory;
}

export function __setProjectExperimentRepositoryFactoryForTests(
  factory: ((context: ModuleContext) => ProjectExperimentRepository) | null,
): void {
  experimentRepositoryFactoryOverride = factory;
}

function repository(context: ModuleContext): ProjectResearchRepository {
  if (repositoryFactoryOverride) return repositoryFactoryOverride(context);
  return new ProjectResearchRepository(dbPool(context.config));
}

function experimentRepository(context: ModuleContext): ProjectExperimentRepository {
  if (experimentRepositoryFactoryOverride) return experimentRepositoryFactoryOverride(context);
  return new ProjectExperimentRepository(dbPool(context.config));
}

function requireParam(request: Parameters<typeof params>[0], name: string): string {
  const value = params(request)[name];
  if (!value) throw new HttpError(422, `${name} is required`);
  return value;
}

export function registerRoutes(app: FastifyInstance, context: ModuleContext): void {
  const base = "/api/v1/projects/:projectId/research";

  app.get(`${base}/profile`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const profile = await repository(context).getProfile(identity, requireParam(request, "projectId"));
      if (!profile) throw new HttpError(404, "Research profile not found");
      return reply.send(profile);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.put(`${base}/profile`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).upsertProfile(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/profile/approve`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).approveProfile(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/workflow`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).listWorkflows(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/workflow/start`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository(context).startWorkflow(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/workflow/:workflowId/stages/:stageKey/run`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository(context).runStage(
          identity,
          requireParam(request, "projectId"),
          requireParam(request, "workflowId"),
          requireParam(request, "stageKey"),
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/workflow/:workflowId/checkpoints`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository(context).listCheckpoints(identity, requireParam(request, "projectId"), requireParam(request, "workflowId")),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/workflow/:workflowId/checkpoints/:checkpointId/decide`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository(context).decideCheckpoint(
          identity,
          requireParam(request, "projectId"),
          requireParam(request, "workflowId"),
          requireParam(request, "checkpointId"),
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/artifacts`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(
        await repository(context).listArtifactLinks(identity, requireParam(request, "projectId"), {
          workflowId: optionalString(q.workflow_id),
          artifactType: optionalString(q.artifact_type),
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/artifacts`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository(context).linkArtifact(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/claims`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const q = query(request);
      return reply.send(
        await repository(context).listClaimLinks(identity, requireParam(request, "projectId"), optionalString(q.workflow_id)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/claims`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository(context).createClaimLink(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch(`${base}/claims/:claimLinkId`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository(context).updateClaimLink(
          identity,
          requireParam(request, "projectId"),
          requireParam(request, "claimLinkId"),
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/screening-criteria`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).getScreeningCriteria(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.put(`${base}/screening-criteria`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await repository(context).upsertScreeningCriteria(identity, requireParam(request, "projectId"), jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/literature-matrix`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).getLiteratureMatrix(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/literature-matrix/rebuild`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).rebuildLiteratureMatrix(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/synthesis`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await repository(context).listSynthesisArtifacts(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/integrity/run`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await repository(context).runIntegrityCheck(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  // --- Experiments ---------------------------------------------------------

  app.get(`${base}/experiments/campaigns`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await experimentRepository(context).listCampaigns(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/experiments/campaigns`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await experimentRepository(context).createCampaign(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.patch(`${base}/experiments/campaigns/:campaignId`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await experimentRepository(context).updateCampaign(
          identity,
          requireParam(request, "projectId"),
          requireParam(request, "campaignId"),
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/experiments/campaigns/:campaignId/runs`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await experimentRepository(context).listRuns(identity, requireParam(request, "projectId"), requireParam(request, "campaignId")),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/experiments/campaigns/:campaignId/runs`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(
          await experimentRepository(context).createRun(
            identity,
            requireParam(request, "projectId"),
            requireParam(request, "campaignId"),
            jsonBody(request),
          ),
        );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/experiments/campaigns/:campaignId/runs/:runId/decide`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await experimentRepository(context).decideRun(
          identity,
          requireParam(request, "projectId"),
          requireParam(request, "campaignId"),
          requireParam(request, "runId"),
          jsonBody(request),
        ),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(`${base}/experiments/provenance`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await experimentRepository(context).listProvenance(identity, requireParam(request, "projectId")));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post(`${base}/experiments/provenance`, async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply
        .code(201)
        .send(await experimentRepository(context).createProvenance(identity, requireParam(request, "projectId"), jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
