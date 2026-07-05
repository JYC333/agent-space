import type {
  AgentSpacePlugin,
  PluginHostContext,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { FastifyInstance } from "fastify";
import {
  RESEARCH_ATLAS_PLUGIN_ID,
  RESEARCH_ATLAS_PLUGIN_VERSION,
} from "./manifest";
import { registerResearchAtlasJobs } from "./jobs";
import { registerResearchAtlasProposalAppliers } from "./proposalAppliers";
import { registerResearchAtlasRoutes } from "./routes";
import { registerResearchAtlasScheduler } from "./scheduler";
import { researchAtlasMigrations } from "./schema";

export const researchAtlasPlugin: AgentSpacePlugin = {
  id: RESEARCH_ATLAS_PLUGIN_ID,
  version: RESEARCH_ATLAS_PLUGIN_VERSION,
  migrations: researchAtlasMigrations,

  activate(ctx: PluginHostContext) {
    registerResearchAtlasRoutes(ctx.fastify as FastifyInstance, ctx.db, ctx);
    registerResearchAtlasJobs(ctx);
    registerResearchAtlasScheduler(ctx);
    registerResearchAtlasProposalAppliers(ctx);
    return { activated: true };
  },
};
