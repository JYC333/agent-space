import type { ServerConfig } from "../../config";
import { getDbPool } from "../../db/pool";
import type { JobHandlerRegistry } from "../jobs/handlerRegistry";
import { IntakeExtractionWorker } from "./extractionWorker";

export function registerIntakeExtractionHandler(
  registry: JobHandlerRegistry,
  config: ServerConfig,
): void {
  if (!config.databaseUrl) return;
  registry.register("intake_extraction", async (job) => {
    const extractionJobId = stringValue(job.payload.extraction_job_id);
    if (!extractionJobId) {
      throw new Error("intake_extraction job payload requires extraction_job_id");
    }
    const worker = new IntakeExtractionWorker(getDbPool(config.databaseUrl!), config);
    const result = await worker.runPendingJob(extractionJobId, job.space_id);
    return {
      extraction_job_id: result.id,
      status: result.status,
      job_type: result.job_type,
    };
  });
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
