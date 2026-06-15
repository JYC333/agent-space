/**
 * Stage 6 slice 7b flip: apply a gated memory proposal in one TS transaction.
 *
 * The accept route, when `CONTROL_PLANE_MEMORY_APPLY_AUTHORITY=ts` and the
 * proposal is a memory_* type, first calls the Python memory-apply-gate port
 * (validation + proposal.apply policy gate + durable ALLOW audit), then calls
 * this to run the active-memory writes + accept state transition atomically. The
 * applied memory is re-read and serialized to the `MemoryOut` the accept result
 * envelope returns.
 */

import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import {
  PgMemoryApplyRepository,
  type ApplyProposal,
} from "./memoryApplyRepository";
import { MEMORY_COLUMNS, serializeMemoryRow, type MemoryRow } from "./repository";
import type { MemoryApplyGateResult } from "../proposals/pythonProposalPorts";
import type { MemoryOut } from "@agent-space/protocol" with { "resolution-mode": "import" };

export interface MemoryAcceptApplied {
  memoryId: string;
  supersededMemoryId: string | null;
  memory: MemoryOut;
}

export async function applyGatedMemoryProposal(
  config: ControlPlaneConfig,
  gate: MemoryApplyGateResult,
  userId: string,
): Promise<MemoryAcceptApplied> {
  if (!config.databaseUrl) {
    throw new Error("Memory apply requires CONTROL_PLANE_DATABASE_URL");
  }
  const proposal: ApplyProposal = {
    id: gate.id,
    space_id: gate.space_id,
    proposal_type: gate.proposal_type,
    title: gate.title,
    payload_json: gate.payload_json,
    workspace_id: gate.workspace_id,
    created_by_user_id: gate.created_by_user_id,
    created_by_run_id: gate.created_by_run_id,
  };

  const client = await getDbPool(config.databaseUrl).connect();
  try {
    await client.query("BEGIN");
    const result = await new PgMemoryApplyRepository(client).acceptAndApply(proposal, userId);
    const memRes = await client.query<MemoryRow>(
      `SELECT ${MEMORY_COLUMNS} FROM memory_entries WHERE id = $1`,
      [result.memoryId],
    );
    const row = memRes.rows[0];
    if (!row) throw new Error("applied memory row not found after acceptAndApply");
    await client.query("COMMIT");
    return {
      memoryId: result.memoryId,
      supersededMemoryId: result.supersededMemoryId,
      memory: serializeMemoryRow(row, userId),
    };
  } catch (err) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw err;
  } finally {
    client.release();
  }
}
