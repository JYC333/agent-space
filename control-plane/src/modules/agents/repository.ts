import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";

interface QueryResult<Row> {
  rows: Row[];
  rowCount: number | null;
}

interface Queryable {
  query<Row = Record<string, unknown>>(
    sql: string,
    params?: readonly unknown[],
  ): Promise<QueryResult<Row>>;
}

export interface AgentChatRecord {
  id: string;
  space_id: string;
  name: string | null;
  current_version_id: string | null;
}

export class PgAgentChatRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgAgentChatRepository {
    if (!config.databaseUrl) {
      throw new Error("Agent chat repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgAgentChatRepository(getDbPool(config.databaseUrl));
  }

  async getAgentForChat(
    spaceId: string,
    agentId: string,
  ): Promise<AgentChatRecord | null> {
    const result: QueryResult<AgentChatRecord> = await this.db.query<AgentChatRecord>(
      `SELECT id, space_id, name, current_version_id
         FROM agents
        WHERE space_id = $1 AND id = $2
        LIMIT 1`,
      [spaceId, agentId],
    );
    return result.rows[0] ?? null;
  }
}
