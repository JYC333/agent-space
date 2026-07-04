import type { Queryable } from "../routeUtils/common";

/**
 * "New since last successful run" support for project-bound agent_run
 * automations. The cursor is a (created_at, id) watermark over intake_items,
 * committed on run success (see runs/finalizationService + intakeCursor.ts);
 * failed runs do not advance it, so the next fire re-reads the same delta.
 */

export interface IntakeWatermark {
  created_at: string;
  id: string;
}

export interface IntakeDeltaItem {
  id: string;
  title: string;
  source_uri: string | null;
  excerpt: string | null;
  created_at: string;
}

export interface IntakeDelta {
  items: IntakeDeltaItem[];
  proposedWatermark: IntakeWatermark | null;
}

export interface IntakeDeltaConfig {
  limit: number;
  skipWhenNoNewItems: boolean;
  sourceConnectionIds: string[];
}

const DEFAULT_DELTA_LIMIT = 25;
const MAX_DELTA_LIMIT = 100;

export function intakeDeltaConfig(
  configJson: Record<string, unknown> | null | undefined,
  defaultSkipWhenNoNewItems = false,
): IntakeDeltaConfig {
  const config = configJson && typeof configJson === "object" ? configJson : {};
  const rawLimit = (config as Record<string, unknown>).intake_delta_limit;
  const limit =
    typeof rawLimit === "number" && Number.isInteger(rawLimit) && rawLimit >= 1
      ? Math.min(rawLimit, MAX_DELTA_LIMIT)
      : DEFAULT_DELTA_LIMIT;
  // The explicit allowlist scopes the delta; an event trigger's
  // source_connection_ids is the fallback so an allowlist-only event
  // automation (no project binding) still has a delta scope.
  const event = (config as Record<string, unknown>).event;
  const sourceConnectionIds =
    stringIds((config as Record<string, unknown>).intake_source_connection_ids) ??
    stringIds(event && typeof event === "object" ? (event as Record<string, unknown>).source_connection_ids : null) ??
    [];
  const rawSkip = (config as Record<string, unknown>).skip_when_no_new_items;
  return {
    limit,
    skipWhenNoNewItems: typeof rawSkip === "boolean" ? rawSkip : defaultSkipWhenNoNewItems,
    sourceConnectionIds,
  };
}

function stringIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const ids = value.filter((id): id is string => typeof id === "string" && id.length > 0);
  return ids.length > 0 ? ids : null;
}

export function intakeCursorWatermark(
  cursorJson: Record<string, unknown> | null | undefined,
): IntakeWatermark | null {
  const watermark = cursorJson && typeof cursorJson === "object"
    ? (cursorJson as Record<string, unknown>).intake_watermark
    : null;
  if (!watermark || typeof watermark !== "object") return null;
  const createdAt = (watermark as Record<string, unknown>).created_at;
  const id = (watermark as Record<string, unknown>).id;
  if (typeof createdAt !== "string" || typeof id !== "string") return null;
  return { created_at: createdAt, id };
}

interface DeltaRow {
  id: string;
  title: string;
  source_uri: string | null;
  excerpt: string | null;
  created_at: string | Date;
}

/**
 * Items newer than the cursor from sources in scope: an explicit connection
 * allowlist when configured, otherwise every connection actively bound to the
 * automation's project. Ordered oldest-first so the proposed watermark is the
 * last returned row.
 */
