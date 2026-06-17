import { randomUUID } from "node:crypto";
import type { ServerConfig } from "../../config";
import { JobHandlerRegistry } from "./handlerRegistry";
import { PgJobQueueRepository } from "./repository";
import { JobWorker } from "./worker";
import { registerAgentRunHandler } from "../runs/agentRunHandler";
import { registerMemoryConsolidationHandler } from "../activity/consolidationJob";
import { registerDailyCaptureReportHandler } from "../dailyReports/jobHandler";
import { PgRunRepository } from "../runs/repository";

const POLL_INTERVAL_MS = 1_000;
const RECLAIM_INTERVAL_MS = 120_000;
const STUCK_AFTER_SECONDS = 600;

export interface JobsWorkerLogger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

export interface JobsWorkerHandle {
  worker_id: string;
  registry: JobHandlerRegistry;
  queue: PgJobQueueRepository;
  stop(): Promise<void>;
}

export function buildJobHandlerRegistry(config: ServerConfig): JobHandlerRegistry {
  const registry = new JobHandlerRegistry();
  registerAgentRunHandler(registry, config);
  registerMemoryConsolidationHandler(registry, config);
  registerDailyCaptureReportHandler(registry, config);
  return registry;
}

export function startJobsWorker(
  config: ServerConfig,
  log?: JobsWorkerLogger,
): JobsWorkerHandle | null {
  if (!config.databaseUrl) return null;

  const queue = PgJobQueueRepository.fromConfig(config);
  const runs = PgRunRepository.fromConfig(config);
  const registry = buildJobHandlerRegistry(config);
  const claimableJobTypes = registry.registeredJobTypes();
  if (claimableJobTypes.length === 0) {
    throw new Error("Job worker started with zero registered handlers");
  }

  const workerId = `ts-job-worker:${randomUUID()}`;
  const worker = new JobWorker(queue, registry, workerId, claimableJobTypes);

  let stopped = false;
  let lastReclaim = 0;

  const loop = (async () => {
    log?.info(`[jobs-worker] started (${workerId}) types=${claimableJobTypes.join(",")}`);
    try {
      const recovered = await runs.recoverStaleRuns(3600);
      if (recovered > 0) log?.warn(`[jobs-worker] recovered ${recovered} stale run(s)`);
    } catch (error) {
      log?.error(
        `[jobs-worker] stale run recovery failed: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
    while (!stopped) {
      try {
        const now = Date.now();
        if (now - lastReclaim >= RECLAIM_INTERVAL_MS) {
          const reclaimed = await worker.reclaimStuckJobs(STUCK_AFTER_SECONDS);
          if (reclaimed > 0) log?.warn(`[jobs-worker] reclaimed ${reclaimed} stuck job(s)`);
          lastReclaim = now;
        }
        const result = await worker.processOne();
        if (result.status === "idle") {
          await sleep(POLL_INTERVAL_MS);
        } else if (result.status === "failed") {
          log?.warn(`[jobs-worker] job ${result.job_id} failed: ${result.error}`);
        }
      } catch (error) {
        log?.error(
          `[jobs-worker] loop error: ${error instanceof Error ? error.message : String(error)}`,
        );
        await sleep(POLL_INTERVAL_MS);
      }
    }
    log?.info(`[jobs-worker] stopped (${workerId})`);
  })();

  return {
    worker_id: workerId,
    registry,
    queue,
    stop: async () => {
      stopped = true;
      await loop;
    },
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => {
    const timer = setTimeout(resolveSleep, ms);
    timer.unref?.();
  });
}
