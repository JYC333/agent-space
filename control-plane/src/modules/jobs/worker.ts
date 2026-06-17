import {
  JobHandlerRegistry,
  type JobEnvelopeForHandler,
  type JobHandlerResult,
} from "./handlerRegistry";
import type { JobQueuePort } from "./queuePort";
import type { JobRecord } from "./repository";

export type JobProcessResult =
  | { status: "idle" }
  | { status: "completed"; job_id: string }
  | { status: "failed"; job_id: string; error: string };

const HANDLER_HEARTBEAT_INTERVAL_MS = 30_000;

export class JobWorker {
  constructor(
    private readonly queue: JobQueuePort,
    private readonly registry: JobHandlerRegistry,
    private readonly workerId: string,
    private readonly claimableJobTypes: readonly string[],
    private readonly heartbeatIntervalMs: number = HANDLER_HEARTBEAT_INTERVAL_MS,
  ) {}

  async processOne(): Promise<JobProcessResult> {
    const job = await this.queue.claimNext(
      this.workerId,
      this.claimableJobTypes.length > 0 ? this.claimableJobTypes : null,
    );
    if (!job) return { status: "idle" };

    const handler = this.registry.get(job.job_type);
    if (!handler) {
      const message = `No handler for job type: ${job.job_type}`;
      await this.queue.failJob(job.id, message, this.workerId);
      await this.safeAppendEvent(job.id, "error", message);
      return { status: "failed", job_id: job.id, error: message };
    }

    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    try {
      const envelope = toHandlerEnvelope(job, this.workerId);
      const started = await this.queue.startJob(job.id, this.workerId);
      if (!started) {
        const message = "Job start skipped because ownership or status changed";
        await this.safeAppendEvent(job.id, "warning", message, {
          worker_id: this.workerId,
          job_type: job.job_type,
        });
        return { status: "failed", job_id: job.id, error: message };
      }
      await this.safeAppendEvent(job.id, "status_change", "Job started by TS worker", {
        attempts: job.attempts,
        max_attempts: job.max_attempts,
        worker_id: this.workerId,
        job_type: job.job_type,
      });
      heartbeatTimer = setInterval(() => {
        void Promise.resolve(this.queue.touchHeartbeat(job.id, this.workerId)).catch(
          () => undefined,
        );
      }, this.heartbeatIntervalMs);
      heartbeatTimer.unref?.();

      const result = await handler(envelope);
      const completed = await this.queue.completeJob(job.id, result ?? null, this.workerId);
      if (!completed) {
        const message = "Job completion skipped because ownership or status changed";
        await this.safeAppendEvent(job.id, "warning", message, {
          worker_id: this.workerId,
          job_type: job.job_type,
        });
        return { status: "failed", job_id: job.id, error: message };
      }
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

function toHandlerEnvelope(job: JobRecord, workerId: string): JobEnvelopeForHandler {
  return {
    job_id: job.id,
    space_id: job.space_id,
    user_id: job.user_id,
    job_type: job.job_type,
    attempts: job.attempts,
    max_attempts: job.max_attempts,
    worker_id: workerId,
    payload: job.payload_json ?? {},
  };
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "unknown job failure";
}

export type AgentRunJobHandler = (
  job: JobEnvelopeForHandler,
) => Promise<JobHandlerResult>;

/** @deprecated Use {@link JobWorker} — kept for runs module compatibility. */
export class RunJobWorker extends JobWorker {
  constructor(
    queue: JobQueuePort,
    workerId: string,
    handler: AgentRunJobHandler,
    heartbeatIntervalMs?: number,
  ) {
    const registry = new JobHandlerRegistry();
    registry.register("agent_run", handler);
    super(queue, registry, workerId, ["agent_run"], heartbeatIntervalMs);
  }
}
