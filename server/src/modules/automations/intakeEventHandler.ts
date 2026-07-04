import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import type { JobHandlerRegistry } from "../jobs/handlerRegistry";
import { AUTOMATION_INTAKE_EVENT_JOB_TYPE } from "../intake/automationEventEmitter";
import { AutomationService } from "./service";
import { PgAutomationRepository } from "./repository";

export function registerAutomationIntakeEventHandler(
  registry: JobHandlerRegistry,
  config: ServerConfig,
): void {
  if (!config.databaseUrl) return;
  registry.register(AUTOMATION_INTAKE_EVENT_JOB_TYPE, async (job) => {
    const sourceConnectionId = stringValue(job.payload.source_connection_id);
    if (!sourceConnectionId) {
      throw new Error("automation_intake_event job payload requires source_connection_id");
    }
    const newItemCount = numberValue(job.payload.new_item_count);
    const service = new AutomationService(
      config,
      new PgAutomationRepository(getDbPool(config.databaseUrl!)),
    );
    const result = await service.fireIntakeEventAutomations({
      spaceId: job.space_id,
      sourceConnectionId,
      newItemCount,
    });
    return {
      source_connection_id: sourceConnectionId,
      new_item_count: newItemCount,
      matched: result.matched,
      fired: result.fired,
      skipped: result.skipped,
    };
  });
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
