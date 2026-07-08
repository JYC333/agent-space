import type { ServerConfig } from "../../../config";
import { getDbPool } from "../../../db/pool";
import type { PgJobQueueRepository } from "../../jobs/repository";
import {
  PgSourcePostProcessingRepository,
  SOURCE_POST_PROCESSING_EVENT_JOB_TYPE,
} from "./repository";

export async function enqueueDueSourcePostProcessingRules(
  config: ServerConfig,
  queue: PgJobQueueRepository,
  limit = 25,
): Promise<number> {
  if (!config.databaseUrl) return 0;
  const db = getDbPool(config.databaseUrl);
  const repo = new PgSourcePostProcessingRepository(db);
  const due = await repo.listDueRules(new Date().toISOString(), limit);
  let enqueued = 0;
  for (const rule of due) {
    try {
      await queue.enqueue({
        job_type: SOURCE_POST_PROCESSING_EVENT_JOB_TYPE,
        space_id: rule.space_id,
        user_id: rule.created_by_user_id,
        agent_id: rule.agent_id,
        payload: {
          trigger_type: "schedule",
          rule_id: rule.id,
          source_connection_id: rule.source_connection_id,
        },
      });
      await repo.recordRuleFire(rule.space_id, rule.id);
      enqueued += 1;
    } catch {
      // Leave scheduler state unchanged on enqueue failure.
    }
  }
  return enqueued;
}
