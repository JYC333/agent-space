import { randomUUID } from "node:crypto";
import type { ControlPlaneConfig } from "../../config";
import { PgRunJobRepository } from "./jobRepository";
import { RunJobWorker } from "./jobWorker";
import { RunMaterializationService } from "./materializationService";
import { RunOrchestrationService } from "./orchestrationService";
import { PgRunRepository } from "./repository";
import { RunPythonContextPortClient } from "./pythonContextPorts";
import { sharedCliProcessRegistry } from "./processRegistry";

const POLL_INTERVAL_MS = 1_000;
const RECLAIM_INTERVAL_MS = 120_000;
const STUCK_AFTER_SECONDS = 600;

export interface RunsWorkerLogger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

export interface RunsWorkerHandle {
  worker_id: string;
  stop(): Promise<void>;
}

/**
 * Durable `agent_run` job consumption for the TS runs authority.
 *
 * This is the Stage 4 replacement for the retired Python `agent_run` handler:
 * the loop claims pending `agent_run` jobs, executes the referenced queued run
 * through `RunOrchestrationService`, heartbeats while the adapter runs, and
 * reclaims stuck work. Job payloads must carry `run_id` — run creation stays
 * Python-owned, so the legacy `task_id`/`agent_id` create-and-execute payload
 * variants fail with a stable error instead of silently creating runs in TS.
 */
export function startRunsJobWorker(
  config: ControlPlaneConfig,
  log?: RunsWorkerLogger,
): RunsWorkerHandle | null {
  if (config.runsAuthority !== "ts" || !config.databaseUrl) return null;

  const repository = PgRunRepository.fromConfig(config);
  const jobs = PgRunJobRepository.fromConfig(config);
  const contextPorts = new RunPythonContextPortClient(config);
  const materializer = new RunMaterializationService(contextPorts);
  const orchestration = new RunOrchestrationService(config, repository, {
    materializer,
    contextPorts,
    processRegistry: sharedCliProcessRegistry,
  });

  const workerId = `ts-agent-run-worker:${randomUUID()}`;
  const worker = new RunJobWorker(jobs, workerId, async (job) => {
    const runId = stringValue(job.payload.run_id);
    if (!runId) {
      throw new Error(
        "agent_run payload requires run_id under the TS runs authority; " +
          "task_id/agent_id create-and-execute payloads are not supported " +
          "(run creation remains Python-owned)",
      );
    }
    return orchestration.executeRun({
      run_id: runId,
      space_id: job.space_id,
      worker_id: job.worker_id,
      job_id: job.job_id,
      command_source: "job",
    });
  });

  let stopped = false;
  let lastReclaim = 0;

  const loop = (async () => {
    log?.info(`[runs-worker] started (${workerId})`);
    while (!stopped) {
      try {
        const now = Date.now();
        if (now - lastReclaim >= RECLAIM_INTERVAL_MS) {
          const reclaimed = await worker.reclaimStuckJobs(STUCK_AFTER_SECONDS);
          if (reclaimed > 0) log?.warn(`[runs-worker] reclaimed ${reclaimed} stuck job(s)`);
          lastReclaim = now;
        }
        const result = await worker.processOne();
        if (result.status === "idle") {
          await sleep(POLL_INTERVAL_MS);
        } else if (result.status === "failed") {
          log?.warn(`[runs-worker] job ${result.job_id} failed: ${result.error}`);
        }
      } catch (error) {
        log?.error(
          `[runs-worker] loop error: ${error instanceof Error ? error.message : String(error)}`,
        );
        await sleep(POLL_INTERVAL_MS);
      }
    }
    log?.info(`[runs-worker] stopped (${workerId})`);
  })();

  return {
    worker_id: workerId,
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

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
