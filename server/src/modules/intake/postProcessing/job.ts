import type { ServerConfig } from "../../../config";
import { getDbPool } from "../../../db/pool";
import type { JobEnvelopeForHandler, JobHandlerRegistry } from "../../jobs/handlerRegistry";
import type { JobHandlerResult } from "../../jobs/handlerRegistry";
import { SourcePostProcessingService } from "./service";
import {
  PgSourcePostProcessingRepository,
  SOURCE_POST_PROCESSING_EVENT_JOB_TYPE,
  type SourcePostProcessingTriggerType,
} from "./repository";

export function registerSourcePostProcessingHandler(
  registry: JobHandlerRegistry,
  config: ServerConfig,
): void {
  if (!config.databaseUrl) return;
  registry.register(SOURCE_POST_PROCESSING_EVENT_JOB_TYPE, async (job) =>
    handleSourcePostProcessingJob(job, config),
  );
}

async function handleSourcePostProcessingJob(
  job: JobEnvelopeForHandler,
  config: ServerConfig,
): Promise<JobHandlerResult> {
  const db = getDbPool(config.databaseUrl!);
  const service = new SourcePostProcessingService(db, config);
  const phase = stringValue(job.payload.phase);
  const triggerType = stringValue(job.payload.trigger_type) as SourcePostProcessingTriggerType | null;
  const ruleId = stringValue(job.payload.rule_id);
  if (phase === "deep_analysis" && ruleId) {
    const itemIds = arrayValue(job.payload.intake_item_ids);
    const run = await service.runDeepAnalysisForItems({
      spaceId: job.space_id,
      ruleId,
      itemIds,
      actorUserId: job.user_id,
      sourceRunId: stringValue(job.payload.source_post_processing_run_id),
    });
    return {
      source_post_processing_run_id: run?.id ?? null,
      status: run?.status ?? "skipped",
      rule_id: ruleId,
      phase,
    };
  }
  if (triggerType === "schedule" && ruleId) {
    const repo = new PgSourcePostProcessingRepository(db);
    const rule = await repo.getRule(job.space_id, ruleId);
    if (!rule) throw new Error("source_post_processing_event schedule payload references missing rule");
    const run = await service.fireScheduledRule(rule);
    return {
      source_post_processing_run_id: run.id,
      status: run.status,
      rule_id: rule.id,
    };
  }
  const sourceConnectionId = stringValue(job.payload.source_connection_id);
  if (!sourceConnectionId) {
    throw new Error("source_post_processing_event payload requires source_connection_id");
  }
  const result = await service.fireSourceEvent({
    spaceId: job.space_id,
    sourceConnectionId,
    newItemCount: numberValue(job.payload.new_item_count) ?? 0,
  });
  return result;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function arrayValue(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}
