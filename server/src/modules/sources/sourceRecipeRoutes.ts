import type { FastifyInstance } from "fastify";
import type { ModuleContext } from "../../gateway/routeRegistry";
import {
  dbPool,
  jsonBody,
  page,
  parsePage,
  params,
  query,
  resolveIdentity,
  sendRouteError,
} from "../routeUtils/common";
import { enforceSources } from "./enforceSources";
import { SourceRecipeDryRunService } from "./sourceRecipes/recipeDryRunService";
import { SourceRecipeCreateService } from "./sourceRecipes/recipeCreateService";
import { SourceRecipePipelineBridgeService } from "./sourceRecipes/pipelineBridgeService";
import { listSourceRecipePrimitives } from "./sourceRecipes/primitiveRegistry";
import {
  getSourceRecipeVersion,
  listSourceRecipeVersions,
  recipeVersionOut,
} from "./sourceRecipes/recipeVersionStore";

/** Level 2 Source recipe routes (plan/create, dry-run preview, activation, and the recipe-version read model), split out of routes.ts like customSourceRoutes.ts. */
export function registerSourceRecipeRoutes(app: FastifyInstance, context: ModuleContext): void {
  const dryRunService = () => new SourceRecipeDryRunService(dbPool(context.config), context.config);
  const createService = () => new SourceRecipeCreateService(dbPool(context.config), context.config);
  const pipelineBridgeService = () => new SourceRecipePipelineBridgeService(dbPool(context.config), context.config);

  app.get("/api/v1/sources/source-recipes/primitives", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    return reply.send({ primitives: listSourceRecipePrimitives() });
  });

  app.post("/api/v1/sources/source-recipes/plan", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "source.source_recipe_create", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await createService().planSource(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/source-recipes", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const gate = await enforceSources(context, identity, "source.source_recipe_create", "source_connection");
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(await createService().createSource(identity, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/source-recipes/:connectionId/activate", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.source_recipe_activate", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await createService().activateRecipe(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/custom-sources/:connectionId/bridge-pipeline", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.source_recipe_create", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.code(201).send(
        await pipelineBridgeService().bridgePipelineHandler(identity, connectionId, jsonBody(request)),
      );
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.post("/api/v1/sources/source-recipes/:connectionId/dry-run", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const connectionId = params(request).connectionId ?? "";
      const gate = await enforceSources(context, identity, "source.source_recipe_dry_run", "source_connection", connectionId);
      if (gate.blocked) return reply.code(403).send(gate.reply403);
      return reply.send(await dryRunService().dryRunRecipeVersion(identity, connectionId, jsonBody(request)));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get("/api/v1/sources/connections/:connectionId/recipe-versions", async (request, reply) => {
    const identity = await resolveIdentity(context.config, request, reply);
    if (!identity) return reply;
    try {
      const { limit, offset } = parsePage(query(request));
      const listed = await listSourceRecipeVersions(
        dbPool(context.config),
        identity.spaceId,
        params(request).connectionId ?? "",
        { limit, offset },
      );
      return reply.send(page(listed.rows.map(recipeVersionOut), listed.total, limit, offset));
    } catch (error) {
      return sendRouteError(reply, error);
    }
  });

  app.get(
    "/api/v1/sources/connections/:connectionId/recipe-versions/:versionId",
    async (request, reply) => {
      const identity = await resolveIdentity(context.config, request, reply);
      if (!identity) return reply;
      try {
        const p = params(request);
        const version = await getSourceRecipeVersion(
          dbPool(context.config),
          identity.spaceId,
          p.connectionId ?? "",
          p.versionId ?? "",
        );
        if (!version) return reply.code(404).send({ detail: "Recipe version not found" });
        return reply.send(recipeVersionOut(version));
      } catch (error) {
        return sendRouteError(reply, error);
      }
    },
  );
}
