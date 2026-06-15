import type { RunJobResult } from "@agent-space/protocol" with { "resolution-mode": "import" };
import type {
  PgRunJobRepository,
  RunJobRecord,
} from "./jobRepository";

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

export type AgentRunJobHandler = (
  job: RunJobEnvelopeForHandler,
) => Promise<RunJobResult | null | undefined>;

export type RunJobProcessResult =
  | { status: "idle" }
  | { status: "completed"; job_id: string }
  | { status: "failed"; job_id: string; error: string };

const HANDLER_HEARTBEAT_INTERVAL_MS = 30_000;

export class RunJobWorker {
  constructor(
    private readonly queue: RunJobQueuePort | PgRunJobRepository,
    private readonly workerId: string,
    private readonly handler: AgentRunJobHandler,
    private readonly heartbeatIntervalMs: number = HANDLER_HEARTBEAT_INTERVAL_MS,
  ) {}

  async processOne(): Promise<RunJobProcessResult> {
    const job = await this.queue.claimNextAgentRun(this.workerId);
    if (!job) return { status: "idle" };

    // Heartbeat while the handler runs so reclaim sweeps (Python or TS) do not
    // evict a live long-running execution as stuck.
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    try {
      const envelope = toHandlerEnvelope(job, this.workerId);
      await this.queue.startJob(job.id, this.workerId);
      await this.safeAppendEvent(job.id, "status_change", "Job started by TS worker", {
        attempts: job.attempts,
        max_attempts: job.max_attempts,
        worker_id: this.workerId,
      });
      heartbeatTimer = setInterval(() => {
        void Promise.resolve(this.queue.touchHeartbeat(job.id, this.workerId)).catch(
          () => undefined,
        );
      }, this.heartbeatIntervalMs);
      heartbeatTimer.unref?.();

      const result = await this.handler(envelope);
      await this.queue.completeJob(job.id, result ?? null, this.workerId);
      await this.safeAppendEvent(job.id, "status_change", "Job completed successfully");
      return { status: "completed", job_id: job.id };
    } catch (error) {
      const message = errorMessage(error);
      await this.queue.failJob(job.id, message, this.workerId);
      await this.safeAppendEvent(job.id, "error", `Job failed: ${message}`);
      return { status: "failed", job_id: job.id, error: message };
    } finally {
      if (heartbeatTimer) clearInterval(heartbeatTimer);
    }
  }

  async cancelJob(jobId: string): Promise<boolean> {
    return this.queue.cancelJob(jobId, this.workerId);
  }

  async heartbeat(jobId: string): Promise<boolean> {
    return this.queue.touchHeartbeat(jobId, this.workerId);
  }

  async reclaimStuckJobs(stuckAfterSeconds = 600): Promise<number> {
    const result = await this.queue.reclaimStuckJobs(stuckAfterSeconds);
    return result.reclaimed_count;
  }

  private async safeAppendEvent(
    jobId: string,
    eventType: string,
    message: string,
    data?: unknown,
  ): Promise<void> {
    try {
      await this.queue.appendJobEvent({
        job_id: jobId,
        event_type: eventType,
        message,
        data,
      });
    } catch {
      return;
    }
  }
}

function toHandlerEnvelope(
  job: RunJobRecord,
  workerId: string,
): RunJobEnvelopeForHandler {
  const payload = job.payload_json ?? {};
  if (!payload.run_id && !payload.task_id && !payload.agent_id) {
    throw new Error("agent_run payload requires run_id, task_id, or agent_id");
  }
  if (!job.user_id) {
    throw new Error("agent_run job requires user_id");
  }
  return {
    job_id: job.id,
    space_id: job.space_id,
    user_id: job.user_id,
    attempts: job.attempts,
    max_attempts: job.max_attempts,
    worker_id: workerId,
    payload,
  };
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "unknown job failure";
}
