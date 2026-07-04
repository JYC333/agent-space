import { PgJobQueueRepository } from "../jobs/repository";
import type { Queryable } from "../routeUtils/common";

export const AUTOMATION_INTAKE_EVENT_JOB_TYPE = "automation_intake_event";

/**
 * Emit an internal "intake items materialized" event after a scan created new
 * items. Delivery is decoupled through the job queue (at-least-once); the
 * consumer's cooldown plus the automation intake cursor make duplicate or
 * coalesced deliveries harmless. Best-effort: an emission failure must never
 * fail the scan that produced the items.
 */
export async function emitIntakeItemsMaterializedEvent(
  db: Queryable,
  input: { spaceId: string; sourceConnectionId: string | null; newItemCount: number },
): Promise<void> {
  if (!input.sourceConnectionId || input.newItemCount < 1) return;
  try {
    await new PgJobQueueRepository(db).enqueue({
      job_type: AUTOMATION_INTAKE_EVENT_JOB_TYPE,
      payload: {
        source_connection_id: input.sourceConnectionId,
        new_item_count: input.newItemCount,
      },
      space_id: input.spaceId,
      user_id: null,
    });
  } catch {
    // Scheduled scans will still surface the items through the intake delta
    // cursor on the next scheduled fire.
  }
}
