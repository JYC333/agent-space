import { startJobsWorker, type JobsWorkerHandle } from "../jobs/workerRuntime";

export type RunsWorkerLogger = {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
};

export type RunsWorkerHandle = JobsWorkerHandle;

/** @deprecated Use the unified jobs worker via `startJobsWorker`. */
export function startRunsJobWorker(
  config: Parameters<typeof startJobsWorker>[0],
  log?: RunsWorkerLogger,
): RunsWorkerHandle | null {
  return startJobsWorker(config, log);
}
