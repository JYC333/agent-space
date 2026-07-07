import { PgJobQueueRepository } from "../../jobs/repository";
import type { Queryable } from "../../routeUtils/common";
import { PgSourcePostProcessingRepository, SOURCE_POST_PROCESSING_EVENT_JOB_TYPE } from "./repository";

/**
 * Best-effort source post-processing signal after intake materializes new
 * items. A failed enqueue must not fail the scan that produced the items.
 */
export async function emitSourcePostProcessingEvent(
  db: Queryable,
  input: { spaceId: string; sourceConnectionId: string | null; newItemCount: number },
): Promise<void> {
  if (!input.sourceConnectionId || input.newItemCount < 1) return;
  try {
    await new PgJobQueueRepository(db).enqueue({
      job_type: SOURCE_POST_PROCESSING_EVENT_JOB_TYPE,
      payload: {
        source_connection_id: input.sourceConnectionId,
        new_item_count: input.newItemCount,
        trigger_type: "items_materialized",
      },
      space_id: input.spaceId,
      user_id: null,
    });
  } catch {
    // Scheduled post-processing rules keep their own cursor and can recover on
    // their next sweep.
  }
}

export async function emitSourcePostProcessingDeepAnalysisEvent(
  db: Queryable,
  input: {
    spaceId: string;
    sourceConnectionId: string | null;
    intakeItemId: string | null;
    metadata: Record<string, unknown> | null;
  },
): Promise<void> {
  if (!input.sourceConnectionId || !input.intakeItemId) return;
  const metadata = input.metadata ?? {};
  const followups = sourcePostProcessingFollowups(metadata);
  if (!followups.length) return;
  const queuedBySourceRun = new Map<string, string[]>();
  try {
    const jobs = new PgJobQueueRepository(db);
    const seen = new Set<string>();
    for (const followup of followups) {
      const ruleId = stringValue(followup.source_post_processing_rule_id);
      if (!ruleId) continue;
      const sourceRunId = stringValue(followup.source_post_processing_run_id);
      const key = `${ruleId}:${sourceRunId ?? ""}:${input.intakeItemId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const job = await jobs.enqueue({
        job_type: SOURCE_POST_PROCESSING_EVENT_JOB_TYPE,
        payload: {
          phase: "deep_analysis",
          trigger_type: "manual",
          source_connection_id: input.sourceConnectionId,
          rule_id: ruleId,
          intake_item_ids: [input.intakeItemId],
          source_post_processing_run_id: sourceRunId,
        },
        space_id: input.spaceId,
        user_id: stringValue(followup.triggered_by_user_id),
      });
      if (sourceRunId) {
        const current = queuedBySourceRun.get(sourceRunId) ?? [];
        current.push(job.id);
        queuedBySourceRun.set(sourceRunId, current);
      }
    }
    const repo = new PgSourcePostProcessingRepository(db);
    for (const [sourceRunId, jobIds] of queuedBySourceRun) {
      await repo.appendRunOutputJobIds(input.spaceId, sourceRunId, jobIds);
    }
  } catch {
    // The review surface can re-run deep analysis manually; extraction success
    // must not be rolled back because the follow-up signal failed.
  }
}

function sourcePostProcessingFollowups(metadata: Record<string, unknown>): Record<string, unknown>[] {
  const value = metadata.source_post_processing_followups;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> =>
    Boolean(item && typeof item === "object" && !Array.isArray(item) && item.phase === "deep_analysis"));
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
