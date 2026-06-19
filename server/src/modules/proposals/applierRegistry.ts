import {
  MEMORY_COLUMNS,
  serializeMemoryRow,
  type MemoryRow,
} from "../memory/repository";
import type { ServerConfig } from "../../config";
import { registerKnowledgeProposalAppliers } from "../knowledge/proposalApplier";
import { registerTaskProposalAppliers } from "../tasks/proposalApplier";
import { registerWorkspaceProposalAppliers } from "../workspaces";
import {
  PgMemoryApplyRepository,
  type ApplyProposal,
} from "../memory/memoryApplyRepository";
import type { Queryable } from "./repository";
import type { ProposalAcceptResultType } from "@agent-space/protocol" with {
  "resolution-mode": "import",
};

export interface ProposalApplyContext {
  config: ServerConfig;
  db: Queryable;
  proposal: ApplyProposal;
  userId: string;
}

export interface ProposalApplyResult {
  result_type: ProposalAcceptResultType;
  result: Record<string, unknown>;
  rollback?: () => Promise<void>;
}

export class UnknownProposalApplierError extends Error {
  readonly statusCode = 422;

  constructor(readonly proposalType: string) {
    super(`unsupported proposal type: ${JSON.stringify(proposalType)}`);
    this.name = "UnknownProposalApplierError";
  }
}

export type ProposalApplier = (context: ProposalApplyContext) => Promise<ProposalApplyResult>;

export class ProposalApplierRegistry {
  private readonly appliers = new Map<string, ProposalApplier>();

  register(proposalType: string, applier: ProposalApplier): void {
    if (!proposalType) throw new Error("proposalType must be non-empty");
    if (this.appliers.has(proposalType)) {
      throw new Error(`an applier is already registered for proposal type ${proposalType}`);
    }
    this.appliers.set(proposalType, applier);
  }

  get(proposalType: string): ProposalApplier | null {
    return this.appliers.get(proposalType) ?? null;
  }

  registeredTypes(): ReadonlySet<string> {
    return new Set(this.appliers.keys());
  }

  async apply(context: ProposalApplyContext): Promise<ProposalApplyResult> {
    const applier = this.get(context.proposal.proposal_type);
    if (!applier) throw new UnknownProposalApplierError(context.proposal.proposal_type);
    return applier(context);
  }
}

export interface ProposalApplierContributor {
  applyProposalAppliers(registry: ProposalApplierRegistry): void;
}

export function createDefaultProposalApplierRegistry(
  contributor?: ProposalApplierContributor,
): ProposalApplierRegistry {
  const registry = new ProposalApplierRegistry();
  for (const proposalType of ["memory_create", "memory_update", "memory_archive"]) {
    registry.register(proposalType, applyMemoryProposal);
  }
  registerKnowledgeProposalAppliers(registry);
  registerTaskProposalAppliers(registry);
  registerWorkspaceProposalAppliers(registry);
  contributor?.applyProposalAppliers(registry);
  return registry;
}

async function applyMemoryProposal(context: ProposalApplyContext): Promise<ProposalApplyResult> {
  const applied = await new PgMemoryApplyRepository(context.db).acceptAndApply(
    context.proposal,
    context.userId,
  );
  const row = await context.db.query<MemoryRow>(
    `SELECT ${MEMORY_COLUMNS} FROM memory_entries WHERE id = $1`,
    [applied.memoryId],
  );
  const memory = row.rows[0];
  if (!memory) throw new Error("applied memory row not found after acceptAndApply");
  return {
    result_type: "memory_entry",
    result: { memory: serializeMemoryRow(memory, context.userId) },
  };
}
