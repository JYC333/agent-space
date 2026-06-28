import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import type { ChatContextCandidateItem } from "@agent-space/protocol" with { "resolution-mode": "import" };

export interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

export interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

export interface ChatSnapshotPersistInput {
  contextSnapshotId: string;
  spaceId: string;
  runId: string;
  userId: string;
  agentId?: string | null;
  tokenEstimate: number;
  requestJson: Record<string, unknown>;
  retrievalTraceJson?: Record<string, unknown> | null;
  tokenBudgetJson?: Record<string, unknown> | null;
  items: readonly ChatContextCandidateItem[];
}

/**
 * server persistence for chat-path context snapshots.
 *
 * The run already owns an empty `ContextSnapshot` (created by run creation), so
 * this UPDATEs `token_estimate` + `request_json` on that row
 * and INSERTs the selected `context_snapshot_items`. It never creates snapshots
 * (run creation owns that). Selected chat memory items are also access-logged in
 * `memory_access_logs`, matching the full-run ContextBuilder audit contract.
 */
export class PgContextSnapshotRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ServerConfig): PgContextSnapshotRepository {
    if (!config.databaseUrl) {
      throw new Error(
        "Context snapshot repository requires SERVER_DATABASE_URL",
      );
    }
    return new PgContextSnapshotRepository(getDbPool(config.databaseUrl));
  }

  async persistChatSnapshot(input: ChatSnapshotPersistInput): Promise<void> {
    // Update the run's existing snapshot row (space-scoped). Other audit fields
    // stay as create-run left them.
    await this.db.query(
      `UPDATE context_snapshots
          SET token_estimate = $1,
              request_json = $2::jsonb,
              retrieval_trace_json = COALESCE($5::jsonb, retrieval_trace_json),
              token_budget_json = COALESCE($6::jsonb, token_budget_json)
        WHERE id = $3
          AND space_id = $4`,
      [
        input.tokenEstimate,
        JSON.stringify(input.requestJson),
        input.contextSnapshotId,
        input.spaceId,
        jsonOrNull(input.retrievalTraceJson),
        jsonOrNull(input.tokenBudgetJson),
      ],
    );

    if (input.items.length === 0) return;

    // Append per-item audit rows. the server supplies id/created_at/metadata_json
    // explicitly to avoid relying on implicit DB defaults.
    const now = new Date().toISOString();
    const columns =
      "id, context_snapshot_id, item_type, item_id, title, excerpt, score, reason, token_count, metadata_json, created_at";
    const valueGroups: string[] = [];
    const params: unknown[] = [];
    input.items.forEach((item) => {
      const base = params.length;
      valueGroups.push(
        `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, ` +
          `$${base + 6}, $${base + 7}, $${base + 8}, $${base + 9}, $${base + 10}::jsonb, $${base + 11})`,
      );
      params.push(
        randomUUID(),
        input.contextSnapshotId,
        item.item_type,
        item.item_id ?? null,
        item.title ?? null,
        item.excerpt ?? null,
        item.score ?? null,
        item.reason ?? null,
        item.token_count ?? null,
        JSON.stringify(item.metadata ?? {}),
        now,
      );
    });

    await this.db.query(
      `INSERT INTO context_snapshot_items (${columns})
       VALUES ${valueGroups.join(", ")}`,
      params,
    );
    await this.recordChatMemoryAccess(input, now);
  }

  private async recordChatMemoryAccess(input: ChatSnapshotPersistInput, now: string): Promise<void> {
    const memoryIds = Array.from(new Set(
      input.items
        .filter((item) => item.item_type === "memory" && typeof item.item_id === "string" && item.item_id)
        .map((item) => item.item_id as string),
    ));
    if (memoryIds.length === 0) return;

    const columns = "id, space_id, memory_id, user_id, agent_id, run_id, access_type, reason, accessed_at";
    const valueGroups: string[] = [];
    const params: unknown[] = [];
    for (const memoryId of memoryIds) {
      const base = params.length;
      valueGroups.push(
        `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, ` +
          `$${base + 6}, 'context_injection', $${base + 7}, $${base + 8})`,
      );
      params.push(
        randomUUID(),
        input.spaceId,
        memoryId,
        input.userId,
        input.agentId ?? null,
        input.runId,
        `chat context snapshot ${input.contextSnapshotId}`,
        now,
      );
    }
    await this.db.query(
      `INSERT INTO memory_access_logs (${columns})
       VALUES ${valueGroups.join(", ")}`,
      params,
    );
    await this.db.query(
      `UPDATE memory_entries
          SET access_count = COALESCE(access_count, 0) + 1,
              last_accessed_at = $3,
              last_retrieved_at = $3
        WHERE space_id = $1
          AND id = ANY($2::varchar[])`,
      [input.spaceId, memoryIds, now],
    );
  }
}

function jsonOrNull(value: Record<string, unknown> | null | undefined): string | null {
  return value === null || value === undefined ? null : JSON.stringify(value);
}
