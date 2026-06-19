import type {
  AgentSpacePlugin,
  PluginHostContext,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { FastifyInstance } from "fastify";
import { registerDairyRoutes } from "./routes";
import { JOB_TYPE_DAIRY_REFLECTION, buildDairyReflectionHandler } from "./jobs";
import { buildDairyDailyPromptTask } from "./scheduler";
import { dairyMigrations } from "./schema";
import {
  DAIRY_PLUGIN_ID,
  DAIRY_PLUGIN_VERSION,
} from "./manifest";

export const dairyPlugin: AgentSpacePlugin = {
  id: DAIRY_PLUGIN_ID,
  version: DAIRY_PLUGIN_VERSION,
  migrations: dairyMigrations,

  activate(ctx: PluginHostContext) {
    const fastify = ctx.fastify as FastifyInstance;
    const db = ctx.db;

    registerDairyRoutes(fastify, db, ctx);
    ctx.jobs.register(
      JOB_TYPE_DAIRY_REFLECTION,
      buildDairyReflectionHandler(db, DAIRY_PLUGIN_ID),
    );
    ctx.scheduler.register(buildDairyDailyPromptTask(db, DAIRY_PLUGIN_ID));
    return { activated: true };
  },
};
