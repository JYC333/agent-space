import type {
  AgentSpacePlugin,
  PluginHostContext,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { FastifyInstance } from "fastify";
import { registerDiaryRoutes } from "./routes";
import { JOB_TYPE_DIARY_REFLECTION, buildDiaryReflectionHandler } from "./jobs";
import { buildDiaryDailyPromptTask } from "./scheduler";
import { diaryMigrations } from "./schema";
import {
  DIARY_PLUGIN_ID,
  DIARY_PLUGIN_VERSION,
} from "./manifest";

export const diaryPlugin: AgentSpacePlugin = {
  id: DIARY_PLUGIN_ID,
  version: DIARY_PLUGIN_VERSION,
  migrations: diaryMigrations,

  activate(ctx: PluginHostContext) {
    const fastify = ctx.fastify as FastifyInstance;
    const db = ctx.db;

    registerDiaryRoutes(fastify, db, ctx);
    ctx.jobs.register(
      JOB_TYPE_DIARY_REFLECTION,
      buildDiaryReflectionHandler(db, DIARY_PLUGIN_ID),
    );
    ctx.scheduler.register(buildDiaryDailyPromptTask(db, DIARY_PLUGIN_ID));
    return { activated: true };
  },
};
