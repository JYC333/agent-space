import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import type {
  MemoryOut,
  MemoryPage,
} from "@agent-space/protocol" with { "resolution-mode": "import" };
import {
  canReadMemory,
  summaryOnlyRedactContent,
  type MemoryAuthFields,
} from "./memoryReadAuth";

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

export interface MemoryListFilters {
  scope?: string | null;
  namespace?: string | null;
  memoryType?: string | null;
  status?: string | null;
  workspaceId?: string | null;
  projectId?: string | null;
  includeSystem?: boolean;
  limit: number;
  offset: number;
}

export interface MemorySearchFilters {
  query: string;
  scope?: string | null;
  namespace?: string | null;
  memoryType?: string | null;
  workspaceId?: string | null;
  includeSystem?: boolean;
  limit: number;
}

/**
 * Whether `scope=system` seed memories (system policy rows) should be visible.
 * The user-facing read surface hides them by default so they do not show up as
 * user memory hits; an explicit `scope=system` filter or `includeSystem` opts in.
 */
function includeSystemScopeFor(
  filters: { scope?: string | null; includeSystem?: boolean },
): boolean {
  return filters.includeSystem === true || filters.scope === "system";
}

/** Raised when a filter references a project that is not in the space. */
export class MemoryReadValidationError extends Error {}

// All columns the read model needs: the MemoryOut wire fields plus the columns
// canReadMemory inspects. SOURCE OF TRUTH: the Python MemoryEntry ORM model.
export const MEMORY_COLUMNS = `id, space_id, subject_user_id, owner_user_id, workspace_id,
  scope_type, namespace, memory_type, title, content, status, visibility,
  sensitivity_level, selected_user_ids, last_confirmed_at, confidence, importance,
  source_id, created_by, created_at, updated_at, deleted_at, version, tags,
  memory_layer, memory_kind, source_trust, created_from_proposal_id,
  root_memory_id, supersedes_memory_id, project_id`;

export interface MemoryRow extends MemoryAuthFields {
  id: string;
  subject_user_id: string | null;
  namespace: string | null;
  memory_type: string;
  title: string | null;
  content: string | null;
  status: string;
  last_confirmed_at: unknown;
  confidence: number | string;
  importance: number | string;
  source_id: string | null;
  created_by: string | null;
  created_at: unknown;
  updated_at: unknown;
  version: number | string;
  tags: unknown;
  memory_layer: string | null;
  memory_kind: string | null;
  source_trust: string | null;
  created_from_proposal_id: string | null;
  root_memory_id: string | null;
  supersedes_memory_id: string | null;
  project_id: string | null;
}

/**
 * TS memory **read** model (Stage 6 slices 5 + 7a). Mirrors Python `MemoryStore`
 * list/get/search exactly: a scoped SQL query loads candidate rows, then
 * `canReadMemory` filters them in app code (so pagination is applied to the
 * readable set, not the raw rows), then rows are serialized with summary-only
 * redaction.
 *
 * Read-access logging (slice 7a, restoring the slice 5/6 deferral): `get` writes
 * one `explicit_read` trace and `search` writes one `search_hit` trace per
 * returned row into `memory_access_logs`, and bumps the accessed memory's
 * `access_count` / `last_accessed_at` (column-scoped UPDATE; the read role never
 * gets table-wide `memory_entries` write). `list` is never logged — matching the
 * Python `/memory` route (`MemoryStore.log_explicit_read` / `log_reads_batch`).
 */
export class PgMemoryReadRepository {
  constructor(private readonly db: Queryable) {}

  static fromConfig(config: ControlPlaneConfig): PgMemoryReadRepository {
    if (!config.databaseUrl) {
      throw new Error("Memory read repository requires CONTROL_PLANE_DATABASE_URL");
    }
    return new PgMemoryReadRepository(getDbPool(config.databaseUrl));
  }

