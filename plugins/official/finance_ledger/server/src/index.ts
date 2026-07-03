import type {
  AgentSpacePlugin,
  PluginHostContext,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import type { FastifyInstance } from "fastify";
import { registerFinanceLedgerProposalAppliers } from "./proposalAppliers";
import { registerFinanceLedgerRoutes } from "./routes";
import { financeLedgerMigrations } from "./schema";
import {
  FINANCE_LEDGER_PLUGIN_ID,
  FINANCE_LEDGER_PLUGIN_VERSION,
} from "./manifest";

export const financeLedgerPlugin: AgentSpacePlugin = {
  id: FINANCE_LEDGER_PLUGIN_ID,
  version: FINANCE_LEDGER_PLUGIN_VERSION,
  migrations: financeLedgerMigrations,

  activate(ctx: PluginHostContext) {
    registerFinanceLedgerRoutes(ctx.fastify as FastifyInstance, ctx.db, ctx);
    registerFinanceLedgerProposalAppliers(ctx);
    return { activated: true };
  },
};
