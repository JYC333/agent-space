import {
  PgSchedulerTaskStore,
  type SchedulerTaskRow,
  type SchedulerTaskStatus,
} from "../scheduler/taskStore";
import type { Queryable } from "../routeUtils/common";
import type { SourceConnectionRow } from "./intakeRepositoryRows";

export const SOURCE_CONNECTION_SCAN_TASK_TYPE = "source_connection_scan";

export interface SourceConnectionScheduleTarget {
  id: string;
  space_id: string;
  owner_user_id: string;
  status: string;
  fetch_frequency: string;
}

export function sourceConnectionSchedulerTaskKey(connectionId: string): string {
  return connectionId;
}

export async function getSourceConnectionScanTask(
  db: Queryable,
  connectionId: string,
): Promise<SchedulerTaskRow | null> {
  return new PgSchedulerTaskStore(db).get(
    SOURCE_CONNECTION_SCAN_TASK_TYPE,
    sourceConnectionSchedulerTaskKey(connectionId),
  );
}

export async function listDueSourceConnectionScanTasks(
  db: Queryable,
  nowIso: string,
  limit: number,
): Promise<SchedulerTaskRow[]> {
  return new PgSchedulerTaskStore(db).listDue(
    SOURCE_CONNECTION_SCAN_TASK_TYPE,
    nowIso,
    limit,
  );
}

export async function upsertSourceConnectionScanTask(
  db: Queryable,
  input: {
    connection: SourceConnectionScheduleTarget;
    nextRunAt: string | null;
    lastRunAt?: string | null;
    updatedAt?: string;
  },
): Promise<SchedulerTaskRow> {
  const taskStore = new PgSchedulerTaskStore(db);
  const existing = await taskStore.get(
    SOURCE_CONNECTION_SCAN_TASK_TYPE,
    sourceConnectionSchedulerTaskKey(input.connection.id),
  );
  const status = sourceConnectionSchedulerStatus(input.connection.status);
  const stateJson = { ...(existing?.state_json ?? {}) };
  delete stateJson.schedule_rule;
  return taskStore.upsert({
    taskType: SOURCE_CONNECTION_SCAN_TASK_TYPE,
    taskKey: sourceConnectionSchedulerTaskKey(input.connection.id),
    scopeType: "space",
    scopeId: input.connection.space_id,
    spaceId: input.connection.space_id,
    userId: input.connection.owner_user_id,
    status,
    nextRunAt: status === "archived" ? null : input.nextRunAt,
    lastRunAt: input.lastRunAt ?? null,
    stateJson,
    updatedAt: input.updatedAt,
  });
}

export function sourceConnectionWithSchedule(
  row: SourceConnectionRow,
  task: SchedulerTaskRow | null,
): SourceConnectionRow {
  return {
    ...row,
    last_checked_at: timestampString(task?.last_run_at) ?? row.last_checked_at ?? null,
    next_check_at: timestampString(task?.next_run_at) ?? row.next_check_at ?? null,
  };
}

function sourceConnectionSchedulerStatus(status: string): SchedulerTaskStatus {
  if (status === "archived") return "archived";
  if (status === "active") return "active";
  return "paused";
}

function timestampString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  const raw = String(value);
  return raw.length > 0 ? raw : null;
}
