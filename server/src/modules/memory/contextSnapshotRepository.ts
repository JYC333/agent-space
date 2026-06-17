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
  tokenEstimate: number;
  requestJson: Record<string, unknown>;
  items: readonly ChatContextCandidateItem[];
}

/**
 * server persistence for chat-path context snapshots.
 *
 * The run already owns an empty `ContextSnapshot` (created by run creation), so
 * this UPDATEs `token_estimate` + `request_json` on that row
 * and INSERTs the selected `context_snapshot_items`. It never creates snapshots
 * (run creation owns that) and writes no other context tables.
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
              request_json = $2::jsonb
        WHERE id = $3
          AND space_id = $4`,
      [
        input.tokenEstimate,
        JSON.stringify(input.requestJson),
        input.contextSnapshotId,
        input.spaceId,
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
  }
}