export async function computeIntakeDelta(
  db: Queryable,
  input: {
    spaceId: string;
    projectId: string | null;
    sourceConnectionIds: string[];
    cursor: IntakeWatermark | null;
    limit: number;
  },
): Promise<IntakeDelta> {
  const params: unknown[] = [input.spaceId];
  let scopeSql: string;
  if (input.sourceConnectionIds.length > 0) {
    params.push(input.sourceConnectionIds);
    scopeSql = `ii.connection_id = ANY($${params.length}::varchar[])`;
  } else if (input.projectId) {
    params.push(input.projectId);
    scopeSql = `ii.connection_id IN (
        SELECT wsb.source_connection_id
          FROM workspace_source_bindings wsb
         WHERE wsb.space_id = $1
           AND wsb.project_id = $${params.length}
           AND wsb.status = 'active'
           AND EXISTS (
             SELECT 1
               FROM project_workspaces pw
              WHERE pw.space_id = wsb.space_id
                AND pw.project_id = wsb.project_id
                AND pw.workspace_id = wsb.workspace_id
           )
      )`;
  } else {
    return { items: [], proposedWatermark: null };
  }
  let cursorSql = "";
  if (input.cursor) {
    params.push(input.cursor.created_at);
    params.push(input.cursor.id);
    // The watermark is a millisecond-precision ISO string; truncate the column
    // to the same precision so the tuple comparison is exact regardless of the
    // microsecond remainder timestamptz can carry. ORDER BY must use the same
    // truncation, or same-millisecond rows could be cut by LIMIT on one side
    // of the watermark and skipped forever on the next fire.
    cursorSql = `AND (date_trunc('milliseconds', ii.created_at), ii.id) > ($${params.length - 1}::timestamptz, $${params.length})`;
  }
  params.push(input.limit);
  const result = await db.query<DeltaRow>(
    `SELECT ii.id, ii.title, ii.source_uri, ii.excerpt,
            date_trunc('milliseconds', ii.created_at) AS created_at
       FROM intake_items ii
      WHERE ii.space_id = $1
        AND ii.deleted_at IS NULL
        AND ${scopeSql}
        ${cursorSql}
      ORDER BY date_trunc('milliseconds', ii.created_at), ii.id
      LIMIT $${params.length}`,
    params,
  );
  const items = result.rows.map((row) => ({
    id: row.id,
    title: row.title,
    source_uri: row.source_uri,
    excerpt: row.excerpt,
    created_at: dateString(row.created_at),
  }));
  const last = items[items.length - 1];
  return {
    items,
    proposedWatermark: last ? { created_at: last.created_at, id: last.id } : null,
  };
}

/**
 * The current highest (created_at, id) watermark of the delta scope. Used to
 * initialize (or re-initialize on scope change) an automation's cursor so it
 * starts at "new items from now on" instead of replaying historical backlog.
 */
export async function currentIntakeWatermark(
  db: Queryable,
  input: { spaceId: string; projectId: string | null; sourceConnectionIds: string[] },
): Promise<IntakeWatermark | null> {
  const params: unknown[] = [input.spaceId];
  let scopeSql: string;
  if (input.sourceConnectionIds.length > 0) {
    params.push(input.sourceConnectionIds);
    scopeSql = `ii.connection_id = ANY($${params.length}::varchar[])`;
  } else if (input.projectId) {
    params.push(input.projectId);
    scopeSql = `ii.connection_id IN (
        SELECT wsb.source_connection_id
          FROM workspace_source_bindings wsb
         WHERE wsb.space_id = $1
           AND wsb.project_id = $${params.length}
           AND wsb.status = 'active'
           AND EXISTS (
             SELECT 1
               FROM project_workspaces pw
              WHERE pw.space_id = wsb.space_id
                AND pw.project_id = wsb.project_id
                AND pw.workspace_id = wsb.workspace_id
           )
      )`;
  } else {
    return null;
  }
  const result = await db.query<{ created_at: string | Date; id: string }>(
    `SELECT date_trunc('milliseconds', ii.created_at) AS created_at, ii.id
       FROM intake_items ii
      WHERE ii.space_id = $1
        AND ii.deleted_at IS NULL
        AND ${scopeSql}
      ORDER BY date_trunc('milliseconds', ii.created_at) DESC, ii.id DESC
      LIMIT 1`,
    params,
  );
  const row = result.rows[0];
  return row ? { created_at: dateString(row.created_at), id: row.id } : null;
}

/**
 * Canonical identity of an automation's delta scope; when it changes on
 * update, the cursor must be re-initialized for the new scope (a stale
 * watermark from the old scope would silently skip the new scope's items).
 */
export function intakeDeltaScopeKey(
  projectId: string | null,
  sourceConnectionIds: readonly string[],
): string {
  return sourceConnectionIds.length > 0
    ? `connections:${[...sourceConnectionIds].sort().join(",")}`
    : projectId
      ? `project:${projectId}`
      : "none";
}

export function renderIntakeDeltaInstruction(items: readonly IntakeDeltaItem[]): string {
  const lines = [
    `## New intake items since the last successful run (${items.length})`,
    "Each entry lists title, source URI, and intake_item_id for reference in outputs.",
    "",
  ];
  items.forEach((item, index) => {
    const source = item.source_uri ? ` — ${item.source_uri}` : "";
    lines.push(`${index + 1}. ${item.title}${source} (intake_item_id: ${item.id})`);
    if (item.excerpt) lines.push(`   ${item.excerpt.slice(0, 500)}`);
  });
  return lines.join("\n");
}

function dateString(value: string | Date): string {
  return value instanceof Date ? value.toISOString() : String(value);
}
