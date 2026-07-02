import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import { listDueSourceConnectionScanTasks } from "./sourceConnectionScheduler";

const INTERVAL_MS: Record<string, number> = {
  hourly: 60 * 60 * 1000,
  daily: 24 * 60 * 60 * 1000,
  weekly: 7 * 24 * 60 * 60 * 1000,
};

export function computeNextCheckAt(
  fetchFrequency: string,
  completedAt: Date | string = new Date(),
  options: { manualRun?: boolean; existingNextCheckAt?: unknown } = {},
): string | null {
  if (fetchFrequency === "manual") return null;
  const interval = INTERVAL_MS[fetchFrequency];
  if (!interval) return null;
  const completed = typeof completedAt === "string" ? new Date(completedAt) : completedAt;
  const completedMs = Number.isNaN(completed.getTime()) ? Date.now() : completed.getTime();
  const existing = dateValue(options.existingNextCheckAt);
  if (options.manualRun && existing && existing.getTime() > completedMs) {
    return existing.toISOString();
  }
  return new Date(completedMs + interval).toISOString();
}

/**
 * built_in-only: `IntakeExtractionWorker` dispatches on a fixed
 * `connector_key` allowlist (rss/atom/web_page) and 422s on anything else.
 * Custom Source connections are polled separately by
 * `enqueueDueCustomSourceHandlerRuns` (customSourceScanSchedule.ts).
 */
export async function enqueueDueSourceConnectionScans(
  db: Queryable,
  batchLimit = 25,
): Promise<number> {
  const now = new Date().toISOString();
  const tasks = await listDueSourceConnectionScanTasks(db, now, batchLimit);
  let enqueued = 0;
  for (const task of tasks) {
    if (!task.space_id) continue;
    const due = await db.query<{ id: string; space_id: string }>(
      `SELECT sc.id, sc.space_id
         FROM source_connections sc
        WHERE sc.status = 'active'
          AND sc.deleted_at IS NULL
          AND sc.space_id = $1
          AND sc.id = $2
          AND sc.handler_kind = 'built_in'
          AND sc.fetch_frequency <> 'manual'
          AND NOT EXISTS (
            SELECT 1
              FROM extraction_jobs ej
             WHERE ej.space_id = sc.space_id
               AND ej.connection_id = sc.id
               AND ej.job_type = 'connection_scan'
               AND ej.status IN ('pending', 'running')
          )
        LIMIT 1`,
      [task.space_id, task.task_key],
    );
    const row = due.rows[0];
    if (!row) continue;
    await db.query(
      `INSERT INTO extraction_jobs (
         id, space_id, connection_id, job_type, status, metadata_json, created_at
       ) VALUES ($1, $2, $3, 'connection_scan', 'pending', $4::jsonb, $5)`,
      [
        randomUUID(),
        row.space_id,
        row.id,
        JSON.stringify({ created_by: "scheduler" }),
        now,
      ],
    );
    enqueued += 1;
  }
  return enqueued;
}

function dateValue(value: unknown): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date;
}
