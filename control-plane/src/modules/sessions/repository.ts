import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import type {
  MessageOut,
  SessionSummaryForContext,
  SessionOut,
  SessionPage,
} from "@agent-space/protocol" with { "resolution-mode": "import" };

export interface CreateSessionInput {
  workspaceId?: string | null;
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface AddMessageInput {
  role: string;
  content: string;
  metadata?: Record<string, unknown> | null;
}

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

interface SessionRow {
  id: string;
  space_id: string;
  user_id: string;
  workspace_id: string | null;
  title: string | null;
  status: string;
  created_at: unknown;
  updated_at: unknown;
}

interface MessageRow {
  id: string;
  session_id: string;
  space_id: string;
  user_id: string;
  role: string;
  content: string;
  metadata_json: unknown;
  created_at: unknown;
}

interface SessionSummaryRow {
  id: string;
  session_id: string;
  version: number;
  summary_text: string;
  condenser_version: string;
}

/**
 * TS repository for the public `sessions` command surface. Mirrors Python
 * `SessionService` scoping exactly: a session/message is only visible to its
 * owning user inside its own space, and only `status = 'active'` sessions are
 * listed (the same filter Python applies).
 *
 * Owns list/get/create sessions plus list/add messages when
 * `CONTROL_PLANE_SESSIONS_AUTHORITY=ts`, and serves the context-safe latest
 * session-summary read used by Python context assembly. Session `reflect` and
 * summary condense/create remain Python-owned.
 */
export class PgSessionRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgSessionRepository {
    if (!config.databaseUrl) {
      throw new Error("Session repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgSessionRepository(getDbPool(config.databaseUrl));
  }

  async listSessions(
    spaceId: string,
    userId: string,
    limit: number,
    offset: number,
  ): Promise<SessionPage> {
    const totalResult = await this.db.query<{ total: string | number }>(
      `SELECT count(s.id)::text AS total
         FROM sessions s
        WHERE s.space_id = $1
          AND s.user_id = $2
          AND s.status = 'active'`,
      [spaceId, userId],
    );
    const rowsResult = await this.db.query<SessionRow>(
      `${sessionSelectSql()}
        WHERE s.space_id = $1
          AND s.user_id = $2
          AND s.status = 'active'
        ORDER BY s.updated_at DESC
        LIMIT $3 OFFSET $4`,
      [spaceId, userId, limit, offset],
    );
    return {
      items: rowsResult.rows.map(sessionToOut),
      total: numberValue(totalResult.rows[0]?.total) ?? 0,
      limit,
      offset,
    };
  }

  async getSession(
    spaceId: string,
    userId: string,
    sessionId: string,
  ): Promise<SessionOut | null> {
    const result = await this.db.query<SessionRow>(
      `${sessionSelectSql()}
        WHERE s.id = $1
          AND s.space_id = $2
          AND s.user_id = $3
          AND s.status = 'active'`,
      [sessionId, spaceId, userId],
    );
    const row = result.rows[0];
    return row ? sessionToOut(row) : null;
  }

  async listMessages(
    spaceId: string,
    userId: string,
    sessionId: string,
    limit: number,
    offset: number,
  ): Promise<MessageOut[] | null> {
    // Mirror Python: 404 (null) when the session is not visible to this user in
    // this space, even if message rows exist.
    const session = await this.getSession(spaceId, userId, sessionId);
    if (!session) return null;
    const result = await this.db.query<MessageRow>(
      `SELECT m.id,
              m.session_id,
              m.space_id,
              m.user_id,
              m.role,
              m.content,
              m.metadata_json,
              m.created_at
         FROM messages m
        WHERE m.session_id = $1
        ORDER BY m.created_at ASC
        LIMIT $2 OFFSET $3`,
      [sessionId, limit, offset],
    );
    return result.rows.map(messageToOut);
  }

  async createSession(
    spaceId: string,
    userId: string,
    input: CreateSessionInput,
  ): Promise<SessionOut> {
    // `sessions` has no server-side defaults for id/status/timestamps (they are
    // Python-side model defaults), so TS must supply them explicitly or the
    // INSERT violates NOT NULL. Mirrors `SessionService.create_session`:
    // status='active', agent_id left null, created_at == updated_at.
    const now = new Date().toISOString();
    const result = await this.db.query<SessionRow>(
      `INSERT INTO sessions
         (id, space_id, user_id, workspace_id, title, status, metadata_json, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, 'active', $6::jsonb, $7, $7)
       RETURNING id, space_id, user_id, workspace_id, title, status, created_at, updated_at`,
      [
        randomUUID(),
        spaceId,
        userId,
        input.workspaceId ?? null,
        input.title ?? null,
        jsonParam(input.metadata),
        now,
      ],
    );
    return sessionToOut(result.rows[0]!);
  }

  async addMessage(
    spaceId: string,
    userId: string,
    sessionId: string,
    input: AddMessageInput,
  ): Promise<MessageOut | null> {
    // Mirror Python: only the owning user in the owning space may append; a
    // missing/invisible session is 404 (null), not an error.
    const session = await this.getSession(spaceId, userId, sessionId);
    if (!session) return null;
    const now = new Date().toISOString();
    // Atomic: insert the message and touch the session's updated_at in one
    // statement (data-modifying CTEs run to completion regardless of the final
    // SELECT), matching the single Python transaction.
    const result = await this.db.query<MessageRow>(
      `WITH inserted AS (
         INSERT INTO messages
           (id, space_id, session_id, user_id, role, content, metadata_json, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
         RETURNING id, space_id, session_id, user_id, role, content, metadata_json, created_at
       ), touched AS (
         UPDATE sessions SET updated_at = $8 WHERE id = $3 RETURNING 1
       )
       SELECT * FROM inserted`,
      [
        randomUUID(),
        spaceId,
        sessionId,
        userId,
        input.role,
        input.content,
        jsonParam(input.metadata),
        now,
      ],
    );
    return messageToOut(result.rows[0]!);
  }

  async getLatestSummaryForContext(
    spaceId: string,
    sessionId: string,
  ): Promise<SessionSummaryForContext | null> {
    const result = await this.db.query<SessionSummaryRow>(
      `SELECT ss.id,
              ss.session_id,
              ss.version,
              ss.summary_text,
              ss.condenser_version
         FROM session_summaries ss
        WHERE ss.space_id = $1
          AND ss.session_id = $2
          AND ss.status = 'active'
        ORDER BY ss.version DESC
        LIMIT 1`,
      [spaceId, sessionId],
    );
    const row = result.rows[0];
    return row
      ? {
          id: row.id,
          session_id: row.session_id,
          version: row.version,
          summary_text: row.summary_text,
          condenser_version: row.condenser_version,
        }
      : null;
  }
}

function jsonParam(value: Record<string, unknown> | null | undefined): string | null {
  return value === null || value === undefined ? null : JSON.stringify(value);
}

function sessionSelectSql(): string {
  return `SELECT s.id,
                 s.space_id,
                 s.user_id,
                 s.workspace_id,
                 s.title,
                 s.status,
                 s.created_at,
                 s.updated_at
            FROM sessions s`;
}

function sessionToOut(row: SessionRow): SessionOut {
  return {
    id: row.id,
    space_id: row.space_id,
    user_id: row.user_id,
    workspace_id: row.workspace_id,
    title: row.title,
    status: row.status,
    created_at: dateValue(row.created_at) ?? new Date(0).toISOString(),
    updated_at: dateValue(row.updated_at) ?? new Date(0).toISOString(),
  };
}

function messageToOut(row: MessageRow): MessageOut {
  return {
    id: row.id,
    session_id: row.session_id,
    space_id: row.space_id,
    user_id: row.user_id,
    role: row.role,
    content: row.content,
    metadata_json: recordOrNull(row.metadata_json),
    created_at: dateValue(row.created_at) ?? new Date(0).toISOString(),
  };
}

function recordOrNull(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function dateValue(value: unknown): string | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  return null;
}