  async list(
    spaceId: string,
    userId: string,
    filters: MemoryListFilters,
  ): Promise<MemoryPage> {
    if (filters.projectId) {
      await this.assertProjectInSpace(spaceId, filters.projectId);
    }
    const where = [`space_id = $1`, `deleted_at IS NULL`];
    const params: unknown[] = [spaceId];
    const status = filters.status ?? "active";
    if (status) {
      params.push(status);
      where.push(`status = $${params.length}`);
    }
    if (filters.scope) {
      params.push(filters.scope);
      where.push(`scope_type = $${params.length}`);
    }
    if (filters.namespace) {
      params.push(filters.namespace);
      where.push(`namespace = $${params.length}`);
    }
    if (filters.memoryType) {
      params.push(filters.memoryType);
      where.push(`memory_type = $${params.length}`);
    }
    if (filters.projectId) {
      params.push(filters.projectId);
      where.push(`project_id = $${params.length}`);
    }
    const result = await this.db.query<MemoryRow>(
      `SELECT ${MEMORY_COLUMNS} FROM memory_entries
        WHERE ${where.join(" AND ")}
        ORDER BY importance DESC, updated_at DESC`,
      params,
    );
    // System-scope seed memories are hidden unless explicitly opted in.
    const includeSystem = includeSystemScopeFor(filters);
    const readable = result.rows.filter((row) =>
      canReadMemory(row, {
        userId,
        spaceId,
        workspaceId: filters.workspaceId ?? null,
        includeSystemScope: includeSystem && row.scope_type === "system",
      }),
    );
    const items = readable
      .slice(filters.offset, filters.offset + filters.limit)
      .map((row) => this.serialize(row, userId));
    return {
      items,
      total: readable.length,
      limit: filters.limit,
      offset: filters.offset,
    };
  }

  async get(
    spaceId: string,
    userId: string,
    memoryId: string,
    workspaceId: string | null,
  ): Promise<MemoryOut | null> {
    const result = await this.db.query<MemoryRow>(
      `SELECT ${MEMORY_COLUMNS} FROM memory_entries
        WHERE id = $1 AND space_id = $2 AND deleted_at IS NULL`,
      [memoryId, spaceId],
    );
    const row = result.rows[0];
    if (!row) return null;
    const includeSystemScope = row.scope_type === "system";
    if (
      !canReadMemory(row, { userId, spaceId, workspaceId, includeSystemScope })
    ) {
      return null;
    }
    await this.recordReads([row.id], spaceId, userId, "explicit_read", null);
    return this.serialize(row, userId);
  }

  async search(
    spaceId: string,
    userId: string,
    filters: MemorySearchFilters,
  ): Promise<MemoryOut[]> {
    const where = [
      `space_id = $1`,
      `status = 'active'`,
      `deleted_at IS NULL`,
      `(title ILIKE $2 OR content ILIKE $2)`,
    ];
    const params: unknown[] = [spaceId, `%${filters.query}%`];
    if (filters.scope) {
      params.push(filters.scope);
      where.push(`scope_type = $${params.length}`);
    }
    if (filters.namespace) {
      params.push(filters.namespace);
      where.push(`namespace = $${params.length}`);
    }
    if (filters.memoryType) {
      params.push(filters.memoryType);
      where.push(`memory_type = $${params.length}`);
    }
    const result = await this.db.query<MemoryRow>(
      `SELECT ${MEMORY_COLUMNS} FROM memory_entries
        WHERE ${where.join(" AND ")}
        ORDER BY importance DESC, confidence DESC`,
      params,
    );
    // System-scope seed memories are hidden from search unless explicitly
    // opted in (an `include_system` flag or an explicit `scope=system` filter).
    const includeSystem = includeSystemScopeFor(filters);
    const readable = result.rows.filter((row) =>
      canReadMemory(row, {
        userId,
        spaceId,
        workspaceId: filters.workspaceId ?? null,
        includeSystemScope: includeSystem && row.scope_type === "system",
      }),
    );
    const returned = readable.slice(0, filters.limit);
    await this.recordReads(
      returned.map((row) => row.id),
      spaceId,
      userId,
      "search_hit",
      "memory search",
    );
    return returned.map((row) => this.serialize(row, userId));
  }

