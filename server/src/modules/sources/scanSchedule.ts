import { randomUUID } from "node:crypto";
import type { Queryable } from "../routeUtils/common";
import { listDueSourceChannelScanTasks } from "./sourceConnectionScheduler";
import { computeNextRunAtFromScheduleRule, parseSourceScheduleRule } from "./sourceScheduleInput";

const INTERVAL_MS: Record<string, number> = {
  hourly: 60 * 60 * 1000,
  daily: 24 * 60 * 60 * 1000,
  weekly: 7 * 24 * 60 * 60 * 1000,
};

export function computeNextCheckAt(
  fetchFrequency: string,
  completedAt: Date | string = new Date(),
  options: { manualRun?: boolean; existingNextCheckAt?: unknown; scheduleRule?: unknown } = {},
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
  const scheduleRule = parseSourceScheduleRule(options.scheduleRule);
  if (scheduleRule?.frequency === fetchFrequency) {
    return computeNextRunAtFromScheduleRule(scheduleRule, new Date(completedMs));
  }
  return new Date(completedMs + interval).toISOString();
}

/**
 * Every scheduled scan is owned by a Channel. A Connection is only the
 * policy/credential boundary and may therefore back multiple independent
 * schedules.
 */
export async function enqueueDueSourceChannelScans(
  db: Queryable,
  batchLimit = 25,
): Promise<number> {
  const now = new Date().toISOString();
  const tasks = await listDueSourceChannelScanTasks(db, now, batchLimit);
  let enqueued = 0;
  for (const task of tasks) {
    if (!task.space_id) continue;
    const due = await db.query<{ id: string; space_id: string; source_connection_id: string }>(
      `SELECT ch.id, ch.space_id, ch.source_connection_id
         FROM source_channels ch
         JOIN source_connections sc ON sc.id = ch.source_connection_id
        WHERE ch.status = 'active'
          AND sc.status = 'active'
          AND sc.deleted_at IS NULL
          AND ch.space_id = $1
          AND ch.id = $2
          AND ch.fetch_frequency <> 'manual'
          AND sc.handler_kind = 'built_in'
          AND NOT EXISTS (
            SELECT 1
              FROM extraction_jobs ej
             WHERE ej.space_id = ch.space_id
               AND ej.connection_id = ch.source_connection_id
               AND ej.job_type = 'connection_scan'
               AND ej.metadata_json->>'source_channel_id' = ch.id
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
        row.source_connection_id,
        JSON.stringify({ created_by: "scheduler", source_channel_id: row.id }),
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
