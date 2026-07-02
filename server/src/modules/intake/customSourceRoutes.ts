import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  jsonBody,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { requireInstanceAdmin } from "../routeUtils/access";
import { enforceIntake } from "./enforceIntake";
import { PgCustomSourceHandlerRepository } from "./customSourceHandlerRepository";
import { CustomSourceCreateFlowService } from "./customSourceCreateFlowService";
import { CustomSourceRepairService } from "./customSourceRepairService";
import { CustomSourceCredentialService } from "./customSourceCredentialService";
import { loadProtocol } from "../providers/protocolRuntime";

/** Custom Source create-flow (Phase 5), repair/rollback (Phase 9), credentials (Phase 10), and read-model (Phase 2) routes, split out of routes.ts per its own size. */
export function registerCustomSourceRoutes(app: FastifyInstance, context: ModuleContext): void {
  const customSourceRepository = () =>
    new PgCustomSourceHandlerRepository(dbPool(context.config), context.config);
  const customSourceCreateFlow = () =>
    new CustomSourceCreateFlowService(dbPool(context.config), context.config);
  const customSourceRepair = () => new CustomSourceRepairService(dbPool(context.config), context.config);
  const customSourceCredentials = () => new CustomSourceCredentialService(dbPool(context.config), context.config);

  app.post("/api/v1/intake/custom-sources/drafts", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.custom_source_create", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await customSourceCreateFlow().createDraft(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-sources/:connectionId/generate-handler", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.custom_source_generate", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply
        .code(201)
        .send(await customSourceCreateFlow().generateHandler(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-sources/:connectionId/test-handler", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.custom_source_test", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await customSourceCreateFlow().testHandler(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-sources/:connectionId/activate", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.custom_source_activate", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await customSourceCreateFlow().activateHandler(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-sources/:connectionId/repair", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.custom_source_repair", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await customSourceRepair().repairHandler(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-sources/:connectionId/rollback", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceIntake(context, identity, "intake.custom_source_rollback", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await customSourceRepair().rollbackHandler(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/intake/custom-source-credentials", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.custom_source_credential_create", "custom_source_credential");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      const protocol = await loadProtocol();
      const payload = protocol.CustomSourceCredentialCreateSchema.parse(jsonBody(request));
      return reply.code(201).send(await customSourceCredentials().create(identity, payload));
    } catch (error) {
      if (error instanceof Error && "issues" in error) {
        return reply.code(422).send({ detail: "Invalid Custom Source credential" });
      }
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/custom-source-credentials", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await customSourceCredentials().list(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/custom-source-settings/space", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(await customSourceRepository().getSpacePolicy(identity));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/custom-source-settings/instance", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireInstanceAdmin(context.config, identity, reply))) return reply;
    try {
      return reply.send(await customSourceRepository().getInstanceRunnerSettings());
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.put("/api/v1/intake/custom-source-settings/instance", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    if (!(await requireInstanceAdmin(context.config, identity, reply))) return reply;
    try {
      const protocol = await loadProtocol();
      const payload = protocol.CustomSourceInstanceRunnerSettingsUpdateSchema.parse(jsonBody(request));
      return reply.send(await customSourceRepository().updateInstanceRunnerSettings(identity, payload));
    } catch (error) {
      if (error instanceof Error && "issues" in error) {
        return reply.code(422).send({ detail: "Invalid Custom Source runner settings" });
      }
      return sendRouteError(reply, error);
    }
  });

  app.put("/api/v1/intake/custom-source-settings/space", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceIntake(context, identity, "intake.custom_source_settings_update", "custom_source_settings");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      const protocol = await loadProtocol();
      const payload = protocol.CustomSourceSpacePolicyUpdateSchema.parse(jsonBody(request));
      return reply.send(await customSourceRepository().updateSpacePolicy(identity, payload));
    } catch (error) {
      if (error instanceof Error && "issues" in error) {
        return reply.code(422).send({ detail: "Invalid Custom Source settings" });
      }
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/connections/:connectionId/custom-source", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      return reply.send(
        await customSourceRepository().getHandlerSummary(identity, params(request).connectionId ?? ""),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/connections/:connectionId/handler-versions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request));
      return reply.send(
        await customSourceRepository().listHandlerVersions(identity, params(request).connectionId ?? "", {
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(
    "/api/v1/intake/connections/:connectionId/handler-versions/:versionId",
    async (request, reply) => {
      const identity = await resolveIdentity(context.config, request, reply);
      if (!identity) return reply;
      try {
        const p = params(request);
        const version = await customSourceRepository().getHandlerVersion(
          identity,
          p.connectionId ?? "",
          p.versionId ?? "",
        );
        if (!version) return reply.code(404).send({ detail: "Handler version not found" });
        return reply.send(version);
      } catch (error) {
        return sendRouteError(reply, error);
      }
    },
  );

  app.get("/api/v1/intake/connections/:connectionId/handler-runs", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request));
      return reply.send(
        await customSourceRepository().listHandlerRuns(identity, params(request).connectionId ?? "", {
          limit,
          offset,
        }),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/intake/connections/:connectionId/handler-runs/:runId", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const p = params(request);
      const run = await customSourceRepository().getHandlerRun(identity, p.connectionId ?? "", p.runId ?? "");
      if (!run) return reply.code(404).send({ detail: "Handler run not found" });
      return reply.send(run);
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });
}
