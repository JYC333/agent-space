import type { ProposalApplierRegistry } from "../proposals/applierRegistry";
import { requiredString } from "../routeUtils/common";
import { SourceConnectionService } from "./sourceConnectionService";

export function registerSourceConnectionProposalAppliers(registry: ProposalApplierRegistry): void {
  registry.register("source_connection_create", async (context) => {
    const { db, proposal } = context;
    const connectionId = requiredString(proposal.payload_json?.source_connection_id, "source_connection_id");
    const expectedUpdatedAt = requiredString(proposal.payload_json?.draft_updated_at, "draft_updated_at");
    const current = await db.query<{ updated_at: unknown }>(`SELECT updated_at FROM source_connections WHERE id=$1 AND space_id=$2 AND status='paused' AND deleted_at IS NULL`, [connectionId, proposal.space_id]);
    if (!current.rows[0] || new Date(String(current.rows[0].updated_at)).toISOString() !== new Date(expectedUpdatedAt).toISOString()) {
      throw new Error("Source connection draft changed after proposal creation");
    }
    const connection = await new SourceConnectionService(db, context.config).activate({ spaceId: proposal.space_id, userId: context.userId }, connectionId);
    return { result_type: "source_connection", result: { connection } };
  });
}