  /**
   * Append `memory_access_logs` traces for the returned rows and bump each
   * memory's `access_count` / `last_accessed_at`. Mirrors Python
   * `record_memory_access`: one trace row per read, viewer user only (no
   * agent/run), and a column-scoped counter UPDATE. `last_retrieved_at` is left
   * untouched — Python only sets it for `context_injection`, not these paths.
   */
  private async recordReads(
    memoryIds: readonly string[],
    spaceId: string,
    userId: string,
    accessType: "explicit_read" | "search_hit",
    reason: string | null,
  ): Promise<void> {
    if (memoryIds.length === 0) return;
    const now = new Date().toISOString();

    const logCols =
      "id, space_id, memory_id, user_id, agent_id, run_id, access_type, reason, accessed_at";
    const logGroups: string[] = [];
    const logParams: unknown[] = [];
    for (const memoryId of memoryIds) {
      const base = logParams.length;
      logGroups.push(
        `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, NULL, NULL, ` +
          `$${base + 5}, $${base + 6}, $${base + 7})`,
      );
      logParams.push(randomUUID(), spaceId, memoryId, userId, accessType, reason, now);
    }
    await this.db.query(
      `INSERT INTO memory_access_logs (${logCols}) VALUES ${logGroups.join(", ")}`,
      logParams,
    );

    const idPlaceholders = memoryIds.map((_, i) => `$${i + 3}`).join(", ");
    await this.db.query(
      `UPDATE memory_entries
          SET access_count = COALESCE(access_count, 0) + 1,
              last_accessed_at = $1
        WHERE space_id = $2 AND id IN (${idPlaceholders})`,
      [now, spaceId, ...memoryIds],
    );
  }

  private async assertProjectInSpace(spaceId: string, projectId: string): Promise<void> {
    const result = await this.db.query(
      `SELECT 1 FROM projects
        WHERE id = $1 AND space_id = $2 AND deleted_at IS NULL`,
      [projectId, spaceId],
    );
    if ((result.rowCount ?? result.rows.length) === 0) {
      throw new MemoryReadValidationError(
        `project_id '${projectId}' not found in space '${spaceId}' or has been deleted`,
      );
    }
  }

  private serialize(row: MemoryRow, viewerUserId: string): MemoryOut {
    return serializeMemoryRow(row, viewerUserId);
  }
}

/** Serialize a memory row to the `MemoryOut` wire shape with summary-only
 * redaction (shared by the read model and the apply accept-result builder). */
export function serializeMemoryRow(row: MemoryRow, viewerUserId: string): MemoryOut {
  const redact = summaryOnlyRedactContent(row, viewerUserId);
  return {
    id: row.id,
      space_id: row.space_id,
      subject_user_id: row.subject_user_id,
      owner_user_id: row.owner_user_id,
      workspace_id: row.workspace_id,
      scope: row.scope_type ?? "",
      namespace: row.namespace,
      type: row.memory_type,
      title: row.title,
      content: redact ? null : row.content,
      status: row.status,
      visibility: row.visibility ?? "private",
      sensitivity_level: row.sensitivity_level ?? "normal",
      selected_user_ids: normalizeArray(row.selected_user_ids),
      last_confirmed_at: isoOrNull(row.last_confirmed_at),
      confidence: numeric(row.confidence),
      importance: numeric(row.importance),
      source_id: row.source_id,
      created_by: row.created_by,
      created_at: isoOrNull(row.created_at) ?? new Date(0).toISOString(),
      updated_at: isoOrNull(row.updated_at) ?? new Date(0).toISOString(),
      deleted_at: isoOrNull(row.deleted_at),
      version: Number(row.version),
      tags: normalizeArray(row.tags),
      memory_layer: row.memory_layer,
      memory_kind: row.memory_kind,
      source_trust: row.source_trust,
      created_from_proposal_id: row.created_from_proposal_id,
      root_memory_id: row.root_memory_id,
      supersedes_memory_id: row.supersedes_memory_id,
      project_id: row.project_id,
    };
}

function numeric(value: number | string): number {
  return typeof value === "number" ? value : Number(value);
}

function normalizeArray(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

function isoOrNull(value: unknown): string | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }
  return null;
}
