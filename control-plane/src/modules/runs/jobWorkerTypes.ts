import type { RunJobRecord } from "./jobRepository";

export interface RunJobEnvelopeForHandler {
  job_id: string;
  space_id: string;
  user_id: string;
  attempts: number;
  max_attempts: number;
  worker_id: string;
  payload: Record<string, unknown>;
}

export interface RunJobQueuePort {
  claimNextAgentRun(workerId: string): Promise<RunJobRecord | null>;
  startJob(jobId: string, workerId: string | null): Promise<boolean>;
  completeJob(
    jobId: string,
    resultJson: unknown,
    workerId: string | null,
  ): Promise<boolean>;
  failJob(
    jobId: string,
    error: string,
    workerId: string | null,
  ): Promise<string | null>;
  cancelJob(jobId: string, workerId: string | null): Promise<boolean>;
  touchHeartbeat(jobId: string, workerId: string | null): Promise<boolean>;
  appendJobEvent(input: {
    job_id: string;
    event_type: string;
    message: string;
    data?: unknown;
  }): Promise<unknown>;
  reclaimStuckJobs(stuckAfterSeconds?: number): Promise<{ reclaimed_count: number }>;
}
